import random

from friend_foe.estimator import Beacon, FriendFoeEstimator, TrackState
from friend_foe.investigation import InvestigationTrigger
from sensors.weather import CLEAR, FOG, UniformWeather

DT = 0.5


def track(tid, t, pos, **kw):
    return TrackState(tid, t, pos, pos_sigma=2.0, **kw)


def beacon(fid, t, pos):
    return Beacon(fid, t, pos, pos_sigma=1.0)


def run(est, steps, tracks_at, beacons_at):
    """Drive the estimator; return the last class per track and the class history."""
    last, history = {}, {}
    for k in range(steps):
        t = k * DT
        for c in est.update(t, tracks_at(t), beacons_at(t)):
            last[c.track_id] = c
            history.setdefault(c.track_id, []).append(c.cls)
    return last, history


def test_steady_beacon_makes_friendly():
    last, _ = run(
        FriendFoeEstimator(), 20,
        lambda t: [track("A", t, (10 * t, 0, 0))],
        lambda t: [beacon("A", t, (10 * t, 0, 0))],
    )
    assert last["A"].cls == "friendly" and last["A"].matched_beacon == "A"


def test_no_beacon_is_suspicious_never_hostile():
    last, history = run(
        FriendFoeEstimator(), 200,
        lambda t: [track("X", t, (10 * t, 0, 0))],
        lambda t: [],
    )
    assert last["X"].cls == "suspicious"
    assert "hostile" not in history["X"]


def test_hostile_needs_behaviour_evidence():
    est = FriendFoeEstimator(behaviour_llr=lambda tr: -0.5)
    last, _ = run(est, 40, lambda t: [track("X", t, (0, 0, 0))], lambda t: [])
    assert last["X"].cls == "hostile"


def test_early_updates_stay_unknown():
    last, _ = run(
        FriendFoeEstimator(), 3,
        lambda t: [track("A", t, (0, 0, 0))],
        lambda t: [beacon("A", t, (0, 0, 0))],
    )
    assert last["A"].cls == "unknown"


def test_one_beacon_marks_only_the_nearest_track():
    # A hostile flies 3 m from a friendly: only the closer track may take the beacon.
    last, _ = run(
        FriendFoeEstimator(), 30,
        lambda t: [track("friend", t, (0, 0, 0)), track("intruder", t, (3, 0, 0))],
        lambda t: [beacon("F", t, (0.2, 0, 0))],
    )
    assert last["friend"].cls == "friendly"
    assert last["intruder"].cls != "friendly"


def test_stale_beacon_is_ignored():
    est = FriendFoeEstimator()
    c = est.update(10.0, [track("A", 10.0, (0, 0, 0))], [beacon("A", 5.0, (0, 0, 0))])
    assert c[0].matched_beacon is None


def test_far_beacon_is_not_matched():
    est = FriendFoeEstimator()
    c = est.update(0.0, [track("A", 0.0, (0, 0, 0))], [beacon("A", 0.0, (500, 0, 0))])
    assert c[0].matched_beacon is None


def test_weak_tracks_are_ignored():
    est = FriendFoeEstimator()
    assert est.update(0.0, [track("g", 0.0, (0, 0, 0), existence_prob=0.1)], []) == []


def test_packet_loss_does_not_make_friendly_flicker():
    rng = random.Random(1)
    _, history = run(
        FriendFoeEstimator(), 200,
        lambda t: [track("A", t, (0, 0, 0))],
        lambda t: [beacon("A", t, (0, 0, 0))] if rng.random() > 0.3 else [],
    )
    h = history["A"]
    first = h.index("friendly")
    assert set(h[first:]) == {"friendly"}


def test_jammed_beacon_friend_holds_then_degrades():
    _, history = run(
        FriendFoeEstimator(), 200,
        lambda t: [track("A", t, (0, 0, 0))],
        lambda t: [beacon("A", t, (0, 0, 0))] if t < 10 else [],
    )
    h = history["A"]
    assert h[int(12 / DT)] == "friendly"        # still trusted shortly after jamming starts
    assert h[-1] == "suspicious"                # but not forever


def make_trigger(weather=CLEAR, **kw):
    return InvestigationTrigger(UniformWeather(weather), **kw)


def drive_trigger(trigger, steps):
    est, requests = FriendFoeEstimator(), []
    for k in range(steps):
        t = k * DT
        tr = [track("X", t, (100, 200, 50))]
        requests += trigger.update(t, est.update(t, tr, []), tr)
    return requests


def test_request_raised_once_for_suspicious_track():
    reqs = drive_trigger(make_trigger(min_suspicious_s=3.0, cooldown_s=1000.0), 200)
    assert len(reqs) == 1
    r = reqs[0]
    assert r["type"] == "investigation_request" and r["track_id"] == "X"
    assert r["position"] == [100, 200, 50]
    assert set(r["standoff_by_sensor"]) == {"camera", "acoustic", "rf", "radar"}


def test_cooldown_allows_a_second_request():
    reqs = drive_trigger(make_trigger(min_suspicious_s=3.0, cooldown_s=20.0), 400)
    assert len(reqs) >= 2


def test_no_request_for_friendly_or_hostile():
    est, trigger = FriendFoeEstimator(), make_trigger(min_suspicious_s=0.0)
    for k in range(60):
        t = k * DT
        tr = [track("A", t, (0, 0, 0))]
        assert trigger.update(t, est.update(t, tr, [beacon("A", t, (0, 0, 0))]), tr) == []
    est = FriendFoeEstimator(behaviour_llr=lambda x: -0.5)
    trigger = make_trigger(min_suspicious_s=0.0)
    for k in range(60):
        t = k * DT
        tr = [track("H", t, (0, 0, 0))]
        classes = est.update(t, tr, [])
        reqs = trigger.update(t, classes, tr)
        if classes[0].cls == "hostile":
            assert reqs == []


def test_active_status_blocks_new_requests_until_done():
    trigger = make_trigger(min_suspicious_s=0.0, cooldown_s=5.0)
    est = FriendFoeEstimator()
    reqs = []
    for k in range(40):
        t = k * DT
        tr = [track("X", t, (0, 0, 0))]
        got = trigger.update(t, est.update(t, tr, []), tr)
        reqs += got
        if got:
            trigger.on_status({"track_id": "X", "state": "en_route"}, t)
    assert len(reqs) == 1
    trigger.on_status({"track_id": "X", "state": "done"}, 20.0)
    for k in range(60, 64):   # t = 30..31.5, after the cooldown that follows "done"
        t = k * DT
        tr = [track("X", t, (0, 0, 0))]
        reqs += trigger.update(t, est.update(t, tr, []), tr)
    assert len(reqs) == 2


def test_fog_shrinks_requested_standoff():
    # Camera-only drone: RF would be unaffected by fog and win the "best sensor" choice.
    clear = drive_trigger(make_trigger(CLEAR, sensor_types=["camera"]), 100)[0]
    fog = drive_trigger(make_trigger(FOG, sensor_types=["camera"]), 100)[0]
    assert fog["standoff_m"] < clear["standoff_m"]
    assert fog["weather_confidence"] < clear["weather_confidence"]
