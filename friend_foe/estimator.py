"""Friend/foe estimator: keeps evidence per track and classifies it.

Classes: friendly | hostile | suspicious | peaceful | unknown (meanings in
docs/data-formats.md). Two separate kinds of evidence, both log-likelihood ratios:

Beacon axis, "friendly" vs "not friendly", p_friendly = sigmoid(llr):
* A fresh friendly beacon consistent with the track pushes llr up (strongly).
* No matching beacon pushes llr down slowly, but only to a floor, and less on a
  lossy link. Beacons can be lost to jamming, so silence alone makes a track
  suspicious, never hostile and never peaceful.

Behaviour axis, "hostile" vs "peaceful", p_hostile = sigmoid(threat):
* Only the `threat_llr` hook moves it (the drone-behaviour module): positive =
  hostile-like, negative = peaceful-like. It forgets over `threat_tau_s`, so a
  track that changes behaviour changes class. Hostile and peaceful both need
  this positive evidence; without a hook neither ever appears.

A beacon match is primary: a friendly stays friendly whatever its behaviour looks
like. Otherwise hostile or peaceful (from behaviour) wins over suspicious (from
silence). Thresholds have hysteresis so classes do not flicker. The class is a
presumption with a probability, never a hard delete.

Inputs are plain dataclasses that mirror the draft `LocalTrack` and
`FriendlyBeacon` messages; swap in the `common/` schemas once they exist.
"""

import math
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, List, Optional, Sequence, Tuple

Vec3 = Tuple[float, float, float]


@dataclass(frozen=True)
class TrackState:
    track_id: str
    t: float
    position: Vec3
    velocity: Vec3 = (0.0, 0.0, 0.0)
    pos_sigma: float = 1.0          # 1-sigma position uncertainty, m
    existence_prob: float = 1.0
    observed_t: Optional[float] = None  # optional internal freshness metadata; coasting is not a new observation


@dataclass(frozen=True)
class Beacon:
    friend_id: str
    t: float                        # time the beacon was sent
    position: Vec3
    velocity: Vec3 = (0.0, 0.0, 0.0)
    pos_sigma: float = 1.0


@dataclass(frozen=True)
class Classification:
    track_id: str
    t: float
    cls: str                        # friendly | hostile | suspicious | peaceful | unknown
    class_prob: float               # probability of `cls`
    p_friendly: float               # beacon axis
    matched_beacon: Optional[str] = None
    p_hostile: float = 0.5          # behaviour axis; 0.5 = no behaviour evidence


@dataclass
class EstimatorConfig:
    beacon_max_age_s: float = 2.0       # older beacons are ignored
    beacon_clock_tolerance_s: float = 0.5   # a beacon stamped this far in the future is a clock offset, not an error
    gate_sigmas: float = 3.0            # gate size in combined sigmas
    gate_min_m: float = 5.0             # gate never smaller than this
    min_existence: float = 0.3          # ignore weaker tracks
    min_updates: int = 5                # updates before leaving `unknown`
    match_step: float = 1.0             # llr gain per matched beacon
    no_beacon_per_s: float = 0.2        # llr lost per second of silence on a perfect link; scaled by the delivery rate
    no_beacon_floor: float = -1.5       # silence alone never goes below this
    beacon_rate_hz: float = 2.0         # how often each friendly broadcasts (scenario `beacon.rate_hz`)
    delivery_prior: float = 0.8         # assumed share of beacons that arrive, until measured
    delivery_prior_n: float = 10.0      # how many expected beacons the prior is worth
    delivery_tau_s: float = 30.0        # the measured delivery rate forgets over this time
    delivery_min: float = 0.05
    max_dt_s: float = 2.0               # a longer gap between updates counts as this much silence
    llr_limit: float = 4.0              # evidence is clipped to +/- this
    friendly_enter: float = 0.9         # on p_friendly
    friendly_exit: float = 0.7
    suspicious_enter: float = 0.3       # on p_friendly: low means not friendly
    suspicious_exit: float = 0.4
    suspicious_requires_behavior: bool = False  # beacon-only baseline compatibility; automatic pipeline enables this
    suspicious_threat_enter: float = 0.65
    suspicious_threat_exit: float = 0.55
    hostile_enter: float = 0.9          # on p_hostile (behaviour axis)
    hostile_exit: float = 0.7
    peaceful_enter: float = 0.1         # on p_hostile: low means peaceful-like
    peaceful_exit: float = 0.3
    threat_tau_s: float = 20.0          # behaviour evidence forgets over this time, so a change shows
    memory_ttl_s: float = 30.0          # forget tracks not seen for this long


