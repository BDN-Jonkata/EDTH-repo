"""Turn a `scenario.json` into estimator input frames.

TEST STAND-IN for the real pipeline, until the simulation and tracker exist:

* tracks: every friendly, hostile and clutter object (birds, vehicles), from the motion formulas in
  `scenario.json` (`friendly_state`, `target_state` from the seeder) plus
  position noise. A real tracker would not know the ids or have clean tracks.
* beacons: each friendly broadcasts at `beacon.rate_hz` with `beacon.pos_sigma_m`
  noise, then the scenario's `degradations` act on them (each only when its
  `enabled` is true): `network` (loss, bursty loss, delay in `latency_ms`),
  `clock` (per-node offset and drift stamp the beacon's `t_sent`) and `pose`
  (position error added to the beacon and to the tracks, reported as honest sigma).

Assumptions, since the scenario only gives ranges: bursty loss is a two-state
chain with a mean burst of `MEAN_BURST` messages and the configured average
loss; a node's clock offset is a random sign times a value in `offset_ms`, and
its drift a random sign times `drift_ppm`. Not modelled: jamming zones, node
dropout, topology. It never reads `truth.json`.
"""

import math
import random
from typing import Dict, Iterator, List, Tuple

from common.seeder_import import ensure_seeder_on_path
from friend_foe.estimator import Beacon, TrackState

ensure_seeder_on_path()
import scenario as seeder_scenario  # noqa: E402  (seeder/scenario.py)

Frame = Tuple[float, List[TrackState], List[Beacon]]
MEAN_BURST = 5.0   # assumed mean length of a loss burst, in messages


class _Loss:
    """Packet loss with the configured average, independent or bursty (two-state chain)."""

    def __init__(self, rng: random.Random, loss: float, burst: bool):
        self.rng, self.loss, self.burst, self.bad = rng, loss, burst, False
        self.p_bad_to_good = 1.0 / MEAN_BURST
        self.p_good_to_bad = loss * self.p_bad_to_good / (1 - loss) if 0 < loss < 1 else 0.0
        if self.p_good_to_bad > 1.0:   # very high loss: lengthen the bursts instead
            self.p_good_to_bad, self.p_bad_to_good = 1.0, (1 - loss) / loss

    def drops(self) -> bool:
        if not self.burst:
            return self.rng.random() < self.loss
        flip = self.p_bad_to_good if self.bad else self.p_good_to_bad
        if self.rng.random() < flip:
            self.bad = not self.bad
        return self.bad


class _Clock:
    """A node's local clock: random offset and drift, as the scenario's ranges allow."""

    def __init__(self, rng: random.Random, clock: dict):
        on = clock.get("enabled", False)
        lo, hi = clock.get("offset_ms", [0, 0]) if on else (0, 0)
        self.offset_s = rng.choice((-1, 1)) * rng.uniform(lo, hi) / 1000.0
        self.drift = rng.choice((-1, 1)) * clock.get("drift_ppm", 0) * 1e-6 if on else 0.0

    def local(self, t: float) -> float:
        return t * (1.0 + self.drift) + self.offset_s


class _Feed:
    def __init__(self, scenario: dict, seed: int, track_sigma: float):
        self.s, self.rng = scenario, random.Random(seed)
        deg = scenario["degradations"]
        net, pose = deg["network"], deg["pose"]
        self.delay_ms = net.get("latency_ms", [0, 0]) if net.get("enabled") else (0, 0)
        loss = net.get("loss", 0.0) if net.get("enabled") else 0.0
        pose_err = pose.get("position_err_m", 0.0) if pose.get("enabled") else 0.0
        self.track_sigma = math.hypot(track_sigma, pose_err)
        self.beacon_sigma = math.hypot(scenario["beacon"]["pos_sigma_m"], pose_err)
        ids = [f["id"] for f in scenario["friendlies"]]
        self.links = {i: _Loss(self.rng, loss, bool(net.get("burst"))) for i in ids}
        self.clocks = {i: _Clock(self.rng, deg["clock"]) for i in ids}
        self.next_beacon: Dict[str, float] = {i: 0.0 for i in ids}
        self.in_flight: List[Tuple[float, Beacon]] = []   # (arrival time, beacon)

    def frame(self, t: float) -> Frame:
        tracks = []
        for f in self.s["friendlies"]:
            state = seeder_scenario.friendly_state(f, t)
            tracks.append(self._track(f["id"], t, state, f["altitude_m"]))
            self._send_beacon(f, state, t)
        for obj in self.s["targets"] + self.s.get("clutter", []):   # clutter: birds and vehicles, never beacons
            state = seeder_scenario.target_state(obj, t)
            if state is not None:
                tracks.append(self._track(obj["id"], t, state, obj["altitude_m"]))
        return t, tracks, self._arrived(t)

    def _noisy(self, state: dict, altitude: float, sigma: float):
        pos = (state["x"] + self.rng.gauss(0, sigma), state["y"] + self.rng.gauss(0, sigma), altitude)
        return pos, (state["vx"], state["vy"], 0.0)

    def _track(self, tid: str, t: float, state: dict, altitude: float) -> TrackState:
        pos, vel = self._noisy(state, altitude, self.track_sigma)
        return TrackState(tid, t, pos, vel, pos_sigma=self.track_sigma, existence_prob=0.95)

    def _send_beacon(self, f: dict, state: dict, t: float) -> None:
        cfg, fid = self.s["beacon"], f["id"]
        if not cfg["enabled"] or t < self.next_beacon[fid] - 1e-9:
            return
        self.next_beacon[fid] += 1.0 / cfg["rate_hz"]
        if self.links[fid].drops():
            return
        pos, vel = self._noisy(state, f["altitude_m"], self.beacon_sigma)
        sent = self.clocks[fid].local(t)
        delay = self.rng.uniform(*self.delay_ms) / 1000.0
        self.in_flight.append((t + delay, Beacon(fid, sent, pos, vel, self.beacon_sigma)))

    def _arrived(self, t: float) -> List[Beacon]:
        due = [b for at, b in self.in_flight if at <= t + 1e-9]
        self.in_flight = [(at, b) for at, b in self.in_flight if at > t + 1e-9]
        return due


def frames_from_scenario(scenario: dict, dt: float = 0.5, seed: int = 0, track_sigma: float = 2.0) -> Iterator[Frame]:
    feed = _Feed(scenario, seed, track_sigma)
    for k in range(int(scenario["duration_s"] / dt) + 1):
        yield feed.frame(k * dt)
