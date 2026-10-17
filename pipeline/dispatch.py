"""Turn investigation requests into drone flights, and drone progress into investigation statuses.

A stand-in for the drone-behaviour module's dispatch (the viewer has the full version in
`ui/viewer/investigations.js`), simple on purpose: the closest free drone that carries a module the request
calls feasible flies to a point at the request's standoff distance from the track, facing it, stays there
for `dwell_s`, and flies back. At most `max_active` investigations run at once. If the track disappears for
`lost_s` the investigation is aborted. Not modelled: mutual separation, RF needing an observed emitter,
command loss, and the identification itself (the estimator does not read camera class hints yet), so this
shows the effect of the extra viewpoint on tracking, not of identification.
"""

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from common.codec import Sequencer
from friend_foe.estimator import Classification, TrackState
from friend_foe.investigation import InvestigationTrigger
from pipeline.cueing import Cueing
from pipeline.fleet import Fleet
from sensors.quality import modules_in_scenario
from sensors.weather import weather_from_scenario

SAFE_STANDOFF_M = 40.0       # never closer than this to an uncontrolled object (as in the viewer)
ON_STATION_MARGIN = 1.15
HARMLESS = ("friendly", "peaceful")    # classes that need no drone
CUE_STANDOFF_M = 80.0       # an assumption: close enough for a camera or radar, far enough not to be in the way
OWN_TRACK_RADIUS_M = 15.0   # a track this close to the drone is probably the drone itself


@dataclass
class Task:
    track_id: str
    drone: str
    standoff_m: float
    t_assigned: float
    state: str = "assigned"
    t_station: Optional[float] = None
    t_last_seen: float = 0.0
    last_xy: Tuple[float, float] = (0.0, 0.0)
    cue: bool = False               # sent at a bearing with no track behind it: there is nothing to lose sight of


@dataclass
class Eligibility:
    """Which tracks are worth a drone. Ghost tracks and friendlies that lost their beacons were 43 % and 11 % of
    the first dispatches, and a drone off its patrol covers nothing else."""
    enabled: bool = True
    min_age_s: float = 4.0           # a track that just appeared may be a fluke
    max_coast_s: float = 2.0         # not one that nobody has updated lately (a guess at where it was)
    max_sigma_m: float = 25.0        # position known well enough to fly to
    min_speed_mps: float = 1.5       # a still "object" is most often a ghost or a fixed return

    def allows(self, track, t: float) -> bool:
        if not self.enabled:
            return True
        speed = math.hypot(track.state[2], track.state[3])
        return (t - track.born >= self.min_age_s and t - track.last_update <= self.max_coast_s
                and track.position_sigma <= self.max_sigma_m and speed >= self.min_speed_mps)


class Investigator:
    """The trigger and the dispatcher together: classifications in, drone flights out, statuses fed back."""

    def __init__(self, scenario: dict, fleet: Fleet, sequencers: Dict[str, Sequencer],
                 eligibility: Optional[Eligibility] = None, cueing: Optional[Cueing] = None, **dispatch_options):
        self.trigger = InvestigationTrigger(weather_from_scenario(scenario), modules_in_scenario(scenario))
        self.dispatcher = Dispatcher(fleet, scenario, sequencers, **dispatch_options)
        self.eligibility = eligibility or Eligibility()
        self.cueing = cueing
        self._classes: Dict[str, Classification] = {}

    def on_readings(self, t: float, readings: list, tracks: list) -> None:
        """Bearings no track explains become cues for the closest other drone."""
        if self.cueing is not None:
            for cue in self._by_risk(self.cueing.step(t, readings, tracks)):
                if not self.dispatcher.cue(t, cue.xy, cue.track_id) and cue.track_id:
                    self.cueing.retry(cue.track_id)         # no drone was free: ask again next time

    def on_classification(self, t: float, classifications: List[Classification], states: List[TrackState],
                          tracks: Optional[Dict[str, object]] = None) -> None:
        """`tracks` maps track ids to the tracker's `Track`s, used to leave out tracks that are not worth a drone."""
        self._classes = {c.track_id: c for c in classifications}
        if tracks is not None:
            classifications = [c for c in classifications if c.track_id in tracks and self.eligibility.allows(tracks[c.track_id], t)]
        requests = self.trigger.update(t, classifications, states)
        self._feed_back(t, self.dispatcher.handle(t, requests))

    def _by_risk(self, cues: list) -> list:
        """The estimator's view of the tracks decides which cues get a drone first: a track already known to be
        friendly or peaceful gets none, and the likeliest hostile goes first (there are few drones)."""
        known = [c for c in cues if not c.track_id or getattr(self._classes.get(c.track_id), "cls", None) not in HARMLESS]
        return sorted(known, key=lambda c: -(getattr(self._classes.get(c.track_id), "p_hostile", 0.0) if c.track_id else 0.0))

    def step(self, t: float, tracks: Dict[str, Tuple[float, float]]) -> None:
        self._feed_back(t, self.dispatcher.step(t, tracks))

    def _feed_back(self, t: float, statuses: List[dict]) -> None:
        for s in statuses:
            if not s["track_id"].startswith("cue-"):
                self.trigger.on_status(s, t)

    @property
    def stats(self) -> Dict[str, int]:
        return self.dispatcher.stats


