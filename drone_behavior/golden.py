"""Emit Python reference input/output sequences for the viewer's parity tests."""

import json
import math
from dataclasses import asdict

from drone_behavior import BehaviorConfig
from friend_foe.automatic import AutomaticEstimator
from friend_foe.estimator import Beacon, EstimatorConfig, TrackState


def build_cases():
    policy = BehaviorConfig.for_area([500, 500], corridors=[{
        "start": [0, 100], "end": [1000, 100], "half_width_m": 30,
    }])
    cases = []
    for name in ("entry", "loiter", "corridor", "noisy", "replayed", "verified", "coasting", "changed", "ambiguous", "one_to_one", "patrol_similarity"):
        est = AutomaticEstimator(policy, verified_ids=["track-a"] if name == "verified" else [])
        frames = []
        for k in range(81):
            t = k / 2
            x, y, vx, vy, sigma, obs = 200 + 10 * t, 500, 10, 0, 2, t
            if name in ("corridor", "replayed"):
                x, y = 100 + 10 * t, 100
            elif name == "loiter":
                x, vx = 500, 0
            elif name == "noisy":
                sigma = 100
            elif name == "coasting" and t > 22:
                obs = 22
            elif name == "changed":
                if t < 15:
                    x, vx = 500, 0
                else:
                    x, y = 100 + 10 * (t - 15), 100
            elif name in ("ambiguous", "patrol_similarity"):
                x, y, vx, vy = 100 + 20 * math.cos(t / 4), 100 + 20 * math.sin(t / 4), -5 * math.sin(t / 4), 5 * math.cos(t / 4)
            tracks = [TrackState("track-a", t, (x, y, 60), (vx, vy, 0), sigma, observed_t=obs)]
            beacons = []
            if name in ("verified", "one_to_one"):
                beacons = [Beacon("trusted", t, (x, y, 60), (vx, vy, 0), 2)] if k % 3 else []
            elif name == "replayed" and t <= 2:
                beacons = [Beacon("trusted", 0, (100, 100, 60), (10, 0, 0), 2)]
            if name == "one_to_one":
                tracks.append(TrackState("track-b", t, (x + 3, y, 60), (vx, vy, 0), 2))
            if name == "patrol_similarity":
                tracks.append(TrackState("track-b", t, (x + 40, y + 40, 60), (vx, vy, 0), 2))
                beacons = [Beacon("trusted-b", t, tracks[-1].position, tracks[-1].velocity, 2)]
            result = est.update(t, tracks, beacons)
            frames.append({"t": t, "tracks": [asdict(tr) for tr in tracks], "beacons": [asdict(b) for b in beacons],
                           "expected": [asdict(c) for c in result],
                           "evidence": {tr.track_id: est.explain(tr.track_id) for tr in tracks}})
        cases.append({"name": name, "policy": asdict(policy), "verified_ids": ["track-a"] if name == "verified" else [], "frames": frames})
    return {"estimator_config": asdict(EstimatorConfig()), "cases": cases}


if __name__ == "__main__":
    print(json.dumps(build_cases(), allow_nan=False))
