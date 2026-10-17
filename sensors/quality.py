"""Sensor quality under weather: the sensor hierarchy and required standoff.

All sensor numbers come from the seeder catalog (`sim.range_m`,
`sim.min_range_m`, `weather_effects`); this module adds none of its own except
`IDENT_FRACTION`, which the catalog does not have. Active weather effects
multiply (fog at night = fog multiplier x night multiplier); that is an
assumption, like the catalog numbers themselves.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

from common.seeder_import import ensure_seeder_on_path
from sensors.weather import Conditions, WeatherProvider

ensure_seeder_on_path()
import catalog as seeder_catalog  # noqa: E402  (seeder/catalog.py)

DETECTION_KINDS = seeder_catalog.DETECTION_KINDS

# PLACEHOLDER, not in the catalog: the share of a module's detection range at
# which it can still identify an object (camera sees class cues, a microphone
# only hears presence). Propose `sim.ident_range_m` for the catalog and delete this.
IDENT_FRACTION = {
    "eo_camera": 0.6,
    "thermal_camera": 0.5,
    "rf_receiver": 0.3,
    "microphone": 0.2,
    "radar": 0.2,
}
MIN_USEFUL_RANGE_M = 20.0   # below this, identification is not worth attempting
STANDOFF_MARGIN = 0.7       # aim for this fraction of the maximum identification range


def load_modules() -> Dict[str, dict]:
    """Catalog sensor modules by id."""
    return {m["id"]: m for m in seeder_catalog.load_catalog()["modules"]}


def load_platforms() -> List[dict]:
    """Catalog platform models, each with `modules[]` = `{module_id, mount, count}`."""
    return seeder_catalog.load_catalog()["platforms"]


def detection_modules(modules: Iterable[dict]) -> List[dict]:
    return [m for m in modules if m["kind"] in DETECTION_KINDS]


def modules_in_scenario(scenario: dict, modules_by_id: Optional[Dict[str, dict]] = None) -> List[dict]:
    """The distinct detection modules carried by the scenario's friendly drones."""
    modules_by_id = modules_by_id or load_modules()
    ids = []
    for node in scenario["friendlies"]:
        for s in node["sensors"]:
            if s["module"] not in ids:
                ids.append(s["module"])
    return detection_modules(modules_by_id[i] for i in ids)


@dataclass(frozen=True)
class SensorQuality:
    range_scale: float   # multiplier on the module's range
    noise_scale: float   # multiplier on its measurement noise
    pd_scale: float      # multiplier on its detection probability


def _at_strength(multiplier: float, strength: float) -> float:
    """Move a catalog multiplier towards 1 (no effect) for a weaker anomaly."""
    return 1.0 + strength * (multiplier - 1.0)


def sensor_quality(module: dict, conditions: Conditions) -> SensorQuality:
    """Combined effect of every active anomaly. They multiply: independent effects, worst case
    for range (extinctions would add, which is milder), so a combination is never better than
    its worst member."""
    rng = noise = pd = 1.0
    for effect, strength in conditions.active_effects().items():
        e = module["weather_effects"][effect]
        rng *= _at_strength(e["range_mult"], strength)
        noise *= _at_strength(e["noise_mult"], strength)
        pd *= _at_strength(e["pd_mult"], strength)
    return SensorQuality(rng, noise, pd)


def modules_that_still_work(modules: Iterable[dict], conditions: Conditions) -> List[str]:
    """Detection modules that keep most of their range and detections, by the catalog's own test."""
    def works(m):
        q = sensor_quality(m, conditions)
        return q.range_scale >= seeder_catalog.ROBUST_RANGE and q.pd_scale >= seeder_catalog.ROBUST_PD
    return [m["id"] for m in detection_modules(modules) if works(m)]


def sensor_hierarchy(modules: Iterable[dict], conditions: Conditions) -> List[str]:
    """Detection module ids, best first: effective range weighted by detection probability."""
    def usefulness(m):
        q = sensor_quality(m, conditions)
        return m["sim"]["range_m"] * q.range_scale * q.pd_scale
    return [m["id"] for m in sorted(detection_modules(modules), key=usefulness, reverse=True)]


@dataclass(frozen=True)
class Standoff:
    max_range_m: float      # farthest distance at which this module can still identify an object
    recommended_m: float    # distance to aim for: margin inside the maximum, never inside the minimum range
    confidence: float       # 0..1, how much of its clear-weather capability weather leaves
    feasible: bool          # False if the module cannot identify the object right now


def required_standoff(
    module: dict, target_position: Sequence[float], t: float, weather: WeatherProvider
) -> Standoff:
    """How close a drone carrying `module` must get to identify the object."""
    sim = module["sim"]
    q = sensor_quality(module, weather.at(target_position, t))
    max_range = sim["range_m"] * IDENT_FRACTION[module["kind"]] * q.range_scale
    floor = sim["min_range_m"]
    return Standoff(
        max_range_m=max_range,
        recommended_m=min(max_range, max(STANDOFF_MARGIN * max_range, floor)),
        confidence=min(1.0, q.range_scale * q.pd_scale),
        feasible=max_range >= max(MIN_USEFUL_RANGE_M, floor),
    )


def standoff_by_module(
    modules: Iterable[dict], target_position: Sequence[float], t: float, weather: WeatherProvider
) -> Dict[str, Standoff]:
    return {m["id"]: required_standoff(m, target_position, t, weather) for m in detection_modules(modules)}


def best_standoff(by_module: Dict[str, Standoff]) -> Standoff:
    """The module that can identify from farthest away. Feasible ones win over infeasible."""
    return max(by_module.values(), key=lambda s: (s.feasible, s.max_range_m))
