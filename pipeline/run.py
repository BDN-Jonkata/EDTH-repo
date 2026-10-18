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
from dataclasses import dataclass, field, replace
from typing import Dict, Iterator, List, Optional

from common.channel import Channel, node_clocks
from common.codec import Sequencer
from health.monitor import HealthMonitor
from health.trust import weighted
from friend_foe.estimator import Beacon, FriendFoeEstimator, TrackState, for_scenario
from pipeline.dispatch import Investigator
from fusion.hub import BearingHub
from fusion.merger import Merger
from pipeline.cueing import Cueing
from pipeline.fleet import Fleet
from pipeline.identify import Emitters, IdentifyConfig
from pipeline.nodes import NodeTrackers
from pipeline.storefwd import StoreForward, store_forward_on
from predictor.identity import IdentityConfig, IdentityKeeper
from predictor.motion import MotionModel
from scoring.metrics import Estimate
from sensors.beacons import BeaconSource
from sensors.observe import ObservationSource
from sensors.quality import load_modules
from sensors.world import World
from tracker.measurement import RssiRange, from_observation
from tracker.poses import PoseBook
from tracker.timesync import TimeSync, clock_floor_s, known_delay_of
from tracker.tracker import Track, Tracker, TrackerConfig

STEP_S = 0.1          # the simulation clock; sensors fire at their own rates inside it
CLASSIFY_EVERY = 5    # the estimator runs every 0.5 s, on the beacons that arrived since


@dataclass
class Frame:
    t: float
    tracks: List[Track]          # confirmed tracks
    beacons: List[dict]          # friendly_beacon messages delivered this step
    readings_used: int           # delivered observations the tracker could use
    readings: list = field(default_factory=list)   # those readings, for the cueing


