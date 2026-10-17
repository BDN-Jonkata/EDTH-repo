"""Friendly position beacons: each friendly drone reports its own position at `beacon.rate_hz`.

The position carries the beacon's noise (`beacon.pos_sigma_m`) plus the scenario's pose error when that
degradation is enabled, and the header's `t_sent` is stamped by the drone's own clock (offset and drift
when the clock degradation is enabled), so clock error shows up as a position error. Like
`sensors/observe.py`, this is the simulation side: it needs the true position.
"""

import math
import random
from typing import Dict, List, Optional

from common.channel import Clock
from common.codec import Sequencer
from sensors.world import World


class BeaconSource:
    def __init__(self, scenario: dict, seed: int = 0, sequencers: Optional[Dict[str, Sequencer]] = None,
                 world: Optional[World] = None):
        self.cfg, self.friendlies = scenario["beacon"], scenario["friendlies"]
        self.world = world or World(scenario)
        self.rng = random.Random(seed)
        deg = scenario["degradations"]
        pose_err = deg["pose"].get("position_err_m", 0.0) if deg["pose"].get("enabled") else 0.0
        self.sigma = math.hypot(self.cfg["pos_sigma_m"], pose_err)
        self.clocks = {f["id"]: Clock(self.rng, deg["clock"]) for f in self.friendlies}
        self.seq = sequencers if sequencers is not None else {}
        self.next_t = 0.0

    def at(self, t: float) -> List[dict]:
        """The beacons sent at time `t`; call with increasing `t`."""
        if not self.cfg["enabled"] or t < self.next_t - 1e-9:
            return []
        self.next_t += 1.0 / self.cfg["rate_hz"]
        return [self._beacon(f, t) for f in self.friendlies]

    def _beacon(self, f: dict, t: float) -> dict:
        s = self.world.node_pose(f["id"], t)
        position = [s.x + self.rng.gauss(0, self.sigma), s.y + self.rng.gauss(0, self.sigma), f["altitude_m"]]
        sequencer = self.seq.setdefault(f["id"], Sequencer(f["id"]))
        v2 = self.sigma ** 2
        return {
            "type": "friendly_beacon", "header": sequencer.header(self.clocks[f["id"]].local(t)),
            "friend_id": f["id"], "position": position, "velocity": [s.vx, s.vy, 0.0],
            "covariance": [[v2 if i == j else 0.0 for j in range(3)] for i in range(3)],
        }
