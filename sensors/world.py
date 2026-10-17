"""The world a scenario describes, at a time `t`: where the nodes and the objects are.

Built only from `scenario.json` through the seeder's own motion formulas (`friendly_state`,
`target_state`), never from `truth.json`. Used by the observation source, the only place that
needs to know where things really are in order to draw what a sensor would see.
"""

import math
from dataclasses import dataclass
from typing import Dict, List, Optional

from common.seeder_import import ensure_seeder_on_path

ensure_seeder_on_path()
import scenario as seeder_scenario  # noqa: E402  (seeder/scenario.py)

GROUND_SENSOR_ALTITUDE_M = 5.0


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    vx: float
    vy: float
    altitude_m: float
    heading: Optional[float]      # maths radians (0 = east, counter-clockwise); None while the direction is unknown


@dataclass(frozen=True)
class Body:
    """Something a sensor can detect."""
    id: str
    role: str                     # friendly | hostile | clutter
    x: float
    y: float
    vx: float
    vy: float
    altitude_m: float
    signature: Dict[str, float]
    emits: bool


class World:
    def __init__(self, scenario: dict):
        self.friendlies = {f["id"]: f for f in scenario["friendlies"]}
        self.ground = {g["id"]: g for g in scenario["ground"]}
        self.targets = scenario["targets"]
        self.clutter = scenario.get("clutter", [])

    def node_pose(self, node: str, t: float) -> Pose:
        if node in self.ground:
            g = self.ground[node]
            return Pose(g["position"][0], g["position"][1], 0.0, 0.0, GROUND_SENSOR_ALTITUDE_M,
                        math.radians(90.0 - g["heading_deg"]))
        f = self.friendlies[node]
        s = seeder_scenario.friendly_state(f, t)
        return Pose(s["x"], s["y"], s["vx"], s["vy"], f["altitude_m"], math.atan2(s["vy"], s["vx"]))

    def bodies_at(self, t: float) -> List[Body]:
        bodies = []
        for f in self.friendlies.values():
            s = seeder_scenario.friendly_state(f, t)
            bodies.append(Body(f["id"], "friendly", s["x"], s["y"], s["vx"], s["vy"], f["altitude_m"], {}, True))
        for role, objects in (("hostile", self.targets), ("clutter", self.clutter)):
            for o in objects:
                s = seeder_scenario.target_state(o, t)
                if s is not None:
                    bodies.append(Body(o["id"], role, s["x"], s["y"], s["vx"], s["vy"], o["altitude_m"],
                                       o.get("signature", {}), o.get("emits", True)))
        return bodies
