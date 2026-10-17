import random

from friend_foe.estimator import Beacon, FriendFoeEstimator, TrackState
from friend_foe.investigation import InvestigationTrigger
from sensors.quality import load_modules
from sensors.weather import PRESETS, UniformWeather

DT = 0.5
CLEAR, FOG = PRESETS["clear"], PRESETS["fog"]
CAMERA = [load_modules()["eo_visible_mini4"]]


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
    est = FriendFoeEstimator(threat_llr=lambda tr: +0.5)
    last, _ = run(est, 40, lambda t: [track("X", t, (0, 0, 0))], lambda t: [])
    assert last["X"].cls == "hostile" and last["X"].p_hostile > 0.9


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
    # B keeps broadcasting, so the link is known to work and A's silence means something
    _, history = run(
        FriendFoeEstimator(), 200,
        lambda t: [track("A", t, (0, 0, 0)), track("B", t, (200, 0, 0))],
        lambda t: [beacon("B", t, (200, 0, 0))] + ([beacon("A", t, (0, 0, 0))] if t < 10 else []),
    )
    h = history["A"]
    assert h[int(12 / DT)] == "friendly"        # still trusted shortly after jamming starts
    assert h[-1] == "suspicious"                # but not forever
    assert set(history["B"][10:]) == {"friendly"}


def test_everyone_silent_is_never_hostile_and_fades_slowly():
    # all beacons lost: cannot tell a jam from a dead link, so no one is condemned
    _, history = run(
        FriendFoeEstimator(), 400,
        lambda t: [track("A", t, (0, 0, 0)), track("B", t, (200, 0, 0))],
        lambda t: [beacon("A", t, (0, 0, 0)), beacon("B", t, (200, 0, 0))] if t < 10 else [],
    )
    assert "hostile" not in history["A"] + history["B"]
    assert history["A"][int(20 / DT)] == "friendly"


def lossy_beacons(loss, seed, ids_pos):
    rng = random.Random(seed)
    return lambda t: [beacon(i, t, p) for i, p in ids_pos.items() if rng.random() >= loss]


FRIENDS = {"A": (0, 0, 0), "B": (200, 0, 0), "C": (400, 0, 0), "D": (600, 0, 0)}


def test_friends_stay_friendly_under_heavy_beacon_loss():
    est = FriendFoeEstimator()
    flagged = total = 0
    beacons_at = lossy_beacons(0.85, 3, FRIENDS)
    for k in range(600):
        t = k * DT
        found = est.update(t, [track(i, t, p) for i, p in FRIENDS.items()], beacons_at(t))
        if t >= 30:
            total += len(found)
            flagged += sum(c.cls in ("suspicious", "hostile") for c in found)
    assert flagged / total < 0.05


def first_flag_time(loss, seed):
    est, beacons_at = FriendFoeEstimator(), lossy_beacons(loss, seed, FRIENDS)
    for k in range(400):
        t = k * DT
        tracks = [track(i, t, p) for i, p in FRIENDS.items()] + [track("X", t, (300, 300, 0))]
        for c in est.update(t, tracks, beacons_at(t)):
            if c.track_id == "X" and c.cls == "suspicious":
                return t
    return None


def test_silent_intruder_is_flagged_slower_when_links_are_lossy_but_still_flagged():
    clean, lossy = first_flag_time(0.0, 1), first_flag_time(0.85, 1)
    assert clean is not None and lossy is not None
    assert lossy > clean


def test_delivery_rate_follows_the_measured_loss():
    est = FriendFoeEstimator()
    beacons_at = lossy_beacons(0.5, 5, FRIENDS)
    for k in range(400):
        t = k * DT
        est.update(t, [track(i, t, p) for i, p in FRIENDS.items()], beacons_at(t))
    assert 0.35 < est.delivery_rate < 0.65


def test_for_scenario_sets_the_beacon_rate():
    from friend_foe.estimator import for_scenario
    assert for_scenario({"beacon": {"rate_hz": 5}}).beacon_rate_hz == 5


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
    assert "radar_mmwave_small" in r["standoff_by_module"]
    assert not {"gnss_basic", "imu_basic"} & set(r["standoff_by_module"])
    assert set(r["standoff_by_module"]["eo_visible_mini4"]) == {"max_range_m", "recommended_m", "confidence", "feasible"}


