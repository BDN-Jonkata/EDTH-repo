"""Cueing: whatever a node sees that is not a friend is handed at once to the drone best placed to identify it.

Two things are handed off, the moment they are seen, not after a track has been classified suspicious (that
takes several seconds of beacon silence):

* a new confirmed track that is not a friend: its position is known, so the closest free drone, the one that
  saw it if that is the closest, flies to a standoff from it and follows it (a normal investigation task);
* repeated bearings that no confirmed track or friend explains (a target seen by one node with a bearing, about
  a fifth of the time a hostile is present): a point `cue_distance_m` along the bearing stands in for the
  position, and the closest free drone, again including the one that saw it, goes to look.

Either way the data the first node recorded tells the best-placed drone where to look. Assumptions: a bearing
has no range, so the point along it is a guess; ground sensors are fixed (the simulation has no pointing
command for them), so they help only through their own readings, which cross the cue anyway.
"""

import math
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Sequence, Tuple

from tracker.measurement import BEARING, Measurement


@dataclass
class CueConfig:
    window_s: float = 2.0             # bearings this recent count together
    min_hits: int = 3                 # unexplained bearings of one sensor needed for a cue
    direction_spread_deg: float = 8.0
    explain_margin_deg: float = 3.0   # a track within this many degrees beyond the sigma explains a bearing
    cue_distance_m: float = 150.0     # a bearing has no range: look this far along it
    cooldown_s: float = 20.0          # no second cue near the same point this soon
    same_place_m: float = 120.0
    track_min_age_s: float = 2.0      # a confirmed non-friend track this old is handed off
    track_max_sigma_m: float = 40.0   # and only if its position is known well enough to fly to


@dataclass
class Cue:
    xy: Tuple[float, float]
    node: str = ""                    # the node whose bearings made it (a bearing cue)
    track_id: str = ""                # the track it is about (a track hand-off)


def explained(m: Measurement, tracks: Sequence, margin_deg: float) -> bool:
    """True if some confirmed track (a friendly drone's included) lies along the bearing, within its reach."""
    allowed = 3.0 * m.sigma_bearing + math.radians(margin_deg)
    for tr in tracks:
        dx, dy = tr.state[0] - m.pose.x, tr.state[1] - m.pose.y
        if math.hypot(dx, dy) > m.max_range_m:
            continue
        off = math.atan2(math.sin(math.atan2(dy, dx) - m.bearing), math.cos(math.atan2(dy, dx) - m.bearing))
        if abs(off) <= allowed:
            return True
    return False


class Cueing:
    def __init__(self, config: CueConfig = None):
        self.config = config or CueConfig()
        self._hits: Dict[Tuple[str, str], Deque[Tuple[float, float, Measurement]]] = {}
        self._recent: List[Tuple[float, Tuple[float, float]]] = []
        self._handed_off: set = set()

    def step(self, t: float, readings: Sequence[Measurement], tracks: Sequence) -> List[Cue]:
        """The new cues this step: new non-friend tracks, and bearings nothing explains."""
        return self._track_cues(t, tracks) + self._bearing_cues(t, readings, tracks)

    def retry(self, track_id: str) -> None:
        self._handed_off.discard(track_id)

    def _track_cues(self, t: float, tracks: Sequence) -> List[Cue]:
        cfg, cues = self.config, []
        for tr in tracks:
            if (tr.friend_id is None and tr.track_id not in self._handed_off and t - tr.born >= cfg.track_min_age_s
                    and tr.position_sigma <= cfg.track_max_sigma_m):
                self._handed_off.add(tr.track_id)
                cues.append(Cue((tr.state[0], tr.state[1]), track_id=tr.track_id))
        return cues

    def _bearing_cues(self, t: float, readings: Sequence[Measurement], tracks: Sequence) -> List[Cue]:
        cfg = self.config
        for m in readings:
            if m.kind == BEARING and not explained(m, tracks, cfg.explain_margin_deg):
                self._hits.setdefault((m.node, m.sensor_id), deque()).append((t, m.bearing, m))
        cues = []
        for key, hits in list(self._hits.items()):
            while hits and t - hits[0][0] > cfg.window_s:
                hits.popleft()
            cue = self._cue_from(t, hits) if len(hits) >= cfg.min_hits else None
            if cue is not None:
                cues.append(Cue(cue, node=key[0]))
                hits.clear()
        return cues

    def _cue_from(self, t: float, hits) -> Tuple[float, float]:
        bearings = [b for _, b, _ in hits]
        mean = math.atan2(sum(math.sin(b) for b in bearings), sum(math.cos(b) for b in bearings))
        spread = max(abs(math.atan2(math.sin(b - mean), math.cos(b - mean))) for b in bearings)
        if math.degrees(spread) > self.config.direction_spread_deg:
            return None
        pose = hits[-1][2].pose
        point = (pose.x + self.config.cue_distance_m * math.cos(mean), pose.y + self.config.cue_distance_m * math.sin(mean))
        self._recent = [(when, p) for when, p in self._recent if t - when <= self.config.cooldown_s]
        if any(math.hypot(point[0] - p[0], point[1] - p[1]) < self.config.same_place_m for _, p in self._recent):
            return None
        self._recent.append((t, point))
        return point
