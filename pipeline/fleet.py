"""The friendly drones in motion: a scripted patrol that can be interrupted by a flight command.

Simulation side (it moves the true positions the sensors see), a stand-in for the drone-flight part of the
drone-behaviour module until the real one is wired in. A drone follows its scenario patrol loop; `command`
sends it to a point with a camera direction; `release` makes it fly back to where the patrol would be now and
rejoin. Limits (speed, acceleration) come from the catalog's `spec.flight` for the drone's platform, which
are assumed numbers. Not modelled: turn rate, mutual separation, obstacles, command loss.
"""

import math
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from common.seeder_import import ensure_seeder_on_path
from sensors.quality import load_platforms
from sensors.world import Pose

ensure_seeder_on_path()
import scenario as seeder_scenario  # noqa: E402  (seeder/scenario.py)

REJOIN_DISTANCE_M = 8.0   # a returning drone this close to its planned position resumes the patrol
PATROL, GOTO, RETURN = "patrol", "goto", "return"


@dataclass
class Drone:
    id: str
    plan: dict                      # the scenario's friendly entry, with its patrol loop
    max_speed: float
    max_accel: float
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    heading: float = 0.0
    mode: str = PATROL
    target: Optional[Tuple[float, float]] = None
    face: Optional[Tuple[float, float]] = None


class Fleet:
    def __init__(self, scenario: dict):
        limits = {p["id"]: p["spec"]["flight"] for p in load_platforms() if "flight" in p.get("spec", {})}
        self.drones: Dict[str, Drone] = {}
        for f in scenario["friendlies"]:
            flight = limits.get(f["platform"], {"max_speed_mps": 15.0, "max_accel_mps2": 4.0})
            d = Drone(f["id"], f, flight["max_speed_mps"], flight["max_accel_mps2"])
            self._follow_plan(d, 0.0)
            self.drones[f["id"]] = d
        self.t = 0.0

    # ----------------------------------------------------------------- commands
    def command(self, drone_id: str, target: Tuple[float, float], face: Optional[Tuple[float, float]] = None) -> None:
        d = self.drones[drone_id]
        d.mode, d.target, d.face = GOTO, target, face

    def release(self, drone_id: str) -> None:
        d = self.drones[drone_id]
        if d.mode != PATROL:
            d.mode, d.face = RETURN, None

    def is_free(self, drone_id: str) -> bool:
        return self.drones[drone_id].mode == PATROL

    # ------------------------------------------------------------------- motion
    def step(self, t: float) -> None:
        dt, self.t = max(0.0, t - self.t), t
        for d in self.drones.values():
            if d.mode == PATROL:
                self._follow_plan(d, t)
                continue
            if d.mode == RETURN:
                planned = seeder_scenario.friendly_state(d.plan, t)
                d.target = (planned["x"], planned["y"])
                if math.hypot(d.x - d.target[0], d.y - d.target[1]) < REJOIN_DISTANCE_M:
                    d.mode = PATROL
                    self._follow_plan(d, t)
                    continue
            self._fly_towards(d, dt)

    def _follow_plan(self, d: Drone, t: float) -> None:
        s = seeder_scenario.friendly_state(d.plan, t)
        d.x, d.y, d.vx, d.vy = s["x"], s["y"], s["vx"], s["vy"]
        d.heading = math.atan2(s["vy"], s["vx"])

    def _fly_towards(self, d: Drone, dt: float) -> None:
        dx, dy = d.target[0] - d.x, d.target[1] - d.y
        distance = math.hypot(dx, dy)
        speed_wanted = min(d.max_speed, math.sqrt(2.0 * d.max_accel * distance)) if distance > 0.5 else 0.0
        wanted = (dx / distance * speed_wanted, dy / distance * speed_wanted) if distance > 0.5 else (0.0, 0.0)
        dvx, dvy = wanted[0] - d.vx, wanted[1] - d.vy
        change = math.hypot(dvx, dvy)
        limit = d.max_accel * dt
        if change > limit > 0:
            dvx, dvy = dvx * limit / change, dvy * limit / change
        d.vx, d.vy = d.vx + dvx, d.vy + dvy
        d.x, d.y = d.x + d.vx * dt, d.y + d.vy * dt
        if d.face is not None:
            d.heading = math.atan2(d.face[1] - d.y, d.face[0] - d.x)
        elif math.hypot(d.vx, d.vy) > 1.0:
            d.heading = math.atan2(d.vy, d.vx)

    # --------------------------------------------------------------------- query
    def pose(self, drone_id: str, altitude_m: float) -> Pose:
        d = self.drones[drone_id]
        return Pose(d.x, d.y, d.vx, d.vy, altitude_m, d.heading)
