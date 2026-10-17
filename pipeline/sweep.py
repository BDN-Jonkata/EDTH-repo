"""The whole pipeline (sensors, lossy network, tracker, friend/foe) scored over message loss.

    python -m pipeline.sweep --set test --seeds 20
    python -m pipeline.sweep --weather fog+wind --csv out/pipeline_sweep.csv
    python -m pipeline.sweep --paired investigate --set test --seeds 20   # does sending drones help?

Every cell is a mean over the seeds, printed with its standard error (`mean±error`). Loss is applied to every
message: observations and beacons alike (`common/channel.py`). Tune on the tuning seeds only; report on the
test seeds. Without a behaviour module nothing is called hostile or peaceful, so every track that is not a
confirmed friendly counts as a hostile.

`--paired investigate` runs each seed twice, without and with investigation, and prints the mean difference
(with minus without) and its standard error per column. A difference under about two standard errors is
seed noise.
"""

import argparse
import csv
from dataclasses import replace
from pathlib import Path
from typing import Dict, List

from friend_foe.sweep import LOSSES, Setup, load_preset, make_scenario_and_truth, seeder_scenario
from pipeline.behaviour import automatic_estimator
from pipeline.run import scored_frames
from scoring.identification import identification
from scoring.metrics import RunScore, ScoreConfig, score, swap_log
from scoring.swaps import summarise
from sensors.quality import load_modules
from scoring.sweep import COLUMNS, average_with_error, fmt_error, paired_difference
from scoring.truth import with_recorded_samples

WARMUP_S = 10.0
OPTIONS = {"investigate": "investigate", "identity": "keep_identity", "distributed": "distributed", "cueing": "cue", "trust": "trust", "oosm": "oosm", "sectors": "sectors", "ground-first": "ground_first"}   # --paired name -> option


def run_once(setup: Setup, index: int, weather: str, loss: float, behaviour: str = "", **options) -> RunScore:
    """`behaviour` ("safe" or "raw", see `pipeline/behaviour.py`) puts the automatic drone-behaviour module
    (`drone_behavior/`) behind the estimator's threat hook; True counts as "safe".
    `options` go to `scored_frames`: `investigate` sends drones at suspicious tracks and scores against the
    trajectories they really flew; `keep_identity` runs the predictor's identity keeper; `distributed` runs a
    tracker per node and the merger instead of one central tracker."""
    scenario, truth = make_scenario_and_truth(setup, index, weather, loss, False)
    estimator = automatic_estimator(scenario, motion_peaceful=behaviour == "raw") if behaviour else None
    recorded: dict = {}
    frames = list(scored_frames(scenario, scenario["seed"], estimator=estimator, recorded=recorded, **options))
    truth = with_recorded_samples(truth, recorded)
    covered, delay = identification(truth, identification_ranges(scenario), WARMUP_S)
    return replace(score(truth, frames, ScoreConfig(warmup_s=WARMUP_S)), ident_covered_frac=covered, ident_delay_s=delay)


def identification_ranges(scenario: dict) -> Dict[str, float]:
    """Each friendly drone's best identification range, from the catalog's `sim.ident_range_m` (assumed numbers)."""
    modules = load_modules()
    return {f["id"]: max(modules[s["module"]]["sim"].get("ident_range_m", 0.0) for s in f["sensors"])
            for f in scenario["friendlies"]}


def run_cell(setup: Setup, weather: str, loss: float, behaviour: str = "", **options) -> List[RunScore]:
    return [run_once(setup, i, weather, loss, behaviour, **options) for i in range(setup.seeds)]

def swap_causes(setup: Setup, weather: str, loss: float, behaviour: str = "", **options) -> dict:
    """Why the hostiles' IDs swap, summed over the seeds (scoring/swaps.py)."""
    total: dict = {}
    for i in range(setup.seeds):
        scenario, truth = make_scenario_and_truth(setup, i, weather, loss, False)
        recorded: dict = {}
        frames = list(scored_frames(scenario, scenario["seed"], recorded=recorded, **options))
        events = swap_log(with_recorded_samples(truth, recorded), frames, ScoreConfig(warmup_s=WARMUP_S))
        for key, n in summarise(events).items():
            total[key] = total.get(key, 0) + n
    return total


