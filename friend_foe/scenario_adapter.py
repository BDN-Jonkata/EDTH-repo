"""Turn a `scenario.json` into estimator input frames.

TEST STAND-IN for the real pipeline, until the simulation and tracker exist:

* tracks: every friendly and every hostile, from the motion formulas in
  `scenario.json` (`friendly_state`, `target_state` from the seeder) plus
  position noise. A real tracker would not know the ids or have clean tracks.
* beacons: each friendly broadcasts at `beacon.rate_hz` with `beacon.pos_sigma_m`
  noise; `degradations.network.loss` drops them at random.

It never reads `truth.json`.
"""

import random
from typing import Dict, Iterator, List, Tuple

from common.seeder_import import ensure_seeder_on_path
from friend_foe.estimator import Beacon, TrackState

ensure_seeder_on_path()
import scenario as seeder_scenario  # noqa: E402  (seeder/scenario.py)

Frame = Tuple[float, List[TrackState], List[Beacon]]


def _noisy(rng: random.Random, xy_state: dict, altitude: float, sigma: float):
    pos = (xy_state["x"] + rng.gauss(0, sigma), xy_state["y"] + rng.gauss(0, sigma), altitude)
    return pos, (xy_state["vx"], xy_state["vy"], 0.0)


def _track(tid: str, t: float, pos, vel, sigma: float) -> TrackState:
    return TrackState(tid, t, pos, vel, pos_sigma=sigma, existence_prob=0.95)


def frames_from_scenario(scenario: dict, dt: float = 0.5, seed: int = 0, track_sigma: float = 2.0) -> Iterator[Frame]:
    rng = random.Random(seed)
    beacon_cfg = scenario["beacon"]
    loss = scenario["degradations"]["network"].get("loss", 0.0)
    period = 1.0 / beacon_cfg["rate_hz"]
    next_beacon: Dict[str, float] = {f["id"]: 0.0 for f in scenario["friendlies"]}

    for k in range(int(scenario["duration_s"] / dt) + 1):
        t = k * dt
        tracks, beacons = [], []
        for f in scenario["friendlies"]:
            state = seeder_scenario.friendly_state(f, t)
            pos, vel = _noisy(rng, state, f["altitude_m"], track_sigma)
            tracks.append(_track(f["id"], t, pos, vel, track_sigma))
            if beacon_cfg["enabled"] and t >= next_beacon[f["id"]] - 1e-9:
                next_beacon[f["id"]] += period
                if rng.random() >= loss:
                    bpos, _ = _noisy(rng, state, f["altitude_m"], beacon_cfg["pos_sigma_m"])
                    beacons.append(Beacon(f["id"], t, bpos, vel, beacon_cfg["pos_sigma_m"]))
        for tg in scenario["targets"]:
            state = seeder_scenario.target_state(tg, t)
            if state is not None:
                pos, vel = _noisy(rng, state, tg["altitude_m"], track_sigma)
                tracks.append(_track(tg["id"], t, pos, vel, track_sigma))
        yield t, tracks, beacons