class Dispatcher:
    def __init__(self, fleet: Fleet, scenario: dict, sequencers: Dict[str, Sequencer],
                 max_active: int = 2, dwell_s: float = 6.0, lost_s: float = 10.0):
        self.fleet, self.seq = fleet, sequencers
        self.modules_of = {f["id"]: [s["module"] for s in f["sensors"]] for f in scenario["friendlies"]}
        self.max_active, self.dwell_s, self.lost_s = max_active, dwell_s, lost_s
        self.tasks: Dict[str, Task] = {}
        self.log: List[dict] = []      # one entry per finished investigation, for analysis
        self.stats = {"requests": 0, "dispatched": 0, "no_drone": 0, "on_station": 0, "done": 0, "aborted": 0,
                      "cues": 0, "cue_dispatched": 0}

    # ------------------------------------------------------------------ requests
    def handle(self, t: float, requests: List[dict]) -> List[dict]:
        statuses = []
        for r in requests:
            self.stats["requests"] += 1
            if r["track_id"] in self.tasks or len(self.tasks) >= self.max_active:
                continue
            pick = self._choose(r)
            if pick is None:
                self.stats["no_drone"] += 1
                continue
            drone, standoff = pick
            xy = (r["position"][0], r["position"][1])
            self.tasks[r["track_id"]] = Task(r["track_id"], drone, standoff, t, t_last_seen=t, last_xy=xy)
            self.stats["dispatched"] += 1
            statuses.append(self._status(r["track_id"], drone, "assigned", t))
        return statuses

    def cue(self, t: float, xy: Tuple[float, float], track_id: str = "") -> bool:
        """Send the closest free drone, the one that saw it included, to identify what is at `xy` (see
        `pipeline/cueing.py`). With a `track_id` it follows that track like any investigation; without one the
        point is a guess along a bearing, so the drone only goes there and looks."""
        self.stats["cues"] += 1
        if len(self.tasks) >= self.max_active or track_id in self.tasks:
            return False
        busy = {task.drone for task in self.tasks.values()}
        free = [(math.hypot(d.x - xy[0], d.y - xy[1]), i) for i, d in self.fleet.drones.items()
                if i not in busy and self.fleet.is_free(i)]
        if not free:
            self.stats["no_drone"] += 1
            return False
        drone = min(free)[1]
        key = track_id or f"cue-{self.stats['cue_dispatched'] + 1}"
        self.tasks[key] = Task(key, drone, CUE_STANDOFF_M, t, t_last_seen=t, last_xy=xy, cue=not track_id)
        self.stats["dispatched"] += 1
        self.stats["cue_dispatched"] += 1
        return True

    def _choose(self, request: dict) -> Optional[Tuple[str, float]]:
        x, y = request["position"][0], request["position"][1]
        busy = {task.drone for task in self.tasks.values()}
        best = None
        for drone_id, d in self.fleet.drones.items():
            distance = math.hypot(d.x - x, d.y - y)
            if drone_id in busy or not self.fleet.is_free(drone_id) or distance < OWN_TRACK_RADIUS_M:
                continue
            ranges = [request["standoff_by_module"][m] for m in self.modules_of[drone_id] if m in request["standoff_by_module"]]
            feasible = [s for s in ranges if s["feasible"]]
            if feasible and (best is None or distance < best[0]):
                best = (distance, drone_id, max(SAFE_STANDOFF_M, max(s["recommended_m"] for s in feasible)))
        return None if best is None else (best[1], best[2])

    # -------------------------------------------------------------------- flight
    def step(self, t: float, tracks: Dict[str, Tuple[float, float]]) -> List[dict]:
        """Advance every investigation; `tracks` maps track ids to their current estimated (x, y)."""
        statuses = []
        for track_id, task in list(self.tasks.items()):
            if task.cue:
                pass
            elif track_id in tracks:
                task.t_last_seen, task.last_xy = t, tracks[track_id]
            elif t - task.t_last_seen > self.lost_s:
                statuses.append(self._finish(task, "aborted", t))
                continue
            statuses += self._fly(task, t)
        return statuses

    def _fly(self, task: Task, t: float) -> List[dict]:
        d = self.fleet.drones[task.drone]
        tx, ty = task.last_xy
        away = math.hypot(d.x - tx, d.y - ty) or 1.0
        goal = (tx + (d.x - tx) / away * task.standoff_m, ty + (d.y - ty) / away * task.standoff_m)
        self.fleet.command(task.drone, goal, face=(tx, ty))
        out = []
        if task.state == "assigned":
            task.state = "en_route"
            out.append(self._status(task.track_id, task.drone, "en_route", t))
        if task.state == "en_route" and away <= task.standoff_m * ON_STATION_MARGIN:
            task.state, task.t_station = "on_station", t
            self.stats["on_station"] += 1
            out.append(self._status(task.track_id, task.drone, "on_station", t))
        if task.state == "on_station" and t - task.t_station >= self.dwell_s:
            out.append(self._finish(task, "done", t))
        return out

    def _finish(self, task: Task, state: str, t: float) -> dict:
        self.fleet.release(task.drone)
        del self.tasks[task.track_id]
        self.stats[state] += 1
        self.log.append({"track_id": task.track_id, "drone": task.drone, "state": state, "t_assigned": task.t_assigned,
                         "t_station": task.t_station, "t_end": t, "xy": task.last_xy})
        return self._status(task.track_id, task.drone, state, t)

    def _status(self, track_id: str, drone: str, state: str, t: float) -> dict:
        sequencer = self.seq.setdefault(drone, Sequencer(drone))
        return {"type": "investigation_status", "header": sequencer.header(t),
                "track_id": track_id, "drone_id": drone, "state": state}
