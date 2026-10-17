"""Where each sensor node is, as the tracker may know it, and how well.

A friendly drone's position comes from its own beacons, smoothed by a small Kalman filter per drone (a beacon
is noisy, 3 m or more, and arrives at 2 Hz) and extrapolated to the time of a reading; a ground sensor's
position is in `scenario.json`. When a drone's beacons stop arriving the book falls back to the planned patrol
loop from `scenario.json`, which is the plan, not the truth: that is wrong whenever the drone was commanded
away. `Pose2D.sigma` is the 1-sigma position uncertainty of the answer, which `measurement.py` adds to the
noise of every reading from a sensor on that drone (a position error of 4 m moves a bearing at 100 m range by
2.3 degrees, more than a camera's own noise).
"""

import math
from typing import Dict, Tuple

from common.seeder_import import ensure_seeder_on_path
from tracker.ekf import Mat, Vec, identity_like, predict, scalar_update
from tracker.measurement import Pose2D

ensure_seeder_on_path()
import scenario as seeder_scenario  # noqa: E402  (seeder/scenario.py)

MAX_BEACON_AGE_S = 3.0
POSE_ACCEL_NOISE_MPS2 = 3.0        # how much a drone may accelerate between beacons (a commanded one does)
BEACON_VELOCITY_SIGMA_MPS = 0.5    # a GNSS-like velocity


class PoseBook:
    def __init__(self, scenario: dict):
        self.ground = {g["id"]: Pose2D(g["position"][0], g["position"][1]) for g in scenario["ground"]}
        self.plan = {f["id"]: f for f in scenario["friendlies"]}
        self._filters: Dict[str, Tuple[float, Vec, Mat]] = {}     # node -> (time of the state, state, covariance)
        self.fallbacks = 0     # poses taken from the plan because no recent beacon was available

    def note_beacon(self, beacon: dict) -> None:
        """Fold a delivered beacon into its drone's filter; `t_sent` is the drone's own clock, which can be off."""
        sigma = math.sqrt(beacon["covariance"][0][0])
        sent = beacon["header"]["t_sent"]
        measured = (beacon["position"][0], beacon["position"][1], beacon["velocity"][0], beacon["velocity"][1])
        variances = (sigma ** 2, sigma ** 2, BEACON_VELOCITY_SIGMA_MPS ** 2, BEACON_VELOCITY_SIGMA_MPS ** 2)
        previous = self._filters.get(beacon["friend_id"])
        if previous is None or sent - previous[0] > MAX_BEACON_AGE_S or sent < previous[0]:
            self._filters[beacon["friend_id"]] = (sent, list(measured), identity_like(list(variances)))
            return
        state, cov = predict(previous[1], previous[2], sent - previous[0], POSE_ACCEL_NOISE_MPS2)
        for i, variance in enumerate(variances):
            h = [1.0 if k == i else 0.0 for k in range(4)]
            state, cov = scalar_update(state, cov, measured[i] - state[i], h, variance)
        self._filters[beacon["friend_id"]] = (sent, state, cov)

    def pose(self, node: str, t: float) -> Pose2D:
        if node in self.ground:
            return self.ground[node]
        known = self._filters.get(node)
        if known is not None and abs(t - known[0]) <= MAX_BEACON_AGE_S:
            sent, state, cov = known
            dt = t - sent
            ahead, ahead_cov = predict(state, cov, abs(dt), POSE_ACCEL_NOISE_MPS2)
            x = state[0] + state[2] * dt
            y = state[1] + state[3] * dt
            sigma = math.sqrt((ahead_cov[0][0] + ahead_cov[1][1]) / 2.0)
            return Pose2D(x, y, state[2], state[3], sigma)
        self.fallbacks += 1
        s = seeder_scenario.friendly_state(self.plan[node], t)
        return Pose2D(s["x"], s["y"], s["vx"], s["vy"], FALLBACK_SIGMA_M)


FALLBACK_SIGMA_M = 15.0   # the plan is a guess for a drone that may have been commanded away
