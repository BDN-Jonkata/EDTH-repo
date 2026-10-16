"""Share the database contents through git: export to a JSON file, import into any database.

    python seeder/dump.py export     # write seeder/data/db-dump.json.gz from your database
    python seeder/dump.py import     # create the schema, load the catalog, then the dump (safe to repeat)

The dump holds the catalog tables, the generated scenarios and the saved simulations.
Importing twice does not duplicate rows: tables are matched by id, scenarios by scenario_id,
simulations by (name, seed, created_at).
"""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

from psycopg.types.json import Jsonb

import catalog as cat
import db

DUMP = Path(__file__).parent / "data" / "db-dump.json.gz"


def export_dump(conn):
    def rows(sql):
        cur = conn.execute(sql)
        names = [c.name for c in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]

    out = {
        "format": "edth.db-dump/1",
        "scenarios": rows("SELECT scenario_id, name, preset, seed, config, scenario, truth, created_at FROM scenarios ORDER BY scenario_id"),
        "simulations": rows("SELECT name, seed, params, scenario, result, created_at FROM simulations ORDER BY created_at"),
    }
    DUMP.parent.mkdir(exist_ok=True)
    with gzip.open(DUMP, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(out, fh, default=lambda v: v.isoformat(), separators=(",", ":"))
    print("Wrote %s (%d scenarios, %d simulations, %.1f MB)" % (DUMP, len(out["scenarios"]), len(out["simulations"]), DUMP.stat().st_size / 1e6))


def import_dump(conn):
    with gzip.open(DUMP, "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    for s in data["scenarios"]:
        conn.execute(
            """INSERT INTO scenarios (scenario_id, name, preset, seed, config, scenario, truth, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (scenario_id) DO UPDATE SET name = EXCLUDED.name, preset = EXCLUDED.preset, seed = EXCLUDED.seed,
                 config = EXCLUDED.config, scenario = EXCLUDED.scenario, truth = EXCLUDED.truth""",
            (s["scenario_id"], s["name"], s["preset"], s["seed"], Jsonb(s["config"]), Jsonb(s["scenario"]), Jsonb(s["truth"]), s["created_at"]),
        )
    added = 0
    for s in data["simulations"]:
        exists = conn.execute(
            "SELECT 1 FROM simulations WHERE name = %s AND seed = %s AND created_at = %s", (s["name"], s["seed"], s["created_at"])
        ).fetchone()
        if exists:
            continue
        conn.execute(
            "INSERT INTO simulations (name, seed, params, scenario, result, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (s["name"], s["seed"], Jsonb(s["params"]), Jsonb(s["scenario"]), Jsonb(s["result"]), s["created_at"]),
        )
        added += 1
    print("Imported %d scenarios, %d new simulations" % (len(data["scenarios"]), added))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["export", "import"])
    args = ap.parse_args()
    with db.connect() as conn:
        db.apply_schema(conn)
        if args.action == "export":
            export_dump(conn)
        else:
            db.upsert_catalog(conn, cat.load_catalog())  # the catalog comes from seeder/catalog/*.json
            import_dump(conn)


if __name__ == "__main__":
    main()
