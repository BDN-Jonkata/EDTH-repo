"""Where each sensor node is, as the tracker may know it.

A friendly drone's position comes from its own beacons (extrapolated with the beacon's velocity); a ground
sensor's position is in `scenario.json`. When a drone's beacons stop arriving the book falls back to the
planned patrol loop from `scenario.json`, which is the plan, not the truth. That is wrong whenever the
drone was commanded away, so a lost beacon link costs accuracy for bearing sensors on drones.
"""

from typing import Dict, Tuple

from common.seeder_import import ensure_seeder_on_path
from tracker.measurement import Pose2D

ensure_seeder_on_path()
import scenario as seeder_scenario  # noqa: E402  (seeder/scenario.py)

MAX_BEACON_AGE_S = 3.0


class PoseBook:
    def __init__(self, scenario: dict):
        self.ground = {g["id"]: Pose2D(g["position"][0], g["position"][1]) for g in scenario["ground"]}
        self.plan = {f["id"]: f for f in scenario["friendlies"]}
        self._beacon: Dict[str, Tuple[float, Pose2D]] = {}
        self.fallbacks = 0     # poses taken from the plan because no recent beacon was available

    def note_beacon(self, beacon: dict) -> None:
        """Remember a delivered beacon; `t_sent` is the drone's own clock, which can be off."""
        x, y, _z = beacon["position"]
        vx, vy, _vz = beacon["velocity"]
        self._beacon[beacon["friend_id"]] = (beacon["header"]["t_sent"], Pose2D(x, y, vx, vy))

    def pose(self, node: str, t: float) -> Pose2D:
        if node in self.ground:
            return self.ground[node]
        sent, p = self._beacon.get(node, (None, None))
        if sent is not None and abs(t - sent) <= MAX_BEACON_AGE_S:   # a drone's clock can run ahead as well as behind
            dt = t - sent
            return Pose2D(p.x + p.vx * dt, p.y + p.vy * dt, p.vx, p.vy)
        self.fallbacks += 1
        s = seeder_scenario.friendly_state(self.plan[node], t)
        return Pose2D(s["x"], s["y"], s["vx"], s["vy"])
