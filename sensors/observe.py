"""Observation source: what each node's sensors see in a scenario, as `observation` messages.

Every detection module a node carries (from `scenario.json` `sensors[]`, numbers from the catalog) fires
at its own rate. An object is detected when it is inside the module's range window and field of view
(for a forward-pointing sensor: where the drone is heading), a silent hostile is invisible to RF, and a
random draw beats a detection probability that falls with distance, scales with the object's signature
and is scaled by the weather *at that detection* (`sensors/quality.py`). A radar cell merges objects closer
than its resolution. Radars also report random false alarms. Each reading carries only its native fields
and honest noise (`sensors/native.py`).

This models the sensors only: messages leave here undelayed and complete; `tracker/channel.py` loses and
delays them. It needs the true positions, so it belongs to the simulation side and must not be used
inside the tracker.
"""

import math
import random
from dataclasses import dataclass
from typing import Dict, List, Optional

from common.codec import Sequencer
from sensors.native import OBSERVATION_KIND, Detection, Viewpoint, read
from sensors.quality import DETECTION_KINDS, load_modules, sensor_quality
from sensors.weather import conditions_between, weather_from_scenario
from sensors.world import Body, Pose, World

SIGNATURE_KEY = {"eo_camera": "eo", "thermal_camera": "thermal", "microphone": "acoustic",
                 "rf_receiver": "rf", "radar": "radar"}
GHOST_ALTITUDE_M = 30.0
MIN_RANGE_FOR_DETECTION_M = 1.0


@dataclass
class Mount:
    node: str
    module: dict
    next_t: float = 0.0

    @property
    def period_s(self) -> float:
        return 1.0 / self.module["sim"]["rate_hz"]