def test_cooldown_allows_a_second_request():
    reqs = drive_trigger(make_trigger(min_suspicious_s=3.0, cooldown_s=20.0), 400)
    assert len(reqs) >= 2


def test_no_request_for_friendly_or_hostile():
    est, trigger = FriendFoeEstimator(), make_trigger(min_suspicious_s=0.0)
    for k in range(60):
        t = k * DT
        tr = [track("A", t, (0, 0, 0))]
        assert trigger.update(t, est.update(t, tr, [beacon("A", t, (0, 0, 0))]), tr) == []
    est = FriendFoeEstimator(threat_llr=lambda x: +0.5)
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
    # Camera-only drone: radar and RF are hardly affected by fog and would win the "best module" choice.
    clear = drive_trigger(make_trigger(CLEAR, modules=CAMERA), 100)[0]
    fog = drive_trigger(make_trigger(FOG, modules=CAMERA), 100)[0]
    assert fog["standoff_m"] < clear["standoff_m"]
    assert fog["weather_confidence"] < clear["weather_confidence"]


# ---- peaceful: the mirror of suspicious, from positive behaviour evidence only

def silent(est, steps=200):
    return run(est, steps, lambda t: [track("X", t, (0, 0, 0))], lambda t: [])


def test_peaceful_needs_behaviour_evidence_silence_alone_is_suspicious():
    last, history = silent(FriendFoeEstimator())
    assert last["X"].cls == "suspicious"
    assert "peaceful" not in history["X"]
    assert last["X"].p_hostile == 0.5


def test_peaceful_like_behaviour_makes_a_silent_track_peaceful():
    last, history = silent(FriendFoeEstimator(threat_llr=lambda tr: -0.5), 60)
    assert last["X"].cls == "peaceful" and last["X"].p_hostile < 0.1
    assert last["X"].class_prob > 0.9


def test_peaceful_is_never_investigated():
    est, trigger = FriendFoeEstimator(threat_llr=lambda tr: -0.5), make_trigger(min_suspicious_s=0.0)
    for k in range(200):
        t = k * DT
        tr = [track("X", t, (0, 0, 0))]
        assert trigger.update(t, est.update(t, tr, []), tr) == []


def test_a_beacon_match_stays_friendly_whatever_the_behaviour_looks_like():
    est = FriendFoeEstimator(threat_llr=lambda tr: +0.5)
    last, _ = run(est, 60, lambda t: [track("A", t, (0, 0, 0))], lambda t: [beacon("A", t, (0, 0, 0))])
    assert last["A"].cls == "friendly" and last["A"].p_hostile > 0.9


def test_behaviour_that_changes_changes_the_class_peaceful_to_hostile_and_back():
    mood = {"x": -0.5}
    est = FriendFoeEstimator(threat_llr=lambda tr: mood["x"])
    seen = []
    for k in range(400):
        t = k * DT
        mood["x"] = -0.5 if t < 40 or t >= 120 else +0.5   # peaceful, then hostile-like, then peaceful again
        seen.append(est.update(t, [track("X", t, (0, 0, 0))], [])[0].cls)
    assert seen[int(35 / DT)] == "peaceful"
    assert seen[int(70 / DT)] == "hostile"
    assert seen[-1] == "peaceful"


def test_old_behaviour_evidence_fades_so_a_quiet_track_returns_to_not_identified():
    stop = {"at": 30.0}
    est = FriendFoeEstimator(threat_llr=lambda tr: -0.5 if tr.t < stop["at"] else 0.0)
    classes = [est.update(k * DT, [track("X", k * DT, (0, 0, 0))], [])[0].cls for k in range(400)]
    assert classes[int(25 / DT)] == "peaceful"
    assert classes[-1] == "suspicious"          # the silence is what is left


def test_peaceful_does_not_flicker_around_its_threshold():
    import random as _random
    rng = _random.Random(2)
    est = FriendFoeEstimator(threat_llr=lambda tr: -0.2 + rng.gauss(0, 0.3))
    _, history = silent(est, 400)
    after = history["X"][int(60 / DT):]
    changes = sum(a != b for a, b in zip(after, after[1:]))
    assert changes <= 4


def test_hostile_behaviour_wins_over_silence_but_silence_alone_never_makes_hostile():
    last, history = silent(FriendFoeEstimator(threat_llr=lambda tr: +0.5), 100)
    assert last["X"].cls == "hostile"
    _, history = silent(FriendFoeEstimator(), 400)
    assert "hostile" not in history["X"]