"""Sweep the estimator over beacon loss and weather on generated scenarios.

    python -m friend_foe.sweep                              # tuning seeds, preset medium
    python -m friend_foe.sweep --set test --seeds 20        # report on the test seeds
    python -m friend_foe.sweep --cfg no_beacon_step=0.05    # try an estimator setting
    python -m friend_foe.sweep --preset hard --csv out/sweep.csv

Tune on the tuning seeds only; report on the test seeds (the seeder's rule).
Loss and burst replace the preset's network loss; its clock and pose errors stay.
"""

import argparse
import copy
import csv
import json
from dataclasses import asdict, fields
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
COLUMNS = ("friendly_flag_frac", "friendlies_flagged", "hostile_as_friendly_frac", "time_to_friendly_s",
           "friendlies_never_confirmed", "time_to_flag_s", "hostiles_never_flagged", "requests_on_friendlies",
           "infeasible_requests", "mean_standoff_m")


def load_preset(name: str) -> dict:
    return json.loads((ROOT / "scenarios" / f"{name}.json").read_text(encoding="utf-8"))


def make_scenario(preset: dict, seed_set: str, index: int, weather: str, loss: float, burst: bool) -> dict:
    config = copy.deepcopy(preset)
    config["seed_set"], config["seed"] = seed_set, seeder_scenario.seed_for(seed_set, index)
    config.setdefault("environment", {})["weather"] = "clear"   # the seeder accepts one weather; combinations are set below
    net = config.setdefault("degradations", {}).setdefault("network", {})
    net.update({"enabled": True, "loss": loss, "burst": burst})
    scenario, _truth = seeder_scenario.generate(config)
    scenario["environment"]["weather"] = weather
    return scenario


def average(runs: List[RunMetrics]) -> Dict[str, Optional[float]]:
    out = {}
    for col in COLUMNS:
        values = [getattr(r, col) for r in runs if getattr(r, col) is not None]
        out[col] = sum(values) / len(values) if values else None
    return out


def run_cell(preset, seed_set, seeds, weather, loss, burst, config) -> Dict[str, Optional[float]]:
    runs = []
    for i in range(seeds):
        scenario = make_scenario(preset, seed_set, i, weather, loss, burst)
        runs.append(evaluate(scenario, config, seed=scenario["seed"]))
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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", default="medium")
    ap.add_argument("--set", dest="seed_set", default="tuning", choices=sorted(seeder_scenario.SEED_SETS))
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--cfg", help="estimator settings, for example no_beacon_step=0.05,match_step=1.5")
    ap.add_argument("--csv", help="write all rows to this file")
    args = ap.parse_args()
    preset, config = load_preset(args.preset), parse_cfg(args.cfg)

    loss_rows = [((loss, burst), run_cell(preset, args.seed_set, args.seeds, "clear", loss, burst, config))
                 for burst in (False, True) for loss in LOSSES]
    weather_rows = [((w,), run_cell(preset, args.seed_set, args.seeds, w, 0.15, False, config)) for w in WEATHERS]
    print(f"preset={args.preset} seed set={args.seed_set} seeds={args.seeds} config={args.cfg or 'default'}")
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