class Pipeline:
    def __init__(self, scenario: dict, seed: int = 0, tracker_config: Optional[TrackerConfig] = None,
                 investigate: bool = False, distributed: bool = False, cue: bool = False, trust: bool = False,
                 oosm: bool = False, clocks: bool = False, timesync: bool = False, oosm_age_s: Optional[float] = None,
                 storefwd: bool = False, rssi: Optional[RssiRange] = None):
        """`rssi` gives the RF readings a range from their signal strength (`tracker/measurement.RssiRange`; central tracker
        only). `investigate` lets the drones be commanded (`pipeline/fleet.py`) and adds the investigator that
        commands them (`pipeline/dispatch.py`); without it every drone flies its patrol loop. `trust` weights each
        reading by how healthy its node's link is and leaves out late ones (`health/`; central tracker only). `oosm` applies
        a late reading at the time it was taken instead (`tracker/oosm.py`; central tracker only; with `trust` the late
        ones are weighted by their age, not left out). `clocks` stamps
        every reading with its node's own clock, offset and drift included, as a beacon already is (without it a reading
        carries the true time); `timesync` also estimates each node's clock from what arrives and puts the stamps back
        on the C2 clock (`tracker/timesync.py`); `oosm_age_s` sets how old a reading must be to be replayed at its own
        time (`TrackerConfig.oosm_min_age_s`). None of the three applies to `distributed`. `storefwd` turns on
        store-and-forward when the scenario asks for it (`pipeline/storefwd.py`; central tracker only). `distributed`
        replaces the one central tracker by a tracker per node and a merger (`pipeline/nodes.py`). `cue` also
        sends the closest other drone at a bearing nothing explains (`pipeline/cueing.py`); it implies the
        commanded drones and the investigator."""
        sequencers: Dict[str, Sequencer] = {}
        self.modules = load_modules()
        commanded = investigate or cue
        self.fleet = Fleet(scenario) if commanded else None
        world = World(scenario, self.fleet)
        self.beacons = BeaconSource(scenario, seed + 1, sequencers, world)
        self.sync = TimeSync(clock_floor_s(scenario, STEP_S)) if timesync and not distributed else None
        stamped = (clocks or timesync) and not distributed
        self.observations = ObservationSource(scenario, seed, self.modules, sequencers, world,
                                              node_clocks(scenario, seed + 3, self.beacons.clocks) if stamped else None)
        self.channel = Channel(scenario, seed + 2, lambda node, t: _node_xy(world, node, t))   # for jamming zones
        self.use_oosm = oosm and not distributed
        central = tracker_config
        if self.use_oosm:
            central = replace(tracker_config or TrackerConfig(), oosm=True,
                              **({} if oosm_age_s is None else {"oosm_min_age_s": oosm_age_s}))
        self.poses, self.tracker = PoseBook(scenario), Tracker(central)
        self.investigator = Investigator(scenario, self.fleet, sequencers, cueing=Cueing() if cue else None) if commanded else None
        self.nodes = NodeTrackers(tracker_config, sequencers) if distributed else None
        self.merger = Merger() if distributed else None
        self.hub = BearingHub(tracker_config) if distributed else None
        self.storefwd = StoreForward(scenario, self.channel, sequencers, self.use_oosm)             if storefwd and not distributed and store_forward_on(scenario) else None
        self.health = HealthMonitor()                  # judges every node's link from what the channel delivers
        self.use_trust = trust and not distributed     # the distributed mode's observations skip the channel, so their seq has gaps
        self.rssi = rssi

    def step(self, t: float) -> Frame:
        if self.fleet is not None:
            self.fleet.step(t)
        observations = self.observations.at(t)
        if self.nodes is None:
            for obs in observations:
                latency_s = self.modules[obs["sensor_id"]]["sim"]["latency_ms"] / 1000.0
                self._send(obs, t, latency_s)
        for beacon in self.beacons.at(t):
            if self.storefwd is not None:
                self.storefwd.stamp_status(beacon, t)
            self._send(beacon, t)
        delivered = self._delivered(t)
        self.health.observe_all(delivered, t)
        if self.sync is not None:
            delivered = self.sync.apply(delivered, t, known_delay_of(self.modules))
        beacons = [m for m in delivered if m["type"] == "friendly_beacon"]
        for b in beacons:
            self.poses.note_beacon(b)
        if self.nodes is not None:
            return self._distributed_step(t, observations, beacons, delivered)
        readings = self._readings([m for m in delivered if m["type"] == "observation"], t)
        tracks = self.tracker.step(t, readings, beacons)
        return Frame(t, tracks, beacons, len(readings), readings)

    def _send(self, message: dict, t: float, latency_s: float = 0.0) -> None:
        if self.storefwd is not None:
            self.storefwd.sent(message, t)
        self.channel.send(message, t, latency_s)

    def _delivered(self, t: float) -> List[dict]:
        """What reached C2 this step; with store-and-forward the acks go out first and the resends, duplicates and
        late messages are dealt with (`pipeline/storefwd.py`)."""
        if self.storefwd is None:
            return self.channel.deliver(t)
        for status in self.storefwd.node_status(t):
            self._send(status, t)
        self.storefwd.send_acks(t)
        return self.storefwd.receive(self.channel.deliver(t), t)

    def _distributed_step(self, t: float, observations: List[dict], beacons: List[dict], delivered: List[dict]) -> Frame:
        """Each node tracks its own readings; only the tracks it shares cross the lossy channel to the merger."""
        readings = self._readings(observations)
        for message in self.nodes.step(t, readings, beacons):
            self.channel.send(message, t)
        self.merger.ingest(delivered + self.hub.step(t, delivered))
        return Frame(t, self.merger.step(t), beacons, len(readings), readings)

    def _readings(self, observations: List[dict], t: float = 0.0) -> list:
        out = []
        for obs in observations:
            if self.use_trust and not self.use_oosm and self.health.is_late(t - obs["t_obs"]):
                continue                                  # too old for the live picture
            module = self.modules[obs["sensor_id"]]
            pose = self.poses.pose(obs["header"]["source_id"], obs["t_obs"])
            m = from_observation(obs, pose, module, self.rssi)
            if m is not None and self.use_trust:
                m = weighted(m, self.health.trust(obs["header"]["source_id"], t, t - obs["t_obs"]))
            if m is not None:
                out.append(m)
        return out


def run(scenario: dict, seed: int = 0, tracker_config: Optional[TrackerConfig] = None) -> Iterator[Frame]:
    pipeline = Pipeline(scenario, seed, tracker_config)
    for k in range(int(scenario["duration_s"] / STEP_S) + 1):
        yield pipeline.step(round(k * STEP_S, 6))


def _node_xy(world: World, node: str, t: float) -> Optional[tuple]:
    """Where a sending node really is (the channel's jamming zones need it); None for a sender that is not a node."""
    if node not in world.friendlies and node not in world.ground:
        return None
    pose = world.node_pose(node, t)
    return pose.x, pose.y


def _track_state(tr: Track, t: float) -> TrackState:
    """What the estimator may know about a track, including how fresh it is: `observed_t` is the last reading
    that really updated it (a coasting track is extrapolation, not an observation), so the behaviour module
    draws no conclusion from a track that is only a guess. Existence is not lowered while a track coasts: that
    dropped friend tracks whose beacons were lost out of the estimator, and they then counted as flagged."""
    return TrackState(tr.track_id, t, (tr.state[0], tr.state[1], 0.0), (tr.state[2], tr.state[3], 0.0),
                      pos_sigma=tr.position_sigma, existence_prob=0.95, observed_t=tr.last_update)


def _beacon(m: dict) -> Beacon:
    """The tracker is 2D (altitude is not tracked), so the beacon is compared with the tracks on the ground plane."""
    var = m["covariance"][0][0]
    x, y, _z = m["position"]
    return Beacon(m["friend_id"], m["header"]["t_sent"], (x, y, 0.0), (m["velocity"][0], m["velocity"][1], 0.0),
                  math.sqrt(var))


