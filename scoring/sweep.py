"""Score the friend/foe estimator over beacon loss with the scoring module's metrics.

    python -m scoring.sweep --set test --seeds 20
    python -m scoring.sweep --birds 2 --vehicles 2 --csv out/scoring_sweep.csv

The tracks come from the friend/foe test adapter (clean, ids known), so position error and ID swaps
say little; count error, OSPA and the false alarms show what the classification does to the operator's
picture. Tune on the tuning seeds only; report on the test seeds. Without a behaviour module nothing is
called hostile or peaceful, so every non-friendly track counts as hostile (clutter included).
"""

import argparse
import csv
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from friend_foe.estimator import FriendFoeEstimator, for_scenario
from friend_foe.scenario_adapter import frames_from_scenario
from friend_foe.sweep import LOSSES, Setup, load_preset, make_scenario_and_truth, seeder_scenario
from scoring.metrics import RunScore, ScoreConfig, score
from scoring.tracks import frames_from_estimator

COLUMNS = ("count_error_mean_abs", "count_error_bias", "ospa_m", "pos_rmse_m", "id_swaps", "hostile_detected_frac",
           "friendlies_flagged", "friendly_flag_frac", "clutter_flagged_frac", "false_tracks_mean", "ident_covered_frac",
           "ident_delay_s")
WARMUP_S = 10.0


def run_once(setup: Setup, index: int, loss: float) -> RunScore:
    scenario, truth = make_scenario_and_truth(setup, index, "clear", loss, False)
    estimator = FriendFoeEstimator(for_scenario(scenario, setup.config))
    frames = frames_from_estimator(frames_from_scenario(scenario, seed=scenario["seed"]), estimator.update)
    return score(truth, frames, ScoreConfig(warmup_s=WARMUP_S))


def average(runs: List[RunScore]) -> Dict[str, Optional[float]]:
    out = {}
    for col in COLUMNS:
        values = [getattr(r, col) for r in runs if getattr(r, col) is not None]
        out[col] = sum(values) / len(values) if values else None
    return out


def stats_of(values: List[float]) -> Tuple[Optional[float], Optional[float]]:
    """(mean, standard error of the mean); the error is None for fewer than 2 values."""
    n = len(values)
    if not n:
        return None, None
    mean = sum(values) / n
    if n < 2:
        return mean, None
    return mean, math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1) / n)


def average_with_error(runs: List[RunScore]) -> Dict[str, Tuple[Optional[float], Optional[float]]]:
    """Each column's mean and standard error over the runs (seeds)."""
    return {col: stats_of([getattr(r, col) for r in runs if getattr(r, col) is not None]) for col in COLUMNS}


def paired_difference(a: List[RunScore], b: List[RunScore]) -> Dict[str, Tuple[Optional[float], Optional[float]]]:
    """Mean and standard error of (b - a) per column over the same seeds. Runs on the same seeds share their
    scenarios, so this is much tighter than comparing two separate means; a difference smaller than about
    two standard errors is not distinguishable from seed noise."""
    out = {}
    for col in COLUMNS:
        pairs = [(getattr(x, col), getattr(y, col)) for x, y in zip(a, b)
                 if getattr(x, col) is not None and getattr(y, col) is not None]
        out[col] = stats_of([y - x for x, y in pairs])
    return out


def fmt_error(pair: Tuple[Optional[float], Optional[float]]) -> str:
    mean, error = pair
    if mean is None:
        return "-"
    return f"{mean:.2f}" if error is None else f"{mean:.2f}±{error:.2f}"


def fmt(v: Optional[float]) -> str:
    return "-" if v is None else f"{v:.2f}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", default="medium")
    ap.add_argument("--set", dest="seed_set", default="tuning", choices=sorted(seeder_scenario.SEED_SETS))
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--birds", type=int, default=0)
    ap.add_argument("--vehicles", type=int, default=0)
    ap.add_argument("--csv", help="write the rows to this file")
    args = ap.parse_args()
    setup = Setup(load_preset(args.preset), args.seed_set, args.seeds, None, args.birds, args.vehicles)
    rows = [(loss, average([run_once(setup, i, loss) for i in range(setup.seeds)])) for loss in LOSSES]
    print(f"preset={args.preset} seed set={args.seed_set} seeds={args.seeds} birds={args.birds} vehicles={args.vehicles}")
    print(" | ".join(["loss"] + [c.replace("_", " ") for c in COLUMNS]))
    for loss, cell in rows:
        print(" | ".join([str(loss)] + [fmt(cell[c]) for c in COLUMNS]))
    if args.csv:
        Path(args.csv).parent.mkdir(parents=True, exist_ok=True)
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["loss", *COLUMNS])
            w.writerows([loss, *[cell[c] for c in COLUMNS]] for loss, cell in rows)


if __name__ == "__main__":
    main()
