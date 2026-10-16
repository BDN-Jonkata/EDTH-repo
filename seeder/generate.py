"""Generate a scenario and its ground truth from a config JSON and a seed.

    python seeder/generate.py scenarios/challenge.json
    python seeder/generate.py scenarios/hard.json --seed 7 --out out/hard-7
    python seeder/generate.py scenarios/medium.json --seed-set test --index 3
    python seeder/generate.py scenarios/challenge.json --save-db

Writes scenario.json (what the system may read) and truth.json (for scoring only; the tracker must never read it).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import scenario as sc


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config", help="scenario config JSON, for example scenarios/challenge.json")
    ap.add_argument("--seed", type=int, help="override the seed in the config")
    ap.add_argument("--seed-set", choices=sorted(sc.SEED_SETS), help="pick the seed from the tuning or test set")
    ap.add_argument("--index", type=int, default=0, help="0-based index within the seed set (default 0)")
    ap.add_argument("--out", help="output folder (default out/<scenario id>)")
    ap.add_argument("--truth-dt", type=float, default=0.1, help="ground-truth sample step in seconds")
    ap.add_argument("--save-db", action="store_true", help="also store the scenario and truth in PostgreSQL")
    args = ap.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if args.seed_set:
        config["seed_set"] = args.seed_set
        config["seed"] = sc.seed_for(args.seed_set, args.index)
    elif args.seed is not None:
        config["seed"] = args.seed
        config["seed_set"] = None
    try:
        scenario, truth = sc.generate(config, truth_dt=args.truth_dt)
    except ValueError as e:
        raise SystemExit(str(e))

    out = Path(args.out or Path("out") / scenario["id"])
    out.mkdir(parents=True, exist_ok=True)
    (out / "scenario.json").write_text(json.dumps(scenario, indent=1), encoding="utf-8")
    (out / "truth.json").write_text(json.dumps(truth, separators=(",", ":")), encoding="utf-8")
    crossings = [e for e in truth["events"] if e["type"] == "crossing"]
    print("%s: %d friendlies, %d ground sensors, %d hostiles, %d crossing(s)" % (
        scenario["id"], len(scenario["friendlies"]), len(scenario["ground"]), len(scenario["targets"]), len(crossings)))
    for e in crossings:
        print("  crossing %s x %s at t=%.1f s, %.1f m apart" % (e["a"], e["b"], e["t"], e["sep_m"]))
    print("wrote %s and %s" % (out / "scenario.json", out / "truth.json"))

    if args.save_db:
        import db
        with db.connect() as conn:
            db.apply_schema(conn)
            row_id = db.save_scenario(conn, scenario, truth)
        print("saved to PostgreSQL as scenario row %d" % row_id)


if __name__ == "__main__":
    main()
