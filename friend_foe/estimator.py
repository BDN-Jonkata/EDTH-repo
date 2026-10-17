"""Friend/foe estimator: keeps evidence per track and classifies it.

Classes: friendly | hostile | suspicious | unknown.

Evidence is a log-likelihood ratio (llr) of "friendly" vs "not friendly" per
track, p_friendly = sigmoid(llr):

* A fresh friendly beacon consistent with the track pushes llr up (strongly).
* No matching beacon pushes llr down slowly, but only to a floor. Beacons can
  be lost to jamming, so silence alone makes a track suspicious, never hostile.
* Hostile needs positive evidence of hostile behaviour, supplied through the
  `behaviour_llr` hook (the drone-behaviour module). Negative = hostile-like.

Thresholds have hysteresis so classes do not flicker. The class is a
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
    cls: str                        # friendly | hostile | suspicious | unknown
    class_prob: float               # probability of `cls`
    p_friendly: float
    matched_beacon: Optional[str] = None


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
    friendly_enter: float = 0.9
    friendly_exit: float = 0.7
    hostile_enter: float = 0.1
    hostile_exit: float = 0.2
    suspicious_enter: float = 0.3
    suspicious_exit: float = 0.4
    memory_ttl_s: float = 30.0          # forget tracks not seen for this long


def for_scenario(scenario: dict, config: Optional[EstimatorConfig] = None) -> EstimatorConfig:
    """The config with the scenario's beacon rate, which the delivery-rate estimate needs."""
    return replace(config or EstimatorConfig(), beacon_rate_hz=scenario["beacon"]["rate_hz"])


@dataclass
class _Memory:
    llr: float = 0.0
    n_updates: int = 0
    cls: str = "unknown"
    last_t: float = 0.0


def _dist(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


class FriendFoeEstimator:
    def __init__(
        self,
        config: Optional[EstimatorConfig] = None,
        behaviour_llr: Optional[Callable[[TrackState], float]] = None,
    ):
        self.config = config or EstimatorConfig()
        self.behaviour_llr = behaviour_llr
        self._memory: Dict[str, _Memory] = {}
        self._last_t: Optional[float] = None
        # beacons received and expected from friendly tracks, both forgetting over delivery_tau_s
        self._received = self.config.delivery_prior * self.config.delivery_prior_n
        self._expected = self.config.delivery_prior_n

    @property
    def delivery_rate(self) -> float:
        """Share of expected beacons that arrive, measured on tracks currently called friendly."""
        return max(self.config.delivery_min, min(1.0, self._received / self._expected))

    def update(
        self, t: float, tracks: Sequence[TrackState], beacons: Sequence[Beacon]
    ) -> List[Classification]:
        dt = self._frame_dt(t)
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
        cfg = self.config
        mem = self._memory.setdefault(tr.track_id, _Memory())
        if matched is not None:
            mem.llr += cfg.match_step
        elif mem.llr > cfg.no_beacon_floor:
            # silence is weaker evidence on a lossy link, where a friendly's beacons are missing too
            mem.llr = max(mem.llr - cfg.no_beacon_per_s * dt * self.delivery_rate, cfg.no_beacon_floor)
        if self.behaviour_llr is not None:
            mem.llr += self.behaviour_llr(tr)
        mem.llr = max(-cfg.llr_limit, min(cfg.llr_limit, mem.llr))
        mem.n_updates += 1
        mem.last_t = t
        p = 1.0 / (1.0 + math.exp(-mem.llr))
        mem.cls = self._classify(mem, p)
        return Classification(tr.track_id, t, mem.cls, self._class_prob(mem.cls, p), p, matched)

    def _learn_delivery(self, dt: float, found: Sequence[Classification]) -> None:
        cfg = self.config
        forget = math.exp(-dt / cfg.delivery_tau_s)
        friendly = [c for c in found if c.cls == "friendly"]
        self._received = self._received * forget + sum(c.matched_beacon is not None for c in friendly)
        self._expected = self._expected * forget + len(friendly) * cfg.beacon_rate_hz * dt

    def _forget_stale(self, t: float) -> None:
        for k in [k for k, m in self._memory.items() if t - m.last_t > self.config.memory_ttl_s]:
            del self._memory[k]

    def _match(self, t, tracks, beacons) -> Dict[str, str]:
        """One-to-one nearest match of fresh beacons to tracks (greedy)."""
        cfg = self.config
        pairs = []
        for i, tr in enumerate(tracks):
            for j, b in enumerate(beacons):
                age = t - b.t
                if age < -cfg.beacon_clock_tolerance_s or age > cfg.beacon_max_age_s:
                    continue
                age = max(age, 0.0)
                pred = tuple(p + v * age for p, v in zip(b.position, b.velocity))
                gate = max(cfg.gate_min_m, cfg.gate_sigmas * math.hypot(tr.pos_sigma, b.pos_sigma))
                d = _dist(tr.position, pred)
                if d <= gate:
                    pairs.append((d, i, j))
        pairs.sort()
        used_t, used_b, result = set(), set(), {}
        for _, i, j in pairs:
            if i in used_t or j in used_b:
                continue
            used_t.add(i)
            used_b.add(j)
            result[tracks[i].track_id] = beacons[j].friend_id
        return result

    def _classify(self, mem: _Memory, p: float) -> str:
        cfg = self.config
        if mem.n_updates < cfg.min_updates:
            return "unknown"
        prev = mem.cls
        if p >= (cfg.friendly_exit if prev == "friendly" else cfg.friendly_enter):
            return "friendly"
        if p <= (cfg.hostile_exit if prev == "hostile" else cfg.hostile_enter):
            return "hostile"
        if p <= (cfg.suspicious_exit if prev == "suspicious" else cfg.suspicious_enter):
            return "suspicious"
        return "unknown"

    @staticmethod
    def _class_prob(cls: str, p: float) -> float:
        if cls == "friendly":
            return p
        if cls in ("hostile", "suspicious"):
            return 1.0 - p
        return max(p, 1.0 - p)
