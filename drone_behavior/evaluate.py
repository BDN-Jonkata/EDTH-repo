"""Reproducible comparison against the beacon-only baseline, using observed adapter tracks.

python -m drone_behavior.evaluate --preset medium --seeds 1 7 83 --birds 2 --vehicles 2
This is a simulation-policy evaluation, not a calibration or real-world accuracy claim.
"""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from common.seeder_import import ensure_seeder_on_path
from friend_foe.evaluate import evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", choices=["easy", "medium", "challenge", "hard", "busy"], default="medium")
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 7, 83])
    parser.add_argument("--birds", type=int, default=2)
    parser.add_argument("--vehicles", type=int, default=2)
    args = parser.parse_args()
    ensure_seeder_on_path()
    import scenario as seeder
    base = json.loads((Path(__file__).parents[1] / "scenarios" / (args.preset + ".json")).read_text())
    rows = []
    for seed in args.seeds:
        cfg = dict(base, seed=seed, seed_set=None)
        cfg.setdefault("environment", {}).setdefault("clutter", {}).update(birds=args.birds, vehicles=args.vehicles)
        sc, _ = seeder.generate(cfg, truth_dt=1)
        rows.append({"seed": seed, "baseline": asdict(evaluate(sc, seed=seed)),
                     "automatic": asdict(evaluate(sc, seed=seed, automatic=True))})
    print(json.dumps({"preset": args.preset, "results": rows}, indent=2))


if __name__ == "__main__":
    main()