def _wrap_pi(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


def mounts_of(scenario: dict, modules: Dict[str, dict]) -> List[Mount]:
    out = []
    for node in list(scenario["friendlies"]) + list(scenario["ground"]):
        for s in node["sensors"]:
            if modules[s["module"]]["kind"] in DETECTION_KINDS and s["kind"] in scenario["sensor_set"]["enabled_kinds"]:
                out.append(Mount(node["id"], modules[s["module"]]))
    return out


class ObservationSource:
    def __init__(self, scenario: dict, seed: int = 0, modules: Optional[Dict[str, dict]] = None,
                 sequencers: Optional[Dict[str, Sequencer]] = None, world: Optional[World] = None):
        """`sequencers` lets the beacon source share one message counter per node, as the header rules say;
        `world` lets the sources share one world, for example one whose drones can be commanded."""
        self.scenario, self.rng = scenario, random.Random(seed)
        self.world, self.weather = world or World(scenario), weather_from_scenario(scenario)
        self.mounts = mounts_of(scenario, modules or load_modules())
        self.seq = sequencers if sequencers is not None else {}
        self.false_alarms_per_s = scenario["environment"].get("clutter", {}).get("false_alarms_per_min", 0.0) / 60.0
        self.radars = max(1, sum(m.module["kind"] == "radar" for m in self.mounts))

    def at(self, t: float) -> List[dict]:
        """The observations produced at time `t`; call with increasing `t`."""
        due = [m for m in self.mounts if t >= m.next_t - 1e-9]
        bodies = self.world.bodies_at(t) if due else []
        out = []
        for mount in due:
            mount.next_t += mount.period_s
            out += self._fire(mount, t, bodies)
        return out

    def _fire(self, mount: Mount, t: float, bodies: List[Body]) -> List[dict]:
        pose = self.world.node_pose(mount.node, t)
        seen = self._detect(mount, pose, t, [b for b in bodies if b.id != mount.node])
        if mount.module["kind"] == "radar":
            seen = _merge_cells(seen, mount.module["sim"].get("resolution_cell"))
            seen += self._false_alarms(mount, pose, t)
        return [self._message(mount, pose, t, d, v) for d, v in seen]

    def _detect(self, mount: Mount, pose: Pose, t: float, bodies: List[Body]):
        sim, out = mount.module["sim"], []
        for b in bodies:
            q = sensor_quality(mount.module, conditions_between(self.weather, (pose.x, pose.y), (b.x, b.y), t))
            det = _geometry(pose, b)
            max_range = sim["range_m"] * q.range_scale
            if not self._visible(mount, pose, b, det, max_range, q.pd_scale):
                continue
            out.append((det, Viewpoint(pose.vx, pose.vy, pose.altitude_m, max_range, q.noise_scale)))
        return out

    def _visible(self, mount: Mount, pose: Pose, body: Body, det: Detection, max_range: float, pd_scale: float) -> bool:
        sim = mount.module["sim"]
        if not (max(sim["min_range_m"], MIN_RANGE_FOR_DETECTION_M) <= det.range_m <= max_range):
            return False
        if mount.module["kind"] == "rf_receiver" and not body.emits:
            return False
        if sim["pointing"] != "omni" and pose.heading is not None:
            if abs(_wrap_pi(det.az - pose.heading)) > math.radians(sim["fov_deg"]) / 2:
                return False
        signature = body.signature.get(SIGNATURE_KEY[mount.module["kind"]], 1.0)
        thinning = 1.0 - (1.0 - sim["pd_far"]) * (det.range_m / max_range) ** 2
        return self.rng.random() <= min(1.0, sim["pd"] * pd_scale * signature) * thinning

    def _false_alarms(self, mount: Mount, pose: Pose, t: float):
        sim = mount.module["sim"]
        if self.rng.random() >= self.false_alarms_per_s / self.radars * mount.period_s:
            return []
        heading = pose.heading if sim["pointing"] != "omni" and pose.heading is not None else 0.0
        half = math.pi if sim["pointing"] == "omni" else math.radians(sim["fov_deg"]) / 2
        az = heading + (self.rng.random() * 2 - 1) * half
        r = sim["min_range_m"] + math.sqrt(self.rng.random()) * (sim["range_m"] - sim["min_range_m"])
        ghost = Detection(az, r, 0.0, 0.0, GHOST_ALTITUDE_M, False)
        return [(ghost, Viewpoint(pose.vx, pose.vy, pose.altitude_m, sim["range_m"], 1.0))]

    def _message(self, mount: Mount, pose: Pose, t: float, det: Detection, view: Viewpoint) -> dict:
        value, sigma = read(mount.module, det, view, self.rng)
        fields = list(sigma)
        sequencer = self.seq.setdefault(mount.node, Sequencer(mount.node))
        return {
            "type": "observation", "header": sequencer.header(t),
            "sensor_type": mount.module["kind"], "sensor_id": mount.module["id"], "t_obs": t,
            "kind": OBSERVATION_KIND[mount.module["native"]["type"]],
            "value": value, "cov_fields": fields,
            "covariance": [[sigma[a] ** 2 if a == b else 0.0 for b in fields] for a in fields],
        }


def _geometry(pose: Pose, body: Body) -> Detection:
    dx, dy = body.x - pose.x, body.y - pose.y
    return Detection(math.atan2(dy, dx), math.hypot(dx, dy), body.vx, body.vy, body.altitude_m, body.role == "friendly")


def _merge_cells(seen, cell: Optional[dict]):
    """Objects closer than the radar's resolution cell in range and azimuth merge into one detection at their centroid."""
    if not cell or len(seen) < 2:
        return seen
    out, used = [], set()
    for i, (a, view) in enumerate(seen):
        if i in used:
            continue
        members = [j for j in range(i, len(seen)) if j not in used and (j == i or _in_cell(a, seen[j][0], cell))]
        used.update(members)
        out.append((_centroid([seen[j][0] for j in members]), view))
    return out


def _in_cell(a: Detection, b: Detection, cell: dict) -> bool:
    return abs(a.range_m - b.range_m) < cell["range_m"] and abs(_wrap_pi(a.az - b.az)) < math.radians(cell["azimuth_deg"])


def _centroid(group: List[Detection]) -> Detection:
    n = len(group)
    mean = lambda key: sum(getattr(g, key) for g in group) / n
    return Detection(mean("az"), mean("range_m"), mean("vx"), mean("vy"), mean("altitude_m"), group[0].friendly)