def for_scenario(scenario: dict, config: Optional[EstimatorConfig] = None) -> EstimatorConfig:
    """The config with the scenario's beacon rate, which the delivery-rate estimate needs."""
    return replace(config or EstimatorConfig(), beacon_rate_hz=scenario["beacon"]["rate_hz"])


@dataclass
class _Memory:
    llr: float = 0.0                # beacon axis
    threat: float = 0.0             # behaviour axis, positive = hostile-like
    n_updates: int = 0
    cls: str = "unknown"
    last_t: float = 0.0


def _sigmoid(llr: float) -> float:
    return 1.0 / (1.0 + math.exp(-llr))


def _dist(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


class FriendFoeEstimator:
    def __init__(
        self,
        config: Optional[EstimatorConfig] = None,
        threat_llr: Optional[Callable[[TrackState], float]] = None,
    ):
        self.config = config or EstimatorConfig()
        self.threat_llr = threat_llr   # per update: > 0 hostile-like, < 0 peaceful-like
        self._memory: Dict[str, _Memory] = {}
        self._last_t: Optional[float] = None
        self._seen_beacons = {}
        self._fresh_matches = set()
        # beacons received and expected from friendly tracks, both forgetting over delivery_tau_s
        self._received = self.config.delivery_prior * self.config.delivery_prior_n
        self._expected = self.config.delivery_prior_n

    @property
    def delivery_rate(self) -> float:
        """Share of expected beacons that arrive, measured on tracks currently called friendly."""
        return max(self.config.delivery_min, min(1.0, self._received / self._expected))

    def register_identity(self, track_id: str, t: float = 0.0) -> None:
        """An already verified fleet identity from the preflight roster sync.

        This is identity evidence, never a result of a similar flight pattern.
        Subsequent silence uses the same loss-aware confidence rules as beacons.
        """
        self._memory[track_id] = _Memory(llr=self.config.llr_limit, n_updates=self.config.min_updates,
                                        cls="friendly", last_t=t)

    def update(
        self, t: float, tracks: Sequence[TrackState], beacons: Sequence[Beacon]
    ) -> List[Classification]:
        dt = self._frame_dt(t)
        self._forget_stale(t)  # a reappearing/reused ID must not revive expired evidence
        usable = [tr for tr in tracks if tr.existence_prob >= self.config.min_existence]
        matches = self._match(t, usable, beacons)
        out = [self._update_track(t, dt, tr, matches.get(tr.track_id)) for tr in usable]
        self._learn_delivery(dt, out)
        self._forget_stale(t)
        self._last_t = t
        return out

    def _frame_dt(self, t: float) -> float:
        if self._last_t is None:
            return 0.5   # nominal tracker period for the first update
        return max(0.0, min(t - self._last_t, self.config.max_dt_s))

    def _update_track(self, t: float, dt: float, tr: TrackState, matched: Optional[str]) -> Classification:
        mem = self._memory.setdefault(tr.track_id, _Memory())
        if mem.n_updates:
            dt = max(0.0, min(t - mem.last_t, self.config.max_dt_s))
        self._beacon_evidence(mem, dt, matched, tr.track_id in self._fresh_matches)
        self._behaviour_evidence(mem, dt, tr)
        mem.n_updates += 1
        mem.last_t = t
        p, q = _sigmoid(mem.llr), _sigmoid(mem.threat)
        mem.cls = self._classify(mem, p, q)
        return Classification(tr.track_id, t, mem.cls, self._class_prob(mem.cls, p, q), p, matched, q)

    def _beacon_evidence(self, mem: _Memory, dt: float, matched: Optional[str], fresh: bool = True) -> None:
        cfg = self.config
        if matched is not None and fresh:
            mem.llr += cfg.match_step
        elif matched is None and mem.llr > cfg.no_beacon_floor:
            # silence is weaker evidence on a lossy link, where a friendly's beacons are missing too
            mem.llr = max(mem.llr - cfg.no_beacon_per_s * dt * self.delivery_rate, cfg.no_beacon_floor)
        mem.llr = max(-cfg.llr_limit, min(cfg.llr_limit, mem.llr))

    def _behaviour_evidence(self, mem: _Memory, dt: float, tr: TrackState) -> None:
        cfg = self.config
        mem.threat *= math.exp(-dt / cfg.threat_tau_s)
        if self.threat_llr is not None:
            mem.threat += self.threat_llr(tr)
        mem.threat = max(-cfg.llr_limit, min(cfg.llr_limit, mem.threat))

    def _learn_delivery(self, dt: float, found: Sequence[Classification]) -> None:
        cfg = self.config
        forget = math.exp(-dt / cfg.delivery_tau_s)
        friendly = [c for c in found if c.cls == "friendly"]
        self._received = self._received * forget + sum(c.track_id in self._fresh_matches for c in friendly)
        self._expected = self._expected * forget + len(friendly) * cfg.beacon_rate_hz * dt

    def _forget_stale(self, t: float) -> None:
        for k in [k for k, m in self._memory.items() if t - m.last_t > self.config.memory_ttl_s]:
            del self._memory[k]

    def _match(self, t, tracks, beacons) -> Dict[str, str]:
        """One-to-one nearest match of fresh beacons to tracks (greedy)."""
        cfg = self.config
        self._fresh_matches = set()
        self._seen_beacons = {key: seen for key, seen in self._seen_beacons.items()
                              if t - seen <= cfg.memory_ttl_s}
        pairs = []
        newest = {}
        for b in beacons:
            if -cfg.beacon_clock_tolerance_s <= t - b.t <= cfg.beacon_max_age_s:
                newest[b.friend_id] = max(newest.get(b.friend_id, -math.inf), b.t)
        for i, tr in enumerate(tracks):
            for j, b in enumerate(beacons):
                age = t - b.t
                if age < -cfg.beacon_clock_tolerance_s or age > cfg.beacon_max_age_s:
                    continue
                if b.t != newest[b.friend_id]:
                    continue
                age = max(age, 0.0)
                pred = tuple(p + v * age for p, v in zip(b.position, b.velocity))
                gate = max(cfg.gate_min_m, cfg.gate_sigmas * math.hypot(tr.pos_sigma, b.pos_sigma))
                d = _dist(tr.position, pred)
                if d <= gate:
                    pairs.append((d, i, j))
        pairs.sort()
        used_t, used_b, used_f, result = set(), set(), set(), {}
        for _, i, j in pairs:
            if i in used_t or j in used_b or beacons[j].friend_id in used_f:
                continue
            used_t.add(i)
            used_b.add(j)
            used_f.add(beacons[j].friend_id)
            result[tracks[i].track_id] = beacons[j].friend_id
            key = (beacons[j].friend_id, beacons[j].t)
            if key not in self._seen_beacons:
                self._fresh_matches.add(tracks[i].track_id)
                self._seen_beacons[key] = t
        return result

    def _classify(self, mem: _Memory, p: float, q: float) -> str:
        """p = p_friendly (beacon axis), q = p_hostile (behaviour axis)."""
        cfg = self.config
        if mem.n_updates < cfg.min_updates:
            return "unknown"
        prev = mem.cls
        if p >= (cfg.friendly_exit if prev == "friendly" else cfg.friendly_enter):
            return "friendly"
        if q >= (cfg.hostile_exit if prev == "hostile" else cfg.hostile_enter):
            return "hostile"
        if q <= (cfg.peaceful_exit if prev == "peaceful" else cfg.peaceful_enter):
            return "peaceful"
        risk_supported = (not cfg.suspicious_requires_behavior or
                          q >= (cfg.suspicious_threat_exit if prev == "suspicious" else cfg.suspicious_threat_enter))
        if risk_supported and p <= (cfg.suspicious_exit if prev == "suspicious" else cfg.suspicious_enter):
            return "suspicious"
        return "unknown"

    def _class_prob(self, cls: str, p: float, q: float) -> float:
        if cls == "friendly":
            return p
        if cls == "hostile":
            return q
        if cls == "peaceful":
            return 1.0 - q
        if cls == "suspicious":
            return q if self.config.suspicious_requires_behavior else 1.0 - p
        return max(p, 1.0 - p)