def _class_of(tr: Track, t: float, classes: Dict[str, str], friend_tracks: bool, emitters: Optional[Emitters]) -> Optional[str]:
    """A beacon track is friendly (with `friend_tracks`); else what the sensors say it is (`identify`: an emitter is
    hostile); else the estimator's class. A friendly from the estimator is never overridden."""
    if friend_tracks and tr.friend_id:
        return "friendly"
    estimated = classes.get(tr.track_id)
    if emitters is not None and estimated != "friendly":
        return emitters.label(tr.track_id, t) or estimated
    return estimated


def scored_frames(scenario: dict, seed: int = 0, tracker_config: Optional[TrackerConfig] = None,
                  estimator: Optional[FriendFoeEstimator] = None, investigate: bool = False,
                  stats: Optional[dict] = None, recorded: Optional[dict] = None,
                  keep_identity: bool = False, distributed: bool = False, cue: bool = False,
                  trust: bool = False, oosm: bool = False, clocks: bool = False, timesync: bool = False,
                  oosm_age_s: Optional[float] = None, storefwd: bool = False,
                  friend_tracks: bool = True, identify: bool = True, rssi: Optional[RssiRange] = None) -> Iterator[tuple]:
    """(t, [Estimate]) for the scoring module: the tracker's confirmed tracks with the estimator's class.

    With `investigate`, suspicious tracks send drones out; when the run ends `stats` (if given) is filled with
    the dispatcher's counts (requests, dispatched, on_station, done, aborted), and `recorded` (if given) with
    each drone's real trajectory as `[t, x, y, vx, vy]` rows, which scoring needs because the drones left
    the scripted patrol in `truth.json` (see `scoring.truth.with_recorded_samples`). `keep_identity` runs the
    predictor's identity keeper (`predictor/identity.py`) on the tracks, so a re-acquired target keeps its ID.
    `trust` weights readings by link health and lets a cut-off friendly's silence count for less (`health/`).
    `oosm` applies a late reading to its track at the time it was taken (`tracker/oosm.py`). `clocks`, `timesync`, `oosm_age_s`
    and `storefwd`: see `Pipeline`. `friend_tracks` calls a track the tracker started from a friendly's beacon friendly
    for as long as the tracker keeps it, instead of waiting for the estimator to match a fresh beacon to it again."""
    estimator = estimator or FriendFoeEstimator(for_scenario(scenario))
    pipeline = Pipeline(scenario, seed, tracker_config, investigate, distributed, cue, trust, oosm, clocks, timesync, oosm_age_s, storefwd, rssi)
    if trust:        # a missing beacon of a node whose link is down is not evidence against the drone
        getattr(estimator, "estimator", estimator).silence_explained = pipeline.health.explains_silence
    keeper = IdentityKeeper(IdentityConfig(model=MotionModel.load() if keep_identity == "learned" else None)) if keep_identity else None
    pending: List[Beacon] = []
    classes: Dict[str, str] = {}
    emitters = Emitters(identify if isinstance(identify, IdentifyConfig) else None) if identify else None
    for k in range(int(scenario["duration_s"] / STEP_S) + 1):
        frame = pipeline.step(round(k * STEP_S, 6))
        if keeper is not None:
            frame.tracks = keeper.step(frame.t, frame.tracks)
        if recorded is not None and pipeline.fleet is not None:
            for d in pipeline.fleet.drones.values():
                recorded.setdefault(d.id, []).append([frame.t, d.x, d.y, d.vx, d.vy])
        pending += [_beacon(b) for b in frame.beacons]
        if emitters is not None:
            emitters.step(frame.t, frame.readings, frame.tracks)
        if k % CLASSIFY_EVERY == 0:
            states = [_track_state(tr, frame.t) for tr in frame.tracks]
            found = estimator.update(frame.t, states, pending)
            classes, pending = {c.track_id: c.cls for c in found}, []
            if pipeline.investigator:
                pipeline.investigator.on_classification(frame.t, found, states, {tr.track_id: tr for tr in frame.tracks})
        if pipeline.investigator:
            pipeline.investigator.on_readings(frame.t, frame.readings, frame.tracks)
            pipeline.investigator.step(frame.t, {tr.track_id: (tr.state[0], tr.state[1]) for tr in frame.tracks})
        yield frame.t, [Estimate(tr.track_id, frame.t, tr.state[0], tr.state[1], tr.state[2], tr.state[3],
                                 _class_of(tr, frame.t, classes, friend_tracks, emitters)) for tr in frame.tracks]
    if stats is not None and pipeline.investigator:
        stats.update(pipeline.investigator.stats, log=pipeline.investigator.dispatcher.log)
