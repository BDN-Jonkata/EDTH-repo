"""The whole chain on one scenario: sensors -> lossy network -> tracker -> friend/foe -> scoring.

    sensors/observe.py + sensors/beacons.py   what the nodes sense and send (needs the true positions)
    common/channel.py                         loss and delay, from the scenario's `degradations`
    tracker/                                  one central baseline tracker on the delivered readings
    friend_foe/                               classification from the tracks and the delivered beacons
    scoring/                                  the metrics against `truth.json`

Everything before the channel is the simulation side; the tracker and friend/foe see only what the
channel delivered. Run `python -m pipeline.sweep` for the metrics over message loss.
"""

import math
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional

from common.channel import Channel
from common.codec import Sequencer
from friend_foe.estimator import Beacon, FriendFoeEstimator, TrackState, for_scenario
from pipeline.dispatch import Investigator
from pipeline.fleet import Fleet
from scoring.metrics import Estimate
from sensors.beacons import BeaconSource
from sensors.observe import ObservationSource
from sensors.quality import load_modules
from sensors.world import World
from tracker.measurement import from_observation
from tracker.poses import PoseBook
from tracker.tracker import Track, Tracker, TrackerConfig

STEP_S = 0.1          # the simulation clock; sensors fire at their own rates inside it
CLASSIFY_EVERY = 5    # the estimator runs every 0.5 s, on the beacons that arrived since


@dataclass
class Frame:
    t: float
    tracks: List[Track]          # confirmed tracks
    beacons: List[dict]          # friendly_beacon messages delivered this step
    readings_used: int           # delivered observations the tracker could use


class Pipeline:
    def __init__(self, scenario: dict, seed: int = 0, tracker_config: Optional[TrackerConfig] = None,
                 investigate: bool = False):
        """`investigate` lets the drones be commanded (`pipeline/fleet.py`) and adds the investigator that
        commands them (`pipeline/dispatch.py`); without it every drone flies its patrol loop."""
        sequencers: Dict[str, Sequencer] = {}
        self.modules = load_modules()
        self.fleet = Fleet(scenario) if investigate else None
        world = World(scenario, self.fleet)
        self.observations = ObservationSource(scenario, seed, self.modules, sequencers, world)
        self.beacons = BeaconSource(scenario, seed + 1, sequencers, world)
        self.channel = Channel(scenario, seed + 2)
        self.poses, self.tracker = PoseBook(scenario), Tracker(tracker_config)
        self.investigator = Investigator(scenario, self.fleet, sequencers) if investigate else None

    def step(self, t: float) -> Frame:
        if self.fleet is not None:
            self.fleet.step(t)
        for obs in self.observations.at(t):
            latency_s = self.modules[obs["sensor_id"]]["sim"]["latency_ms"] / 1000.0
            self.channel.send(obs, t, latency_s)
        for beacon in self.beacons.at(t):
            self.channel.send(beacon, t)
        delivered = self.channel.deliver(t)
        beacons = [m for m in delivered if m["type"] == "friendly_beacon"]
        for b in beacons:
            self.poses.note_beacon(b)
        readings = self._readings([m for m in delivered if m["type"] == "observation"])
        tracks = self.tracker.step(t, readings, beacons)
        return Frame(t, tracks, beacons, len(readings))

    def _readings(self, observations: List[dict]) -> list:
        out = []
        for obs in observations:
            module = self.modules[obs["sensor_id"]]
            pose = self.poses.pose(obs["header"]["source_id"], obs["t_obs"])
            m = from_observation(obs, pose, module)
            if m is not None:
                out.append(m)
        return out


def run(scenario: dict, seed: int = 0, tracker_config: Optional[TrackerConfig] = None) -> Iterator[Frame]:
    pipeline = Pipeline(scenario, seed, tracker_config)
    for k in range(int(scenario["duration_s"] / STEP_S) + 1):
        yield pipeline.step(round(k * STEP_S, 6))


def _track_state(tr: Track, t: float) -> TrackState:
    return TrackState(tr.track_id, t, (tr.state[0], tr.state[1], 0.0), (tr.state[2], tr.state[3], 0.0),
                      pos_sigma=tr.position_sigma, existence_prob=0.95)


def _beacon(m: dict) -> Beacon:
    """The tracker is 2D (altitude is not tracked), so the beacon is compared with the tracks on the ground plane."""
    var = m["covariance"][0][0]
    x, y, _z = m["position"]
    return Beacon(m["friend_id"], m["header"]["t_sent"], (x, y, 0.0), (m["velocity"][0], m["velocity"][1], 0.0),
                  math.sqrt(var))


def scored_frames(scenario: dict, seed: int = 0, tracker_config: Optional[TrackerConfig] = None,
                  estimator: Optional[FriendFoeEstimator] = None, investigate: bool = False,
                  stats: Optional[dict] = None, recorded: Optional[dict] = None) -> Iterator[tuple]:
    """(t, [Estimate]) for the scoring module: the tracker's confirmed tracks with the estimator's class.

    With `investigate`, suspicious tracks send drones out; when the run ends `stats` (if given) is filled with
    the dispatcher's counts (requests, dispatched, on_station, done, aborted), and `recorded` (if given) with
    each drone's real trajectory as `[t, x, y, vx, vy]` rows, which scoring needs because the drones left
    the scripted patrol in `truth.json` (see `scoring.truth.with_recorded_samples`)."""
    estimator = estimator or FriendFoeEstimator(for_scenario(scenario))
    pipeline = Pipeline(scenario, seed, tracker_config, investigate)
    pending: List[Beacon] = []
    classes: Dict[str, str] = {}
    for k in range(int(scenario["duration_s"] / STEP_S) + 1):
        frame = pipeline.step(round(k * STEP_S, 6))
        if recorded is not None and pipeline.fleet is not None:
            for d in pipeline.fleet.drones.values():
                recorded.setdefault(d.id, []).append([frame.t, d.x, d.y, d.vx, d.vy])
        pending += [_beacon(b) for b in frame.beacons]
        if k % CLASSIFY_EVERY == 0:
            states = [_track_state(tr, frame.t) for tr in frame.tracks]
            found = estimator.update(frame.t, states, pending)
            classes, pending = {c.track_id: c.cls for c in found}, []
            if pipeline.investigator:
                pipeline.investigator.on_classification(frame.t, found, states)
        if pipeline.investigator:
            pipeline.investigator.step(frame.t, {tr.track_id: (tr.state[0], tr.state[1]) for tr in frame.tracks})
        yield frame.t, [Estimate(tr.track_id, frame.t, tr.state[0], tr.state[1], tr.state[2], tr.state[3],
                                 classes.get(tr.track_id)) for tr in frame.tracks]
    if stats is not None and pipeline.investigator:
        stats.update(pipeline.investigator.stats, log=pipeline.investigator.dispatcher.log)
