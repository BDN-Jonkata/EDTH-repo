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
    # Exercise the default policy with no authorized corridor, including noisy
    # derivative estimates and circles whose tangent sometimes points at C2.
    for name in ("default_transit", "neutral_silence", "noisy_transit", "safe_orbit", "noisy_orbit", "protected_orbit", "repeated_entry", "association_jump"):
        default_policy = BehaviorConfig.for_area([500, 500])
        est, frames = AutomaticEstimator(default_policy), []
        for k in range(101):
            t = k / 2
            x, y, vx, vy = 100 + 10 * t, 100, 10, 0
            if name == "neutral_silence":
                x, vx = 100, 0
            elif name == "noisy_transit":
                x += math.sin(7 * t)
                y += math.cos(5 * t)
                vx += 3 * math.sin(11 * t)
                vy += 3 * math.cos(9 * t)
            elif name in ("safe_orbit", "noisy_orbit", "protected_orbit"):
                cy = 500 if name == "protected_orbit" else 850
                a, noise = t / 6, int(name == "noisy_orbit")
                x, y = 500 + 50 * math.cos(a), cy + 50 * math.sin(a)
                vx, vy = -50 / 6 * math.sin(a) + noise * 2 * math.sin(11 * t), 50 / 6 * math.cos(a) + noise * 2 * math.cos(9 * t)
            elif name == "repeated_entry":
                x, y, vx = 650 + 35 * math.cos(t / 2), 500, -17.5 * math.sin(t / 2)
            elif name == "association_jump" and t >= 25.5:
                x, y, vx = 500, 500, 0
            tracks = [TrackState("opaque", t, (x, y, 60), (vx, vy, 0), 2)]
            result = est.update(t, tracks, [])
            frames.append({"t": t, "tracks": [asdict(tr) for tr in tracks], "beacons": [],
                           "expected": [asdict(c) for c in result], "evidence": {"opaque": est.explain("opaque")}})
        cases.append({"name": name, "policy": asdict(default_policy), "verified_ids": [], "frames": frames})
    return {"estimator_config": asdict(EstimatorConfig()), "cases": cases}


if __name__ == "__main__":
    print(json.dumps(build_cases(), allow_nan=False))
