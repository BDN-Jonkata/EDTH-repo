"""Sweep the estimator over beacon loss and weather on generated scenarios.

    python -m friend_foe.sweep                              # tuning seeds, preset medium
    python -m friend_foe.sweep --set test --seeds 20        # report on the test seeds
    python -m friend_foe.sweep --cfg no_beacon_per_s=0.1    # try an estimator setting
    python -m friend_foe.sweep --birds 2 --vehicles 2       # add clutter objects
    python -m friend_foe.sweep --preset hard --csv out/sweep.csv

Tune on the tuning seeds only; report on the test seeds (the seeder's rule).
Loss and burst replace the preset's network loss; its clock and pose errors stay.
There is no behaviour module yet, so no track is ever called hostile or peaceful here.
"""

import argparse
import copy
import csv
import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Dict, List, Optional

from common.seeder_import import ensure_seeder_on_path
from friend_foe.estimator import EstimatorConfig
from friend_foe.evaluate import RunMetrics, evaluate

ensure_seeder_on_path()
import scenario as seeder_scenario  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LOSSES = (0.0, 0.1, 0.3, 0.5, 0.7, 0.9)
WEATHERS = ("clear", "fog", "rain", "wind", "fog+wind", "rain+wind", "fog+rain+wind")   # the seeder knows only the first four
COLUMNS = ("friendly_flag_frac", "friendlies_flagged", "hostile_as_friendly_frac", "hostile_as_peaceful_frac",
           "time_to_friendly_s", "friendlies_never_confirmed", "time_to_flag_s", "hostiles_never_flagged",
           "clutter_flagged_frac", "requests_on_friendlies", "requests_on_clutter", "infeasible_requests",
           "mean_standoff_m")


@dataclass
class Setup:
    preset: dict
    seed_set: str = "tuning"
    seeds: int = 5
    config: EstimatorConfig = None
    birds: int = 0
    vehicles: int = 0


def load_preset(name: str) -> dict:
    return json.loads((ROOT / "scenarios" / f"{name}.json").read_text(encoding="utf-8"))


def make_scenario(setup: Setup, index: int, weather: str, loss: float, burst: bool) -> dict:
    return make_scenario_and_truth(setup, index, weather, loss, burst)[0]


def make_scenario_and_truth(setup: Setup, index: int, weather: str, loss: float, burst: bool):
    """The scenario and its `truth.json`; only the scoring module may read the second."""
    config = copy.deepcopy(setup.preset)
    config["seed_set"], config["seed"] = setup.seed_set, seeder_scenario.seed_for(setup.seed_set, index)
    env = config.setdefault("environment", {})
    env["weather"] = "clear"   # the seeder accepts one weather; combinations are set below
    if setup.birds or setup.vehicles:
        env["clutter"] = {**env.get("clutter", {}), "birds": setup.birds, "vehicles": setup.vehicles}
    net = config.setdefault("degradations", {}).setdefault("network", {})
    net.update({"enabled": True, "loss": loss, "burst": burst})
    scenario, truth = seeder_scenario.generate(config)
    scenario["environment"]["weather"] = weather
    return scenario, truth


def average(runs: List[RunMetrics]) -> Dict[str, Optional[float]]:
    out = {}
    for col in COLUMNS:
        values = [getattr(r, col) for r in runs if getattr(r, col) is not None]
        out[col] = sum(values) / len(values) if values else None
    return out


def run_cell(setup: Setup, weather: str, loss: float, burst: bool) -> Dict[str, Optional[float]]:
    runs = []
    for i in range(setup.seeds):
        scenario = make_scenario(setup, i, weather, loss, burst)
        runs.append(evaluate(scenario, setup.config, seed=scenario["seed"]))
    return average(runs)


def parse_cfg(text: Optional[str]) -> EstimatorConfig:
    config = EstimatorConfig()
    types = {f.name: f.type for f in fields(EstimatorConfig)}
    for item in filter(None, (text or "").split(",")):
        key, value = item.split("=")
        setattr(config, key, types[key](value))
    return config


def fmt(v: Optional[float]) -> str:
    return "-" if v is None else f"{v:.2f}"


def print_table(title: str, key_names, rows) -> None:
    print(f"\n{title}")
    print(" | ".join(list(key_names) + [c.replace("_", " ") for c in COLUMNS]))
    for keys, cell in rows:
        print(" | ".join([str(k) for k in keys] + [fmt(cell[c]) for c in COLUMNS]))


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", default="medium")
    ap.add_argument("--set", dest="seed_set", default="tuning", choices=sorted(seeder_scenario.SEED_SETS))
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--cfg", help="estimator settings, for example no_beacon_per_s=0.1,match_step=1.5")
    ap.add_argument("--birds", type=int, default=0, help="bird clutter objects per scenario (0 to 10)")
    ap.add_argument("--vehicles", type=int, default=0, help="vehicle clutter objects per scenario (0 to 10)")
    ap.add_argument("--csv", help="write all rows to this file")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    setup = Setup(load_preset(args.preset), args.seed_set, args.seeds, parse_cfg(args.cfg), args.birds, args.vehicles)
    loss_rows = [((loss, burst), run_cell(setup, "clear", loss, burst)) for burst in (False, True) for loss in LOSSES]
    weather_rows = [((w,), run_cell(setup, w, 0.15, False)) for w in WEATHERS]
    print(f"preset={args.preset} seed set={args.seed_set} seeds={args.seeds} config={args.cfg or 'default'} "
          f"birds={args.birds} vehicles={args.vehicles}")
    print_table("By beacon loss (clear weather)", ("loss", "burst"), loss_rows)
    print_table("By weather (loss 0.15)", ("weather",), weather_rows)
    if args.csv:
        write_csv(args.csv, loss_rows, weather_rows)


def write_csv(path: str, loss_rows, weather_rows) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["table", "key1", "key2", *COLUMNS])
        for keys, cell in loss_rows:
            w.writerow(["loss", keys[0], keys[1], *[cell[c] for c in COLUMNS]])
        for keys, cell in weather_rows:
            w.writerow(["weather", keys[0], "", *[cell[c] for c in COLUMNS]])


if __name__ == "__main__":
    main()
