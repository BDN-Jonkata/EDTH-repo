import math
from dataclasses import replace

import pytest

from drone_behavior import BehaviorConfig
from friend_foe.automatic import AutomaticEstimator
from friend_foe.estimator import Beacon, EstimatorConfig, TrackState


CORRIDOR = {"start": [0.0, 100.0], "end": [1000.0, 100.0], "half_width_m": 30.0}


def state(t, x=500, y=500, vx=0, vy=0, **kw):
    return TrackState("opaque-track", t, (x, y, 60), (vx, vy, 0), **kw)


def run(path, duration=30, dt=0.5, policy=None, beacon=False):
    est = AutomaticEstimator(policy or BehaviorConfig())
    out = []
    for k in range(round(duration / dt) + 1):
        t = k * dt
        tr = path(t)
        beacons = [Beacon("trusted", t, tr.position, tr.velocity)] if beacon and k % round(0.5 / dt) == 0 else []
        out += est.update(t, [tr], beacons)
    return est, out


def approach(t, **kw):
    return state(t, x=200 + 10 * t, y=500, vx=10, **kw)


def test_silence_cannot_verify_identity_but_sustained_safe_transit_can_be_peaceful():
    _, found = run(lambda t: state(t, x=100 + 10 * t, y=100, vx=10), duration=60)
    assert found[-1].cls == "peaceful"
    assert not {"hostile", "friendly"}.intersection(c.cls for c in found)
    assert all(c.cls == 'unknown' for c in found if c.t < 15)


def test_transit_past_c2_is_not_a_threat_without_a_risky_encounter():
    est, found = run(approach, duration=30)
    assert found[-1].cls == "peaceful"
    assert all(c.cls not in ("hostile", "suspicious") for c in found)
    assert est.explain("opaque-track")["reasons"] == ["sustained_safe_transit"]


def test_authorized_transit_is_peaceful_without_becoming_ally():
    cfg = BehaviorConfig(corridors=[CORRIDOR])
    _, found = run(lambda t: state(t, x=100 + 10 * t, y=100, vx=10), policy=cfg)
    assert found[-1].cls == "peaceful" and found[-1].p_hostile < 0.1
    assert all(c.cls != "friendly" for c in found)


def test_corridors_no_longer_depend_on_distance_from_c2():
    corridor = dict(CORRIDOR, start=[0, 500], end=[1000, 500])
    _, found = run(approach, duration=22, policy=BehaviorConfig(corridors=[corridor]))
    assert found[-1].cls == "peaceful"
    assert all(c.cls != "hostile" for c in found)


def test_verified_identity_stays_primary_and_stationary_motion_is_neutral():
    _, found = run(lambda t: state(t), duration=25, beacon=True)
    assert found[-1].cls == "friendly" and found[-1].p_hostile == 0.5
    assert all(c.cls == "friendly" for c in found if c.t >= 2)


def test_known_preflight_roster_is_identity_evidence():
    est = AutomaticEstimator(verified_ids=["our-fleet-7"])
    tr = replace(state(0), track_id="our-fleet-7")
    assert est.update(0, [tr], [])[0].cls == "friendly"


@pytest.mark.parametrize('roster', [False, True])
def test_friendly_losing_its_beacon_fades_to_unknown_and_recovers_without_suspicion(roster):
    est = AutomaticEstimator(BehaviorConfig(), verified_ids=['opaque-track'] if roster else [])
    lost = []
    for k in range(241):
        t = k / 2
        tr = state(t, 100, 100, observed_t=min(t, 20))
        beacons = [Beacon('trusted', t, tr.position)] if t <= 20 else []
        found = est.update(t, [tr], beacons)[0]
        if t == 20:
            assert found.cls == 'friendly'
        if t > 20:
            lost.append(found)
    assert {c.cls for c in lost} == {'friendly', 'unknown'}
    assert lost[-1].cls == 'unknown'
    assert all(c.p_hostile == 0.5 for c in lost)
    for k in range(1, 7):
        t = 120 + k / 2
        tr = state(t, 100, 100)
        found = est.update(t, [tr], [Beacon('trusted', t, tr.position)])[0]
    assert found.cls == 'friendly'


def test_erratic_turns_alone_are_not_enemy_evidence():
    _, found = run(lambda t: state(t, 100 + 20 * math.cos(t), 100 + 20 * math.sin(t),
                                  -20 * math.sin(t), 20 * math.cos(t)))
    assert all(c.cls not in ("hostile", "peaceful") for c in found)


@pytest.mark.parametrize("quality", [{"pos_sigma": 100}, {"existence_prob": 0.4}, {"pos_sigma": math.nan}])
def test_low_quality_or_invalid_measurements_never_add_behavior_evidence(quality):
    est, found = run(lambda t: approach(t, **quality), duration=22)
    assert all(c.p_hostile == 0.5 for c in found)
    assert est.explain("opaque-track")["increment"] == 0


def test_noisy_boundary_crossing_without_confident_entry_is_ambiguous():
    _, found = run(lambda t: state(t, 350 + 3 * math.sin(3 * t), 500, 1, 0, pos_sigma=10))
    assert all(c.cls != "hostile" for c in found)


