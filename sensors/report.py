"""Which sensors and platforms survive which weather, alone and combined.

    python -m sensors.report

The catalog check (`seed_catalog.py --check`) only tests single weathers. This adds the
combinations in `PRESETS`: a platform "survives" when at least one of its detection
modules keeps most of its range and detections (the catalog's own test).
"""

from typing import Dict, List

from sensors.quality import detection_modules, load_modules, load_platforms, modules_that_still_work, required_standoff
from sensors.weather import PRESETS, UniformWeather

ORIGIN = (0.0, 0.0, 0.0)


def platform_modules(platform: dict, modules_by_id: Dict[str, dict]) -> List[dict]:
    return [modules_by_id[link["module_id"]] for link in platform["modules"]]


def best_standoff_m(modules: List[dict], name: str) -> str:
    """Longest identification distance among the platform's modules; '!' if even that is infeasible."""
    weather = UniformWeather(PRESETS[name])
    best = max((required_standoff(m, ORIGIN, 0.0, weather) for m in detection_modules(modules)),
               key=lambda s: s.max_range_m, default=None)
    return "-" if best is None else f"{best.max_range_m:.0f}" + ("" if best.feasible else "!")


def survival_rows(modules_by_id: Dict[str, dict], platforms: List[dict]) -> List[List[str]]:
    rows = []
    for name, conditions in PRESETS.items():
        working = modules_that_still_work(modules_by_id.values(), conditions)
        dead = [p["id"] for p in platforms
                if not modules_that_still_work(platform_modules(p, modules_by_id), conditions)]
        rows.append([name, f"{len(working)}/{len(detection_modules(modules_by_id.values()))}", ", ".join(dead) or "-"])
    return rows


def standoff_rows(modules_by_id: Dict[str, dict], platforms: List[dict]) -> List[List[str]]:
    return [[name] + [best_standoff_m(platform_modules(p, modules_by_id), name) for p in platforms] for name in PRESETS]


def show(title: str, header: List[str], rows: List[List[str]]) -> None:
    print(f"\n{title}")
    print(" | ".join(header))
    for row in rows:
        print(" | ".join(row))


def main() -> None:
    modules_by_id, platforms = load_modules(), load_platforms()
    show("Detection modules still working, and platforms left with none",
         ["weather", "modules working", "platforms with no working module"], survival_rows(modules_by_id, platforms))
    show("Best identification distance in metres per platform (! = cannot identify at all)",
         ["weather"] + [p["id"] for p in platforms], standoff_rows(modules_by_id, platforms))
    print("\nAll numbers come from the catalog's assumed weather effects (verified: false).")


if __name__ == "__main__":
    main()