def print_table(title: str, rows) -> None:
    print(title)
    print(" | ".join(["loss"] + [c.replace("_", " ") for c in COLUMNS]))
    for loss, cell in rows:
        print(" | ".join([str(loss)] + [fmt_error(cell[c]) for c in COLUMNS]))


def write_csv(path: str, rows) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["loss", *[f"{c}{suffix}" for c in COLUMNS for suffix in ("", "_sem")]])
        w.writerows([loss, *[x for c in COLUMNS for x in cell[c]]] for loss, cell in rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", default="medium")
    ap.add_argument("--set", dest="seed_set", default="tuning", choices=sorted(seeder_scenario.SEED_SETS))
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--weather", default="clear")
    ap.add_argument("--birds", type=int, default=0)
    ap.add_argument("--vehicles", type=int, default=0)
    ap.add_argument("--behaviour", nargs="?", const="safe", choices=["safe", "raw"],
                    help="use the automatic drone-behaviour module: `safe` (the default when given) never lets motion "
                         "alone call a track peaceful, `raw` is the module's own behaviour (pipeline/behaviour.py)")
    ap.add_argument("--investigate", action="store_true", help="send drones at suspicious tracks (pipeline/dispatch.py)")
    ap.add_argument("--keep-identity", nargs="?", const=True, choices=["learned"],
                    help="run the predictor's identity keeper on the tracks; `learned` sizes its gate with the model "
                         "from `python -m predictor.train` (predictor/motion.py)")
    ap.add_argument("--cue", action="store_true", help="send the closest other drone at a bearing no track explains (pipeline/cueing.py)")
    ap.add_argument("--trust", action="store_true", help="weight readings by link health and discount explained silence (health/)")
    ap.add_argument("--oosm", action="store_true", help="apply a late reading at the time it was taken (tracker/oosm.py)")
    ap.add_argument("--sectors", action="store_true", help="planned patrol sectors and a neighbour covering a busy drone's sector (pipeline/sectors.py)")
    ap.add_argument("--place-ground", action="store_true", help="with --sectors: also plan where the ground sensors stand")
    ap.add_argument("--cluster", type=float, metavar="W", help="with --sectors: a cell seen twice counts W times a cell seen once (default 1; larger pulls the drones together)")
    ap.add_argument("--ground-first", action="store_true", help="no drone for a track a ground sensor can identify (with --investigate)")
    ap.add_argument("--distributed", action="store_true", help="a tracker per node and a merger (pipeline/nodes.py)")
    ap.add_argument("--paired", choices=sorted(OPTIONS), help="compare with and without this on the same seeds")
    ap.add_argument("--losses", default=",".join(str(x) for x in LOSSES), help="comma-separated message-loss levels")
    ap.add_argument("--swaps", action="store_true", help="print why the hostiles' IDs swap (scoring/swaps.py) instead of the table")
    ap.add_argument("--csv")
    args = ap.parse_args()
    losses = [float(x) for x in args.losses.split(",")]
    setup = Setup(load_preset(args.preset), args.seed_set, args.seeds, None, args.birds, args.vehicles)
    header = (f"preset={args.preset} seed set={args.seed_set} seeds={args.seeds} weather={args.weather} "
              f"birds={args.birds} vehicles={args.vehicles} behaviour={args.behaviour}")
    base = {"investigate": args.investigate, "keep_identity": args.keep_identity, "distributed": args.distributed,
            "cue": args.cue, "trust": args.trust, "oosm": args.oosm,
            "sectors": {"place_ground": args.place_ground, "overlap": args.cluster or 1.0} if args.sectors else False,
            "ground_first": args.ground_first}
    if args.swaps:
        for loss in losses:
            print(f"loss {loss}: {swap_causes(setup, args.weather, loss, args.behaviour, **base)}")
        return
    if args.paired:
        flag = OPTIONS[args.paired]
        rows = [(loss, paired_difference(run_cell(setup, args.weather, loss, args.behaviour, **{**base, flag: False}),
                                         run_cell(setup, args.weather, loss, args.behaviour, **{**base, flag: base[flag] or True})))
                for loss in losses]
        print_table(f"{header}\nmean difference, {args.paired} on minus off (±standard error)", rows)
    else:
        rows = [(loss, average_with_error(run_cell(setup, args.weather, loss, args.behaviour, **base))) for loss in losses]
        print_table(f"{header} {base}", rows)
    if args.csv:
        write_csv(args.csv, rows)


if __name__ == "__main__":
    main()
