"""A sensor observation turned into what the tracker filters on: scalar readings plus where the sensor was.

The observation message carries only native fields (a camera gives a bearing and an elevation, never a
range); where the sensor was comes separately, from the pose book. Bearings are converted from compass
degrees to maths radians (0 = east, counter-clockwise) here and nowhere else.
"""

import math
from dataclasses import dataclass
from typing import Optional

from sensors.native import math_rad

BEARING, RANGE, RANGE_BEARING = "bearing", "range", "range_bearing"


@dataclass(frozen=True)
class Pose2D:
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0


@dataclass(frozen=True)
class Measurement:
    kind: str                    # bearing | range | range_bearing
    t: float
    node: str
    sensor_id: str
    pose: Pose2D
    max_range_m: float
    bearing: Optional[float] = None       # radians, maths convention
    sigma_bearing: float = 0.0
    range_m: Optional[float] = None
    sigma_range: float = 0.0
    radial_mps: Optional[float] = None
    sigma_radial: float = 0.0

    @property
    def scan(self) -> tuple:
        """Detections from one scan of one sensor share this key and cannot all be the same object."""
        return (self.node, self.sensor_id, self.t)


def _sigma(obs: dict, field: str) -> float:
    return math.sqrt(obs["covariance"][obs["cov_fields"].index(field)][obs["cov_fields"].index(field)])


def _range_from_level(obs: dict, source_level_db: float):
    """A single microphone only hears how loud: with the module's source level that is a (poor) range."""
    level = obs["value"]["level_db"]
    range_m = 10.0 ** ((source_level_db - level) / 20.0)
    return range_m, range_m * math.log(10.0) / 20.0 * _sigma(obs, "level_db")


def from_observation(obs: dict, pose: Pose2D, module: dict) -> Optional[Measurement]:
    """The measurement an observation message gives, or None for a kind the tracker cannot use."""
    value, kind = obs["value"], obs["kind"]
    base = dict(t=obs["t_obs"], node=obs["header"]["source_id"], sensor_id=obs["sensor_id"], pose=pose,
                max_range_m=module["sim"]["range_m"])
    if kind == "bearing":
        return Measurement(BEARING, bearing=math_rad(value["bearing_deg"]),
                           sigma_bearing=math.radians(_sigma(obs, "bearing_deg")), **base)
    if kind == "range_bearing":
        return Measurement(RANGE_BEARING, bearing=math_rad(value["azimuth_deg"]),
                           sigma_bearing=math.radians(_sigma(obs, "azimuth_deg")), range_m=value["range_m"],
                           sigma_range=_sigma(obs, "range_m"), radial_mps=value["radial_mps"],
                           sigma_radial=_sigma(obs, "radial_mps"), **base)
    if kind == "detection" and "source_level_db" in module["sim"]["noise"]:
        range_m, sigma = _range_from_level(obs, module["sim"]["noise"]["source_level_db"])
        return Measurement(RANGE, range_m=range_m, sigma_range=sigma, **base)
    return None
