"""Save an exported simulation run (plain JSON) into PostgreSQL.

    node ui/viewer/export-run.js --seed 4127 > run.json
    python seeder/save_simulation.py run.json --name "Crossing pair"
"""
from __future__ import annotations

import argparse
import json

import db


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help="JSON file with keys params, scenario, result")
    ap.add_argument("--name", default=None, help="name for the saved run (default: file name)")
    args = ap.parse_args()

    with open(args.file, encoding="utf-8") as fh:
        run = json.load(fh)
    params = run["params"]
    name = args.name or args.file
    with db.connect() as conn:
        db.apply_schema(conn)
        sim_id = db.save_simulation(conn, name, params["seed"], params, run["scenario"], run["result"])
    print("Saved simulation %d (%s, seed %d)" % (sim_id, name, params["seed"]))


if __name__ == "__main__":
    main()
