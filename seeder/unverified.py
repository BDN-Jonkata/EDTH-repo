"""Worksheet for catalog verification (plan task 8): every unverified module and platform with the numbers to check.

    python seeder/unverified.py                      # print the worksheet (Markdown)
    python seeder/unverified.py --out worksheet.md

For each number, fill in the datasheet value and its source; then set `verified: true` and `source` on the
module or platform in seeder/catalog/ and run `python seeder/seed_catalog.py --check`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog as cat  # noqa: E402

SIM_ROWS = ("range_m", "ident_range_m", "min_range_m", "fov_deg", "pd", "pd_far", "rate_hz", "latency_ms")
EFFECT_ROWS = ("range_mult", "noise_mult", "pd_mult")


def number_rows(module):
    rows = [("sim." + k, module["sim"][k]) for k in SIM_ROWS if k in module["sim"]]
    rows += [("noise." + k, v) for k, v in module["sim"].get("noise", {}).items()]
    for weather, effect in module.get("weather_effects", {}).items():
        rows += [("%s.%s" % (weather, k), effect[k]) for k in EFFECT_ROWS if k in effect]
    return rows


def table(rows):
    lines = ["| Number | Assumed | Datasheet value | Source |", "|--------|---------|-----------------|--------|"]
    return lines + ["| %s | %s |  |  |" % (name, value) for name, value in rows]


def module_section(module):
    head = ["### %s (%s)" % (module["id"], module["kind"]), module["name"], "",
            "Current source: %s" % module.get("source", "none"), ""]
    return head + table(number_rows(module)) + [""]


def platform_section(platform):
    flight = platform["spec"].get("flight", {})
    rows = [("mass_g", platform["spec"].get("mass_g", "-"))] + [("flight." + k, v) for k, v in flight.items() if k != "assumed"]
    head = ["### %s" % platform["id"], platform["name"], "",
            "Current source: %s" % platform.get("source", "none"),
            "Flight limits assumed: %s" % flight.get("assumed", "-"), ""]
    return head + table(rows) + [""]


def worksheet(catalog):
    modules = [m for m in catalog["modules"] if not m.get("verified")]
    platforms = [p for p in catalog["platforms"] if not p.get("verified")]
    lines = ["# Catalog verification worksheet", "",
             "%d of %d modules and %d of %d platforms are unverified." % (
                 len(modules), len(catalog["modules"]), len(platforms), len(catalog["platforms"])), "", "## Modules", ""]
    for m in modules:
        lines += module_section(m)
    lines += ["## Platforms", ""]
    for p in platforms:
        lines += platform_section(p)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="write the worksheet to this file instead of printing it")
    args = ap.parse_args()
    text = worksheet(cat.load_catalog())
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print("wrote %s" % args.out)
    else:
        print(text)


if __name__ == "__main__":
    main()
