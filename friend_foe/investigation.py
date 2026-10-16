"""Trigger for investigating suspicious tracks.

Raises an `InvestigationRequest` (draft schema in docs/system-design.md) when
a track has stayed `suspicious` long enough. The request carries the
weather-based standoff distance. Choosing the drone and flying it is the
drone-behaviour module's job; this only decides when to ask and how close.

Rules: only suspicious tracks are requested (not confirmed hostiles), one
request per track at a time, and a cooldown before asking again.
"""

from typing import Dict, Iterable, List, Optional, Sequence

from friend_foe.estimator import Classification, TrackState
from sensors.quality import SENSOR_SPECS, best_standoff, standoff_by_sensor
from sensors.weather import WeatherProvider

ACTIVE_STATES = {"assigned", "en_route", "on_station"}
FINISHED_STATES = {"done", "aborted"}


class InvestigationTrigger:
    def __init__(
        self,
        weather: WeatherProvider,
        sensor_types: Optional[Iterable[str]] = None,
        min_suspicious_s: float = 3.0,
        cooldown_s: float = 30.0,
        source_id: str = "estimator",
    ):
        self.weather = weather
        self.sensor_types = list(sensor_types) if sensor_types is not None else list(SENSOR_SPECS)
        self.min_suspicious_s = min_suspicious_s
        self.cooldown_s = cooldown_s
        self.source_id = source_id
        self._suspicious_since: Dict[str, float] = {}
        self._blocked_until: Dict[str, float] = {}
        self._seq = 0

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
        by_sensor = standoff_by_sensor(self.sensor_types, tr.position, t, self.weather)
        best = best_standoff(by_sensor)
        var = tr.pos_sigma ** 2
        self._seq += 1
        return {
            "type": "investigation_request",
            "header": {
                "msg_id": f"{self.source_id}-{self._seq}",
                "source_id": self.source_id,
                "t_sent": t,
                "seq": self._seq,
                "schema_version": 1,
            },
            "track_id": c.track_id,
            "position": list(tr.position),
            "covariance": [[var, 0, 0], [0, var, 0], [0, 0, var]],
            "class_prob": c.class_prob,
            "priority": round(1.0 - c.p_friendly, 3),
            "t_requested": t,
            "standoff_m": best.recommended_m,
            "standoff_by_sensor": {
                s: {
                    "max_range_m": v.max_range_m,
                    "recommended_m": v.recommended_m,
                    "confidence": v.confidence,
                    "feasible": v.feasible,
                }
                for s, v in by_sensor.items()
            },
            "weather_confidence": best.confidence,
            "feasible": best.feasible,
        }
