"""Validate the catalog and load it into PostgreSQL.

    python seeder/seed_catalog.py --check   # validate only, no database needed
    python seeder/seed_catalog.py           # create schema and load the catalog
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root, for sensors.report
import catalog as cat  # noqa: E402
from sensors.report import survival_rows  # noqa: E402


def print_resilience(catalog):
    print("\nModules that still work per weather (range >= %.0f%% and detections >= %.0f%%):" % (cat.ROBUST_RANGE * 100, cat.ROBUST_PD * 100))
    for pid, row in cat.resilience_table(catalog):
        print("  %-18s" % pid + "".join("  %s: %s" % (w, ",".join(row[w]) or "NONE") for w in cat.WEATHERS))


def print_combinations(catalog):
    """Information only, never an error: in a combined weather some platforms keep no working detection module."""
    rows = survival_rows({m["id"]: m for m in catalog["modules"]}, catalog["platforms"])
    print("\nWeather combinations (information only; sensors/report.py has the same table):")
    for name, working, dead in rows:
        print("  %-12s %-4s modules work   platforms with none: %s" % (name, working, dead))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="validate the catalog files only")
    args = ap.parse_args()

    catalog = cat.load_catalog()
    errors = cat.validate(catalog)
    print("%d modules, %d platforms" % (len(catalog["modules"]), len(catalog["platforms"])))
    print_resilience(catalog)
    print_combinations(catalog)
    if errors:
        print("\nCatalog errors:")
        for e in errors:
            print("  - " + e)
        sys.exit(1)
    print("\nCatalog OK")
    if args.check:
        return

    import db  # imported here so --check works without psycopg or a database

    with db.connect() as conn:
        db.apply_schema(conn)
        db.upsert_catalog(conn, catalog)
        n = conn.execute("SELECT count(*) FROM platform_loadouts").fetchone()[0]
    print("Loaded into PostgreSQL (%d platform loadouts)" % n)


if __name__ == "__main__":
    main()
