"""Trigger for investigating suspicious tracks.

Raises an `InvestigationRequest` (see docs/data-formats.md) when a track has
stayed `suspicious` long enough. The request carries, for every sensor module
a drone may carry, how close it must get to identify the object in the current
weather. Choosing the drone and flying it is the drone-behaviour module's job;
this only decides when to ask and how close.

Rules: only suspicious tracks are requested (not confirmed hostiles), one
request per track at a time, and a cooldown before asking again.
"""

from typing import Dict, Iterable, List, Optional, Sequence

from common.codec import Sequencer
from friend_foe.estimator import Classification, TrackState
from sensors.quality import best_standoff, detection_modules, load_modules, standoff_by_module
from sensors.weather import WeatherProvider

ACTIVE_STATES = {"assigned", "en_route", "on_station"}
FINISHED_STATES = {"done", "aborted"}


class InvestigationTrigger:
    def __init__(
        self,
        weather: WeatherProvider,
        modules: Optional[Iterable[dict]] = None,
        min_suspicious_s: float = 3.0,
        cooldown_s: float = 30.0,
        source_id: str = "estimator",
    ):
        self.weather = weather
        self.modules = detection_modules(modules if modules is not None else load_modules().values())
        self.min_suspicious_s = min_suspicious_s
        self.cooldown_s = cooldown_s
        self._sequencer = Sequencer(source_id)
        self._suspicious_since: Dict[str, float] = {}
        self._blocked_until: Dict[str, float] = {}

    def update(
        self, t: float, classifications: Sequence[Classification], tracks: Sequence[TrackState]
    ) -> List[dict]:
        by_id = {tr.track_id: tr for tr in tracks}
        requests = []
        for c in classifications:
            if c.cls != "suspicious":
                self._suspicious_since.pop(c.track_id, None)
                continue
            since = self._suspicious_since.setdefault(c.track_id, t)
            if t - since < self.min_suspicious_s or t < self._blocked_until.get(c.track_id, -1.0):
                continue
            tr = by_id.get(c.track_id)
            if tr is None:
                continue
            requests.append(self._build_request(t, c, tr))
            self._blocked_until[c.track_id] = t + self.cooldown_s
        return requests

    def on_status(self, status: dict, t: float) -> None:
        """Feed back `InvestigationStatus` so we do not re-ask while a drone is on it."""
        track_id, state = status["track_id"], status["state"]
        if state in ACTIVE_STATES:
            self._blocked_until[track_id] = float("inf")
        elif state in FINISHED_STATES:
            self._blocked_until[track_id] = t + self.cooldown_s

    def _build_request(self, t: float, c: Classification, tr: TrackState) -> dict:
        by_module = standoff_by_module(self.modules, tr.position, t, self.weather)
        best = best_standoff(by_module)
        var = tr.pos_sigma ** 2
        return {
            "type": "investigation_request",
            "header": self._sequencer.header(t),
            "track_id": c.track_id,
            "position": list(tr.position),
            "covariance": [[var, 0, 0], [0, var, 0], [0, 0, var]],
            "class_prob": c.class_prob,
            "priority": round(1.0 - c.p_friendly, 3),
            "t_requested": t,
            "standoff_m": best.recommended_m,
            "standoff_by_module": {
                module_id: {
                    "max_range_m": s.max_range_m,
                    "recommended_m": s.recommended_m,
                    "confidence": s.confidence,
                    "feasible": s.feasible,
                }
                for module_id, s in by_module.items()
            },
            "weather_confidence": best.confidence,
            "feasible": best.feasible,
        }
