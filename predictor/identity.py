"""Identity keeper: a track that was lost and starts again where it was heading gets its old ID back.

Most ID swaps in the pipeline are not two targets trading places but re-acquisitions: a confirmed track is
dropped after a gap (nothing sees the target for 10 s) and a new track, with a new ID, starts later. The
keeper remembers each lost track's last state and extrapolates it with constant velocity (the short-horizon
predictor of docs/system-design.md 5.6). A new confirmed track that falls inside the growing gate of a lost
one takes over its ID. Friend tracks are not touched: a friend's ID is its beacon's.

It works on tracker output only, so it needs no truth and no change inside the tracker.
"""

import math
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Sequence

from tracker.tracker import Track


@dataclass
class IdentityConfig:
    max_gap_s: float = 30.0         # a lost track is forgotten after this long
    accel_noise_mps2: float = 3.0   # how much the target may have manoeuvred while unseen
    gate_sigmas: float = 3.0
    min_gate_m: float = 20.0
    max_gate_m: float = 120.0       # a wide gate would hand one target's ID to another
    max_speed_change_mps: float = 10.0


@dataclass
class Lost:
    stable_id: str
    t: float
    x: float
    y: float
    vx: float
    vy: float
    sigma: float


class IdentityKeeper:
    def __init__(self, config: Optional[IdentityConfig] = None):
        self.config = config or IdentityConfig()
        self._stable: Dict[str, str] = {}      # tracker's track id -> the id shown
        self._live: Dict[str, Track] = {}      # confirmed non-friend tracks seen last step, by tracker id
        self._lost: List[Lost] = []

    def step(self, t: float, tracks: Sequence[Track]) -> List[Track]:
        """The confirmed tracks with their IDs replaced by the stable ones."""
        current = {tr.track_id: tr for tr in tracks if tr.friend_id is None}
        self._retire(t, current)
        back = {self._stable[i] for i in current if i in self._stable}      # confirmed again under its own ID
        self._lost = [lo for lo in self._lost if lo.stable_id not in back]
        new = [tr for tr in current.values() if tr.track_id not in self._stable]
        self._reclaim(t, new)
        for tr in new:
            self._stable.setdefault(tr.track_id, tr.track_id)
        self._live = current
        return [tr if tr.friend_id is not None else replace(tr, track_id=self._stable[tr.track_id]) for tr in tracks]

    def _retire(self, t: float, current: Dict[str, Track]) -> None:
        for track_id, tr in self._live.items():
            if track_id not in current:
                x, y, vx, vy = tr.state
                self._lost.append(Lost(self._stable[track_id], t, x, y, vx, vy, tr.position_sigma))
        self._lost = [lo for lo in self._lost if t - lo.t <= self.config.max_gap_s]

    def _reclaim(self, t: float, new: List[Track]) -> None:
        """Hand each new track the nearest lost track's ID, nearest pairs first, each ID once."""
        pairs = [(d, tr, lo) for tr in new for lo in self._lost for d in [self._fit(t, tr, lo)] if d is not None]
        taken = set()
        for _, tr, lo in sorted(pairs, key=lambda p: p[0]):
            if tr.track_id in self._stable or lo.stable_id in taken:
                continue
            self._stable[tr.track_id] = lo.stable_id
            taken.add(lo.stable_id)
        self._lost = [lo for lo in self._lost if lo.stable_id not in taken]

    def _fit(self, t: float, tr: Track, lo: Lost) -> Optional[float]:
        """Distance between the new track and where the lost one should be, or None if it cannot be it."""
        cfg, dt = self.config, t - lo.t
        px, py = lo.x + lo.vx * dt, lo.y + lo.vy * dt
        spread = math.hypot(lo.sigma, 0.5 * cfg.accel_noise_mps2 * dt * dt)
        gate = min(cfg.max_gate_m, max(cfg.min_gate_m, cfg.gate_sigmas * math.hypot(spread, tr.position_sigma)))
        d = math.hypot(tr.state[0] - px, tr.state[1] - py)
        dv = math.hypot(tr.state[2] - lo.vx, tr.state[3] - lo.vy)
        return d if d <= gate and dv <= cfg.max_speed_change_mps else None