def test_predicted_and_replayed_states_decay_instead_of_adding_evidence():
    est, found = run(lambda t: state(t, x=100+10*t, y=100, vx=10), duration=22)
    assert found[-1].cls == "peaceful"
    before = found[-1].p_hostile
    for t in [22.5, 23, 23.5]:
        tr = replace(state(t), observed_t=22)
        result = est.update(t, [tr], [])[0]
        assert est.explain(tr.track_id)["increment"] == 0
        assert result.p_hostile > before
        before = result.p_hostile
    # After a gap, reacquisition has to establish a fresh continuous history.
    result = est.update(30, [state(30)], [])[0]
    assert result.p_hostile == pytest.approx(0.5)
    assert est.explain("opaque-track")["reasons"] == ["insufficient_history"]


def test_duplicate_frame_cannot_advance_warmup_or_evidence():
    est = AutomaticEstimator()
    initial = est.update(0, [state(0)], [])
    for _ in range(100):
        assert est.update(0, [state(0)], []) == initial
    assert est.estimator._memory["opaque-track"].n_updates == 1


def test_one_replayed_beacon_cannot_verify_an_identity():
    est = AutomaticEstimator()
    b = Beacon("trusted", 0, (500, 500, 60))
    found = [est.update(k / 10, [state(k / 10)], [b])[0] for k in range(20)]
    assert all(c.cls != "friendly" for c in found)
    assert max(c.p_friendly for c in found) < 0.75


def test_frame_rate_does_not_change_behavior_probability():
    _, slow = run(approach, duration=22, dt=0.5)
    _, fast = run(approach, duration=22, dt=0.1)
    for c in slow:
        other = next(v for v in fast if abs(v.t - c.t) < 1e-8)
        assert c.p_hostile == pytest.approx(other.p_hostile)


def test_evidence_reverses_after_a_genuine_behavior_change():
    cfg = BehaviorConfig(corridors=[CORRIDOR])
    est, found = run(lambda t: state(t, 100+10*t, 100, 10, 0), duration=20, policy=cfg)
    assert found[-1].cls == "peaceful"
    classes = []
    for k in range(61):
        t = 25 + k/2
        classes += est.update(t, [state(t)], [])
    assert classes[-1].cls == "unknown" and classes[-1].p_hostile == 0.5


def test_opaque_ids_do_not_change_the_result():
    a, b = AutomaticEstimator(BehaviorConfig()), AutomaticEstimator(BehaviorConfig())
    for k in range(45):
        t = k / 2
        x = a.update(t, [approach(t)], [])[0]
        y = b.update(t, [replace(approach(t), track_id="bird-friendly-enemy-999")], [])[0]
        assert (x.cls, x.p_hostile, x.p_friendly) == (y.cls, y.p_hostile, y.p_friendly)


def test_memory_is_bounded_and_out_of_order_time_is_rejected():
    est, _ = run(approach)
    assert len(est.behavior.memory["opaque-track"]["history"]) <= 41
    with pytest.raises(ValueError, match="monotonic"):
        est.update(20, [state(20)], [])
    est.update(61, [], [])
    assert not est.behavior.memory


def test_invalid_policy_is_rejected():
    with pytest.raises(ValueError):
        BehaviorConfig(corridors=[dict(CORRIDOR, end=CORRIDOR["start"])])
    with pytest.raises(ValueError):
        BehaviorConfig(window_s=-1)


def test_reappearing_id_does_not_inherit_expired_threat():
    est, found = run(lambda t: state(t, 100+10*t, 100, 10, 0), duration=20)
    assert found[-1].cls == "peaceful"
    result = est.update(55, [state(55, x=100, y=100)], [])[0]
    assert result.cls == "unknown" and result.p_hostile == 0.5


def test_custom_evidence_limit_and_ttl_do_not_create_opposite_evidence():
    est = AutomaticEstimator(BehaviorConfig(), EstimatorConfig(llr_limit=1, memory_ttl_s=10))
    for k in range(41):
        t = k / 2
        est.update(t, [state(t, 100+10*t, 100, 10, 0)], [])
    assert est.update(20.5, [state(20.5, x=100, y=100)], [])[0].p_hostile == 0.5
    assert est.update(35, [state(35, x=100, y=100)], [])[0].p_hostile == 0.5


def test_multiple_packets_of_one_identity_cannot_verify_two_tracks():
    est = AutomaticEstimator()
    for k in range(20):
        t = k / 2
        a, b = state(t), replace(state(t, x=503), track_id="second")
        packets = [Beacon("same-identity", t, a.position), Beacon("same-identity", t - 0.1, b.position)]
        found = est.update(t, [a, b], packets)
        assert sum(c.matched_beacon is not None for c in found) <= 1
    assert found[0].cls == "friendly" and found[1].cls != "friendly"


def test_learned_patrol_comparison_is_independent_of_track_order():
    a, b = AutomaticEstimator(), AutomaticEstimator()
    for k in range(61):
        t = k / 2
        tr = state(t, 100 + 20 * math.cos(t / 4), 100 + 20 * math.sin(t / 4),
                   -5 * math.sin(t / 4), 5 * math.cos(t / 4))
        friend = replace(tr, track_id="trusted-track", position=(tr.position[0] + 100, tr.position[1], 60))
        beacon = Beacon("trusted", t, friend.position, friend.velocity)
        first = {c.track_id: c for c in a.update(t, [tr, friend], [beacon])}
        second = {c.track_id: c for c in b.update(t, [friend, tr], [beacon])}
        assert first == second
