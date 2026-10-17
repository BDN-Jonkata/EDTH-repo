"""What each sensor type reports for one detection: its native fields with noise, and the honest noise of each.

Mirrors the mock simulation in ui/viewer/sim.js (`makeRecord`), including its simplifications: signal
levels use a fixed source level, a camera's class hint is right with a probability that falls with
distance, noise is independent per field. Angles are compass degrees (0 = north, clockwise), as in
docs/data-formats.md.
"""

import math
import random
from dataclasses import dataclass
from typing import Callable, Dict, Tuple

OBSERVATION_KIND = {"bearing_elevation": "bearing", "bearing_level": "bearing", "bearing_rssi": "bearing",
                    "level": "detection", "range_azimuth_doppler": "range_bearing"}
RF_CENTER_MHZ = {"friendly": 5745, "other": 2437}   # a friendly link and a hostile's control link


def compass_deg(math_rad: float) -> float:
    """Maths angle (0 = east, counter-clockwise) to compass degrees."""
    return (90.0 - math.degrees(math_rad)) % 360.0


def math_rad(compass: float) -> float:
    return math.radians(90.0 - compass)


@dataclass(frozen=True)
class Detection:
    """The truth about one object as seen from the sensor: what the sensor model needs to draw a reading."""
    az: float            # maths angle from sensor to object, radians
    range_m: float
    vx: float
    vy: float
    altitude_m: float
    friendly: bool


@dataclass(frozen=True)
class Viewpoint:
    sensor_vx: float
    sensor_vy: float
    sensor_altitude_m: float
    max_range_m: float   # the module's range under the current weather
    noise_scale: float   # weather multiplier on every noise term


Reading = Tuple[dict, Dict[str, float]]   # value, 1-sigma noise per field
Builder = Callable[[dict, Detection, Viewpoint, random.Random], Reading]


def _log_range_db(range_m: float) -> float:
    return 20.0 * math.log10(max(range_m, 1.0))


def _bearing(noise: dict, det: Detection, view: Viewpoint, rng: random.Random) -> Tuple[float, float]:
    sigma = noise["bearing_deg"] * view.noise_scale
    return compass_deg(det.az + math.radians(rng.gauss(0.0, sigma))), sigma


def _bearing_elevation(noise, det, view, rng) -> Reading:
    bearing, sig_b = _bearing(noise, det, view, rng)
    sig_e = noise["elevation_deg"] * view.noise_scale
    elevation = math.degrees(math.atan2(det.altitude_m - view.sensor_altitude_m, det.range_m)) + rng.gauss(0.0, sig_e)
    value = {"bearing_deg": bearing, "elevation_deg": elevation}
    return value, {"bearing_deg": sig_b, "elevation_deg": sig_e}


def class_hint(det: Detection, max_range_m: float, rng: random.Random) -> str:
    """A camera's guess whether the object is a friendly: right less often at long range."""
    p_right = max(0.5, 0.95 - 0.45 * det.range_m / max_range_m)
    truth, other = ("friendly", "unknown") if det.friendly else ("unknown", "friendly")
    return truth if rng.random() < p_right else other


def _eo(noise, det, view, rng) -> Reading:
    value, sd = _bearing_elevation(noise, det, view, rng)
    value["class_hint"] = class_hint(det, view.max_range_m, rng)
    return value, sd


def _thermal(noise, det, view, rng) -> Reading:
    value, sd = _bearing_elevation(noise, det, view, rng)
    value["intensity"] = max(0.0, 1.0 - 0.5 * det.range_m / view.max_range_m + rng.gauss(0.0, 0.05))
    return value, sd


def _bearing_level(noise, det, view, rng) -> Reading:
    bearing, sig_b = _bearing(noise, det, view, rng)
    sig_l = noise["level_db"] * view.noise_scale
    level = 90.0 - _log_range_db(det.range_m) + rng.gauss(0.0, sig_l)
    return {"bearing_deg": bearing, "level_db": level, "presence": True}, {"bearing_deg": sig_b, "level_db": sig_l}


def _level(noise, det, view, rng) -> Reading:
    sig_l = noise["level_db"] * view.noise_scale
    level = noise["source_level_db"] - _log_range_db(det.range_m) + rng.gauss(0.0, sig_l)
    return {"level_db": level, "presence": True}, {"level_db": sig_l}


def _bearing_rssi(noise, det, view, rng) -> Reading:
    bearing, sig_b = _bearing(noise, det, view, rng)
    sig_r = noise["rssi_db"] * view.noise_scale
    value = {"bearing_deg": bearing, "rssi_dbm": -40.0 - _log_range_db(det.range_m) + rng.gauss(0.0, sig_r),
             "center_freq_mhz": RF_CENTER_MHZ["friendly" if det.friendly else "other"]}
    return value, {"bearing_deg": sig_b, "rssi_dbm": sig_r}


def _range_azimuth_doppler(noise, det, view, rng) -> Reading:
    sig_r, sig_a = noise["range_m"] * view.noise_scale, noise["azimuth_deg"] * view.noise_scale
    sig_v = noise["radial_mps"] * view.noise_scale
    radial = (det.vx - view.sensor_vx) * math.cos(det.az) + (det.vy - view.sensor_vy) * math.sin(det.az)
    value = {"range_m": det.range_m + rng.gauss(0.0, sig_r),
             "azimuth_deg": compass_deg(det.az + math.radians(rng.gauss(0.0, sig_a))),
             "radial_mps": radial + rng.gauss(0.0, sig_v),
             "snr_db": 20.0 - 20.0 * math.log10(max(det.range_m, 1.0) / 100.0) + rng.gauss(0.0, 1.0)}
    return value, {"range_m": sig_r, "azimuth_deg": sig_a, "radial_mps": sig_v}


BUILDERS: Dict[str, Builder] = {
    "bearing_elevation": _bearing_elevation, "bearing_level": _bearing_level, "level": _level,
    "bearing_rssi": _bearing_rssi, "range_azimuth_doppler": _range_azimuth_doppler,
}
BUILDERS_BY_KIND: Dict[str, Builder] = {"eo_camera": _eo, "thermal_camera": _thermal}


def read(module: dict, det: Detection, view: Viewpoint, rng: random.Random) -> Reading:
    """The native fields and their noise for one detection by this module."""
    native = module["native"]["type"]
    build = BUILDERS_BY_KIND.get(module["kind"]) or BUILDERS[native]
    return build(module["sim"]["noise"], det, view, rng)
