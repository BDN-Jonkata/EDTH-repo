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
from pathlib import Path
from typing import Dict, List

from friend_foe.automatic import AutomaticEstimator
from friend_foe.sweep import LOSSES, Setup, load_preset, make_scenario_and_truth, seeder_scenario
from pipeline.run import scored_frames
from scoring.metrics import RunScore, ScoreConfig, score
from scoring.sweep import COLUMNS, average_with_error, fmt_error, paired_difference
from scoring.truth import with_recorded_samples

WARMUP_S = 10.0


def run_once(setup: Setup, index: int, weather: str, loss: float, behaviour: bool = False,
             investigate: bool = False) -> RunScore:
    """`behaviour` puts the automatic drone-behaviour module (`drone_behavior/`) behind the estimator's threat hook;
    `investigate` sends drones at suspicious tracks, and scores against the trajectories they really flew."""
    scenario, truth = make_scenario_and_truth(setup, index, weather, loss, False)
    estimator = AutomaticEstimator.for_scenario(scenario) if behaviour else None
    recorded: dict = {}
    frames = list(scored_frames(scenario, scenario["seed"], estimator=estimator, investigate=investigate, recorded=recorded))
    return score(with_recorded_samples(truth, recorded), frames, ScoreConfig(warmup_s=WARMUP_S))


def run_cell(setup: Setup, weather: str, loss: float, behaviour: bool = False, investigate: bool = False) -> List[RunScore]:
    return [run_once(setup, i, weather, loss, behaviour, investigate) for i in range(setup.seeds)]


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
    ap.add_argument("--behaviour", action="store_true", help="use the automatic drone-behaviour module")
    ap.add_argument("--investigate", action="store_true", help="send drones at suspicious tracks (pipeline/dispatch.py)")
    ap.add_argument("--paired", choices=["investigate"], help="compare with and without this on the same seeds")
    ap.add_argument("--losses", default=",".join(str(x) for x in LOSSES), help="comma-separated message-loss levels")
    ap.add_argument("--csv")
    args = ap.parse_args()
    losses = [float(x) for x in args.losses.split(",")]
    setup = Setup(load_preset(args.preset), args.seed_set, args.seeds, None, args.birds, args.vehicles)
    header = (f"preset={args.preset} seed set={args.seed_set} seeds={args.seeds} weather={args.weather} "
              f"birds={args.birds} vehicles={args.vehicles} behaviour={args.behaviour}")
    if args.paired:
        rows = []
        for loss in losses:
            off = run_cell(setup, args.weather, loss, args.behaviour, False)
            on = run_cell(setup, args.weather, loss, args.behaviour, True)
            rows.append((loss, paired_difference(off, on)))
        print_table(f"{header}\nmean difference, investigation on minus off (±standard error)", rows)
    else:
        rows = [(loss, average_with_error(run_cell(setup, args.weather, loss, args.behaviour, args.investigate)))
                for loss in losses]
        print_table(f"{header} investigate={args.investigate}", rows)
    if args.csv:
        write_csv(args.csv, rows)


if __name__ == "__main__":
    main()
