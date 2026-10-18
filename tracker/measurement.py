"""A sensor observation turned into what the tracker filters on: scalar readings plus where the sensor was.

The observation message carries only native fields (a camera gives a bearing and an elevation, never a
range); where the sensor was comes separately, from the pose book. Bearings are converted from compass
degrees to maths radians (0 = east, counter-clockwise) here and nowhere else.
"""

import math
from dataclasses import dataclass
from typing import Optional

from sensors.native import in_friend_band, math_rad

BEARING, RANGE, RANGE_BEARING = "bearing", "range", "range_bearing"


@dataclass(frozen=True)
class Pose2D:
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    sigma: float = 0.0       # 1-sigma position uncertainty of the sensor's own position, metres


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
    sensor_kind: str = ""                  # the module's kind (eo_camera, rf_receiver, ...): what sort of evidence a reading is
    freq_mhz: Optional[float] = None       # an RF receiver's centre frequency: which link the transmitter uses

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


def _with_pose_error(sigma_angle: float, pose: Pose2D, max_range_m: float) -> float:
    """The sensor's own position error moves a bearing by about sigma / range; the range is not known to a
    bearing-only reading, so half the sensor's reach stands in for it."""
    return math.hypot(sigma_angle, pose.sigma / (0.5 * max_range_m)) if pose.sigma > 0 else sigma_angle


@dataclass(frozen=True)
class RssiRange:
    """How to turn an RF reading's signal strength into a range: `rssi = reference_dbm - 20 log10(range)`.
    ASSUMED: nobody knows a hostile's transmit power, so the reference carries `reference_sigma_db` of its own
    uncertainty on top of the receiver's noise."""
    reference_dbm: float
    reference_sigma_db: float = 6.0


def _range_from_rssi(obs: dict, rssi: RssiRange):
    """(range, sigma) from the signal strength of an RF reading; log-normal error, so sigma grows with the range."""
    range_m = 10.0 ** ((rssi.reference_dbm - obs["value"]["rssi_dbm"]) / 20.0)
    sigma_db = math.hypot(_sigma(obs, "rssi_dbm"), rssi.reference_sigma_db)
    return range_m, range_m * math.log(10.0) / 20.0 * sigma_db


def from_observation(obs: dict, pose: Pose2D, module: dict, rssi: Optional[RssiRange] = None) -> Optional[Measurement]:
    """The measurement an observation message gives, or None for a kind the tracker cannot use. The noise
    includes the uncertainty of where the sensor was (`pose.sigma`). With `rssi`, an RF reading on a hostile's
    link (not the friendlies' band, whose drones are tracked by beacons) also carries a range."""
    value, kind = obs["value"], obs["kind"]
    reach = module["sim"]["range_m"]
    base = dict(t=obs["t_obs"], node=obs["header"]["source_id"], sensor_id=obs["sensor_id"], pose=pose, max_range_m=reach,
                sensor_kind=module.get("kind", ""))
    if kind == "bearing":
        sigma = _with_pose_error(math.radians(_sigma(obs, "bearing_deg")), pose, reach)
        ranged = {}
        if rssi is not None and "rssi_dbm" in value and not in_friend_band(value.get("center_freq_mhz", 0.0)):
            ranged["range_m"], ranged["sigma_range"] = _range_from_rssi(obs, rssi)
        return Measurement(BEARING, bearing=math_rad(value["bearing_deg"]), sigma_bearing=sigma,
                           freq_mhz=value.get("center_freq_mhz"), **ranged, **base)
    if kind == "range_bearing":
        sigma = _with_pose_error(math.radians(_sigma(obs, "azimuth_deg")), pose, reach)
        return Measurement(RANGE_BEARING, bearing=math_rad(value["azimuth_deg"]), sigma_bearing=sigma,
                           range_m=value["range_m"], sigma_range=math.hypot(_sigma(obs, "range_m"), pose.sigma),
                           radial_mps=value["radial_mps"], sigma_radial=_sigma(obs, "radial_mps"), **base)
    if kind == "detection" and "source_level_db" in module["sim"]["noise"]:
        range_m, sigma = _range_from_level(obs, module["sim"]["noise"]["source_level_db"])
        return Measurement(RANGE, range_m=range_m, sigma_range=math.hypot(sigma, pose.sigma), **base)
    return None
