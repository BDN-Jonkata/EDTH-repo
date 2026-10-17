"""Generate a scenario and its ground truth from a config JSON and a seed.

    python seeder/generate.py scenarios/challenge.json
    python seeder/generate.py scenarios/hard.json --seed 7 --out out/hard-7
    python seeder/generate.py scenarios/medium.json --seed-set test --index 3
    python seeder/generate.py scenarios/challenge.json --save-db
    python seeder/generate.py scenarios/hard.json --sweep tuning    (every seed of a set, see sweep.py)

Writes scenario.json (what the system may read) and truth.json (for scoring only; the tracker must never read it).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import scenario as sc
import sweep as sw


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config", help="scenario config JSON, for example scenarios/challenge.json")
    ap.add_argument("--seed", type=int, help="override the seed in the config")
    ap.add_argument("--seed-set", choices=sorted(sc.SEED_SETS), help="pick the seed from the tuning or test set")
    ap.add_argument("--sweep", choices=sorted(sc.SEED_SETS), help="generate every seed of the tuning or test set into <out>/<seed>/")
    ap.add_argument("--count", type=int, help="with --sweep: only the first N seeds (for a quick check)")
    ap.add_argument("--index", type=int, default=0, help="0-based index within the seed set (default 0)")
    ap.add_argument("--out", help="output folder (default out/<scenario id>)")
    ap.add_argument("--truth-dt", type=float, default=0.1, help="ground-truth sample step in seconds")
    ap.add_argument("--save-db", action="store_true", help="also store the scenario and truth in PostgreSQL")
    args = ap.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if args.sweep:
        return run_sweep(args, config)
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
    sw.write_run(out, scenario, truth)
    print_summary(scenario, truth, out)
    if args.save_db:
        save_to_db(scenario, truth)


def print_summary(scenario, truth, out):
    crossings = [e for e in truth["events"] if e["type"] == "crossing"]
    print("%s: %d friendlies, %d ground sensors, %d hostiles, %d crossing(s)" % (
        scenario["id"], len(scenario["friendlies"]), len(scenario["ground"]), len(scenario["targets"]), len(crossings)))
    for e in crossings:
        print("  crossing %s x %s at t=%.1f s, %.1f m apart" % (e["a"], e["b"], e["t"], e["sep_m"]))
    print("wrote %s and %s" % (out / "scenario.json", out / "truth.json"))


def save_to_db(scenario, truth):
    import db
    with db.connect() as conn:
        db.apply_schema(conn)
        row_id = db.save_scenario(conn, scenario, truth)
    print("saved to PostgreSQL as scenario row %d" % row_id)


def run_sweep(args, config):
    if args.seed is not None or args.seed_set or args.save_db:
        raise SystemExit("--sweep picks the seeds itself: do not combine it with --seed, --seed-set or --save-db")
    out = Path(args.out or Path("out") / ("%s-sweep-%s" % (Path(args.config).stem, args.sweep)))
    try:
        index = sw.sweep(config, args.sweep, out, args.truth_dt, args.count,
                         lambda i, n: print("\r%d/%d seeds" % (i, n), end="", flush=True))
    except ValueError as e:
        raise SystemExit(str(e))
    print("\nwrote %d runs and %s" % (len(index["runs"]), out / "index.json"))
    if args.sweep == "test":
        print("This is the final test set: run it once, at the end. Never tune on it.")


if __name__ == "__main__":
    main()
