"""Identification from what a track's own readings are, not from how it moves.

Steady flight looks the same for a hostile and a harmless object, so motion alone cannot say which it is. An RF
receiver can: it only hears something that transmits, and the birds and vehicles of a scenario do not. A track that is
not a friendly (the beacons decide that) and that RF receivers keep hearing is an unknown emitter in the defended
area, and is called `hostile`. A hostile that stays silent is not caught by this (it stays whatever the estimator says).

One receiver gives only a bearing, and any track on that line could take the reading (a bird behind a hostile would
be called hostile too). So the bearings of two different receivers are crossed into a fix (`models.triangulate`), and
the fix is given to the one track that it agrees with best, if any (a Mahalanobis gate with the fix's own
uncertainty). A fix nearest a friendly's track is the friendly's radio and gives nothing. A track needs several fixes
in a few seconds before it is called.

Uses only the delivered readings and the tracker's tracks, so it needs no truth and no change to the tracker.
"""

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from tracker.ekf import innovation_variance
from tracker.measurement import BEARING, Measurement
from tracker.models import triangulate
from tracker.tracker import Track

RF_KIND = "rf_receiver"
GATE_CHI2 = 9.21           # 2 degrees of freedom, 99 %


@dataclass
class IdentifyConfig:
    min_fixes: int = 3          # fixes on the track within `window_s` (assumed)
    window_s: float = 6.0
    pair_s: float = 0.3         # two receivers' bearings this close in time cross into one fix
    keep_s: float = 1.0         # how long a bearing waits for the other receiver's


class Emitters:
    def __init__(self, config: Optional[IdentifyConfig] = None):
        self.config = config or IdentifyConfig()
        self._recent: List[Measurement] = []
        self._heard: Dict[str, List[float]] = {}        # track id -> times of the fixes that landed on it

    def step(self, t: float, readings: Sequence[Measurement], tracks: Sequence[Track]) -> None:
        rf = [m for m in readings if m.sensor_kind == RF_KIND and m.kind == BEARING]
        for m in rf:
            for other in self._recent:
                if other.node != m.node and abs(other.t - m.t) <= self.config.pair_s:
                    self._land(t, triangulate(other, m), tracks)
        self._recent = [m for m in self._recent + rf if t - m.t <= self.config.keep_s]
        self._heard = {k: [u for u in v if t - u <= self.config.window_s] for k, v in self._heard.items()}
        self._heard = {k: v for k, v in self._heard.items() if v}

    def _land(self, t: float, fix, tracks: Sequence[Track]) -> None:
        """Give the fix to the track it agrees with best, unless that is a friendly's."""
        if fix is None:
            return
        x, y, cov = fix
        best, best_d2 = None, GATE_CHI2
        for tr in tracks:
            d2 = _distance2(tr, x, y, cov)
            if d2 <= best_d2:
                best, best_d2 = tr, d2
        if best is not None and best.friend_id is None:
            self._heard.setdefault(best.track_id, []).append(t)

    def label(self, track_id: str, t: float) -> Optional[str]:
        """`hostile` for a track that fixes of RF bearings have recently landed on, else None (no opinion)."""
        recent = [u for u in self._heard.get(track_id, ()) if t - u <= self.config.window_s]
        return "hostile" if len(recent) >= self.config.min_fixes else None


def _distance2(track: Track, x: float, y: float, cov) -> float:
    """Squared Mahalanobis distance between a fix and a track's position, with both uncertainties."""
    dx, dy = track.state[0] - x, track.state[1] - y
    s00, s01, s11 = track.cov[0][0] + cov[0][0], track.cov[0][1] + cov[0][1], track.cov[1][1] + cov[1][1]
    det = s00 * s11 - s01 * s01
    return math.inf if det <= 0 else (s11 * dx * dx - 2.0 * s01 * dx * dy + s00 * dy * dy) / det
