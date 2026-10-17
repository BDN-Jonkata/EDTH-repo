"""Baseline multi-target tracker: one Kalman filter per track on native measurements, gated association,
track initiation from a radar fix or from two bearings that cross, and a track life cycle with support rules.

Per step: predict every track to now; feed the friendly beacons in (a beacon is a cooperative position
reading, so each friendly drone has a track of its own and sensor readings of it are absorbed, not mistaken
for an intruder); match each sensor scan's readings to tracks (optimal assignment within the gate, so two
readings of one scan never feed the same track); start tentative tracks from the readings nothing claimed;
confirm tracks that are well pinned down and supported, and drop those that stop being updated.

Support: a bearing alone says nothing about range, so a track is confirmed (and stays confirmed) only
while it gets a range-capable reading (radar, microphone level) or readings from at least `min_nodes`
different nodes. Without that, bearings of other objects along the same line keep a wandering track alive.

Simplifications (a baseline, not the final tracker): readings are used at their arrival time, not at their
`t_obs` (latency of a few hundred milliseconds is a few metres of error); one central tracker, not one per
node; no covariance intersection; constant-velocity motion only.
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from common.assignment import assign
from tracker.ekf import Mat, Vec, identity_like, predict, scalar_update
from tracker.measurement import BEARING, RANGE_BEARING, RANGE, Measurement
from tracker.models import apply_measurement, fix_from_range_bearing, gate_cost, triangulate

NO_MATCH = 1e8
BIG_GATE = 1e7
RANGE_KINDS = (RANGE, RANGE_BEARING)


@dataclass
class TrackerConfig:
    accel_noise_mps2: float = 3.0          # how much a target is assumed to manoeuvre (1-sigma)
    initial_speed_sigma_mps: float = 12.0  # velocity is unknown when a track starts
    confirm_updates: int = 5               # readings within `confirm_window_s` that confirm a track
    confirm_window_s: float = 4.0
    confirm_max_sigma_m: float = 30.0      # not confirmed while the position is this uncertain
    support_window_s: float = 3.0
    min_nodes: int = 2                     # viewpoints that stand in for a range reading (3 was worse on the tuning seeds)
    unsupported_ttl_s: float = 4.0         # a confirmed track without support this long goes back to tentative
    tentative_ttl_s: float = 2.0           # a tentative track unseen this long is dropped
    confirmed_ttl_s: float = 10.0          # longer bridges more gaps (6 s was worse on the tuning seeds)
    pair_window_s: float = 0.6             # two bearings this close in time may be crossed into a fix
    pending_ttl_s: float = 1.0
    spawn_clearance_m: float = 25.0        # no new track this close to a living one
    beacon_velocity_sigma_mps: float = 1.0
    friend_accel_noise_mps2: float = 3.0   # process noise of a friendly's beacon track
    beacon_trust_s: float = 2.0            # while a friend's last beacon is this recent, sensor readings of it are only absorbed


@dataclass
class Track:
    track_id: str
    state: Vec
    cov: Mat
    born: float
    last_update: float
    update_times: List[float] = field(default_factory=list)
    confirmed: bool = False
    origin: str = ""             # what started it: "radar", "bearings" or "beacon"
    friend_id: Optional[str] = None     # set for a track started by a friendly beacon
    beacon_time: float = -math.inf      # when that drone's last beacon arrived
    range_time: float = -math.inf       # last reading that gave a range
    node_times: Dict[str, float] = field(default_factory=dict)
    unsupported_since: Optional[float] = None

    @property
    def position_sigma(self) -> float:
        return ((self.cov[0][0] + self.cov[1][1]) / 2.0) ** 0.5


class Tracker:
    def __init__(self, config: Optional[TrackerConfig] = None):
        self.config = config or TrackerConfig()
        self.tracks: List[Track] = []
        self.friends: Dict[str, Track] = {}
        self._pending: List[Measurement] = []     # unclaimed bearings that may pair with another sensor's
        self._t: Optional[float] = None
        self._next_id = 1

    def step(self, t: float, measurements: Sequence[Measurement], beacons: Sequence[dict] = ()) -> List[Track]:
        """Advance to `t` with the readings and beacons that arrived; returns the confirmed tracks."""
        self._predict(t)
        for b in beacons:
            self._beacon(t, b)
        leftovers = self._associate(t, measurements)
        self._initiate(t, leftovers)
        self._life_cycle(t)
        return [tr for tr in self.tracks if tr.confirmed]

    def _predict(self, t: float) -> None:
        dt = 0.0 if self._t is None else max(0.0, t - self._t)
        self._t = t
        for tr in self.tracks:
            accel = self.config.friend_accel_noise_mps2 if tr.friend_id else self.config.accel_noise_mps2
            tr.state, tr.cov = predict(tr.state, tr.cov, dt, accel)

    # ------------------------------------------------------------------ beacons
    def _beacon(self, t: float, b: dict) -> None:
        sigma, v_sigma = math.sqrt(b["covariance"][0][0]), self.config.beacon_velocity_sigma_mps
        tr = self.friends.get(b["friend_id"])
        if tr is None:
            cov = identity_like([sigma ** 2, sigma ** 2, v_sigma ** 2, v_sigma ** 2])
            state = [b["position"][0], b["position"][1], b["velocity"][0], b["velocity"][1]]
            tr = self._add(Track(self._new_id(), state, cov, t, t, [t], True, "beacon", b["friend_id"], beacon_time=t))
            self.friends[b["friend_id"]] = tr
            return
        for i, variance in enumerate((sigma ** 2, sigma ** 2, v_sigma ** 2, v_sigma ** 2)):
            value = (b["position"][0], b["position"][1], b["velocity"][0], b["velocity"][1])[i]
            h = [1.0 if k == i else 0.0 for k in range(4)]
            tr.state, tr.cov = scalar_update(tr.state, tr.cov, value - tr.state[i], h, variance)
        tr.last_update = tr.beacon_time = t

    # --------------------------------------------------------------- association
    def _associate(self, t: float, measurements: Sequence[Measurement]) -> List[Measurement]:
        scans: Dict[tuple, List[Measurement]] = {}
        for m in measurements:
            scans.setdefault(m.scan, []).append(m)
        leftovers = []
        for scan in scans.values():
            cost = [[_cost(tr, m) for m in scan] for tr in self.tracks]
            matched = {j for _, j in self._claim(t, scan, cost)}
            leftovers += [m for j, m in enumerate(scan) if j not in matched]
        return leftovers

    def _claim(self, t: float, scan: List[Measurement], cost) -> List[tuple]:
        pairs = assign(cost, BIG_GATE) if self.tracks and scan else []
        for i, j in pairs:
            tr, m = self.tracks[i], scan[j]
            if tr.friend_id is not None and t - tr.beacon_time <= self.config.beacon_trust_s:
                tr.last_update = t          # absorbed: it is the drone, whose beacons know better than a sensor
                continue
            tr.state, tr.cov = apply_measurement(tr.state, tr.cov, m)
            tr.last_update = t
            tr.update_times.append(t)
            tr.node_times[m.node] = t
            if m.kind in RANGE_KINDS:
                tr.range_time = t
        return pairs

    # ---------------------------------------------------------------- initiation
    def _initiate(self, t: float, leftovers: List[Measurement]) -> None:
        self._pending = [p for p in self._pending if t - p.t <= self.config.pending_ttl_s]
        for m in leftovers:
            if m.kind == RANGE_BEARING:
                x, y, cov = fix_from_range_bearing(m)
                self._spawn(t, (x, y), cov, [m], "radar")
            elif m.kind == BEARING:
                self._pair_bearing(t, m)

    def _pair_bearing(self, t: float, m: Measurement) -> None:
        for other in self._pending:
            if other.node == m.node or abs(other.t - m.t) > self.config.pair_window_s:
                continue
            fix = triangulate(other, m)
            if fix is not None:
                self._pending.remove(other)
                self._spawn(t, (fix[0], fix[1]), fix[2], [other, m], "bearings")
                return
        self._pending.append(m)

    def _spawn(self, t: float, xy: tuple, fix_cov: Mat, readings: List[Measurement], origin: str) -> None:
        clearance = max(self.config.spawn_clearance_m, 2.0 * math.sqrt(max(fix_cov[0][0], fix_cov[1][1])))   # a vague fix is not new
        if any(math.hypot(tr.state[0] - xy[0], tr.state[1] - xy[1]) < clearance for tr in self.tracks):
            return
        v2 = self.config.initial_speed_sigma_mps ** 2
        cov = identity_like([0.0, 0.0, v2, v2])
        for i in range(2):
            for j in range(2):
                cov[i][j] = fix_cov[i][j]
        tr = self._add(Track(self._new_id(), [xy[0], xy[1], 0.0, 0.0], cov, t, t, [t] * len(readings), origin=origin))
        tr.node_times = {m.node: t for m in readings}
        if any(m.kind in RANGE_KINDS for m in readings):
            tr.range_time = t

    def _add(self, track: Track) -> Track:
        self.tracks.append(track)
        return track

    def _new_id(self) -> str:
        self._next_id += 1
        return f"T{self._next_id - 1}"

    # ---------------------------------------------------------------- life cycle
    def _life_cycle(self, t: float) -> None:
        keep = []
        for tr in self.tracks:
            if tr.friend_id is None:
                self._confirm_or_demote(tr, t)
            ttl = self.config.confirmed_ttl_s if tr.confirmed else self.config.tentative_ttl_s
            if t - tr.last_update <= ttl:
                keep.append(tr)
            elif tr.friend_id is not None:
                del self.friends[tr.friend_id]
        self.tracks = keep

    def _supported(self, tr: Track, t: float) -> bool:
        window = self.config.support_window_s
        nodes = sum(t - seen <= window for seen in tr.node_times.values())
        return t - tr.range_time <= window or nodes >= self.config.min_nodes

    def _confirm_or_demote(self, tr: Track, t: float) -> None:
        tr.update_times = [u for u in tr.update_times if t - u <= self.config.confirm_window_s]
        supported = self._supported(tr, t)
        if not tr.confirmed:
            ready = len(tr.update_times) >= self.config.confirm_updates
            tr.confirmed = ready and supported and tr.position_sigma < self.config.confirm_max_sigma_m
            return
        if supported:
            tr.unsupported_since = None
        elif tr.unsupported_since is None:
            tr.unsupported_since = t
        elif t - tr.unsupported_since > self.config.unsupported_ttl_s:
            tr.confirmed, tr.update_times, tr.unsupported_since = False, [], None


def _cost(track: Track, m: Measurement) -> float:
    c = gate_cost(track.state, track.cov, m)
    return NO_MATCH if c is None else c
