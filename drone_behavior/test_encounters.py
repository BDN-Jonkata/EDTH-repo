"""Zone-free risk decisions on observed trajectories; IDs and location are opaque."""
import math
import pytest

from drone_behavior import BehaviorConfig
from friend_foe.automatic import AutomaticEstimator
from friend_foe.estimator import Beacon, TrackState


def wave(t):
    return (200 + 8*t, 400 + 35*math.sin(0.55*t), 8, 19.25*math.cos(0.55*t))


def encounter(kind='pursuit', duration=40, dt=0.5, offset=(0, 0), sigma=2, reverse=False, stale=False,
              ally_sigma=2, verified_contact=False):
    est = AutomaticEstimator(BehaviorConfig(), verified_ids=['verified', 'opaque'] if verified_contact else ['verified'])
    frames = []
    for k in range(round(duration/dt) + 1):
        t = k*dt
        if kind == 'crossing':
            own, other = (200+8*t, 500, 8, 0), (500, 200+8*t, 0, 8)
        else:
            own = wave(t - 2 if reverse else t)
            delay = 0 if kind == 'parallel' or reverse else 2
            x, y, vx, vy = wave(t-delay)
            drift = 3 if kind in ('pursuit', 'breakoff') else 0
            other = (x-80+drift*t, y, vx+drift, vy)
        if kind == 'breakoff' and t >= 25:
            old = wave(23)
            other = (old[0]-5, old[1]+12*(t-25), 0, 12)
        a = TrackState('verified', t, (own[0]+offset[0], own[1]+offset[1], 60), (*own[2:], 0), ally_sigma,
                       observed_t=min(t, 20) if stale else t)
        b = TrackState('opaque', t, (other[0]+offset[0], other[1]+offset[1], 60), (*other[2:], 0), sigma)
        beacons = [Beacon('trusted', t, a.position, a.velocity, 2)] if not stale or t <= 20 else []
        if verified_contact:
            beacons.append(Beacon('trusted-partner', t, b.position, b.velocity, 2))
        found = est.update(t, [a, b], beacons)
        frames.append((t, next(c for c in found if c.track_id == 'opaque'), est.explain('opaque')))
    return est, frames


def test_responsive_pursuit_plus_intercept_risk_can_establish_hostile():
    _, frames = encounter()
    hostile = [e for _, c, e in frames if c.cls == 'hostile']
    assert hostile
    assert 'pursuit_with_intercept_risk' in hostile[0]['reasons']
    assert all('responsive_pursuit' in e['reasons'] or
               'responsive_pursuit' in (e['retained_risk'] or {}).get('reasons', []) for e in hostile)
    assert all(c.cls != 'hostile' for t, c, _ in frames if t < 12)


def test_verified_partner_identity_stays_primary_even_with_risky_motion():
    _, frames = encounter(verified_contact=True)
    assert all(c.cls == 'friendly' for _, c, _ in frames)
    assert max(c.p_hostile for _, c, _ in frames) > 0.9


def test_association_jump_discards_retained_hostile_evidence():
    est, frames = encounter(duration=25)
    assert any(c.cls == 'hostile' for _, c, _ in frames)
    result = est.update(26, [TrackState('opaque', 26, (5000, -5000, 60), (0, 0, 0), 2)], [])[0]
    assert result.cls == 'unknown' and result.p_hostile == 0.5
    assert est.explain('opaque')['retained_risk'] is None


def test_following_without_aggressive_closure_is_suspicious_not_hostile():
    _, frames = encounter('tail')
    assert any(c.cls == 'suspicious' for _, c, _ in frames)
    assert all(c.cls != 'hostile' for _, c, _ in frames)


def test_a_single_collision_course_is_risk_not_proof_of_hostility():
    _, frames = encounter('crossing', duration=65)
    assert any(c.cls == 'suspicious' for _, c, _ in frames)
    assert all(c.cls != 'hostile' for _, c, _ in frames)


def test_parallel_flight_does_not_establish_responsive_pursuit():
    _, frames = encounter('parallel')
    assert all(c.cls not in ('suspicious', 'hostile') for _, c, _ in frames)


def test_our_investigator_following_a_contact_is_not_evidence_against_the_contact():
    _, frames = encounter('tail', reverse=True)
    assert all(c.cls not in ('suspicious', 'hostile') for _, c, _ in frames)


def test_absolute_location_does_not_change_risk():
    _, a = encounter()
    _, b = encounter(offset=(10000, -8000))
    for (_, x, _), (_, y, _) in zip(a, b):
        assert x.cls == y.cls
        assert x.p_hostile == pytest.approx(y.p_hostile)


def test_uncertain_motion_cannot_establish_hostility():
    _, frames = encounter(sigma=100)
    assert all(c.cls == 'unknown' for _, c, _ in frames)


def test_uncertain_ally_motion_cannot_establish_hostility():
    _, frames = encounter(ally_sigma=100)
    assert all(c.cls != 'hostile' for _, c, _ in frames)


def test_unverified_motion_is_not_an_ally_reference():
    est = AutomaticEstimator()
    for k in range(81):
        t = k/2
        own, other = wave(t), wave(t-2)
        tracks = [TrackState('a', t, (*own[:2], 60), (*own[2:], 0), 2),
                  TrackState('b', t, (other[0]-80+3*t, other[1], 60), (other[2]+3, other[3], 0), 2)]
        assert all(c.cls != 'hostile' for c in est.update(t, tracks, []))


def test_a_breakoff_can_clear_prior_risk_after_observed_safe_transit():
    _, frames = encounter('breakoff', duration=65)
    assert any(c.cls == 'hostile' for _, c, _ in frames)
    assert frames[-1][1].cls == 'peaceful'
    assert frames[-1][2]['retained_risk'] is None


def test_retained_risk_decays_without_reusing_stale_ally_maneuvers():
    _, frames = encounter(stale=True)
    retained = [(t, c, e) for t, c, e in frames if t >= 23 and e.get('retained_risk')]
    assert retained
    for (ta, a, _), (tb, b, e) in zip(retained, retained[1:]):
        assert b.p_hostile < a.p_hostile
        assert e['retained_risk']['age_s'] > 0
        assert 'responsive_pursuit' not in e['reasons']


def test_stale_reference_cannot_supply_new_pursuit_evidence():
    _, frames = encounter(stale=True)
    assert all('responsive_pursuit' not in e['reasons'] for t, _, e in frames if t >= 23)


def test_relative_evidence_is_independent_of_frame_rate():
    _, slow = encounter()
    _, fast = encounter(dt=0.1)
    for (t, a, _), (_, b, _) in zip(slow, fast[::5]):
        assert a.cls == b.cls, t
        assert a.p_hostile == pytest.approx(b.p_hostile), t


def test_reference_and_contact_order_do_not_change_assessments():
    a, b = AutomaticEstimator(verified_ids=['verified']), AutomaticEstimator(verified_ids=['verified'])
    for k in range(81):
        t = k/2
        own, other = wave(t), wave(t-2)
        ref = TrackState('verified', t, (*own[:2], 60), (*own[2:], 0), 2)
        tr = TrackState('opaque', t, (other[0]-80+3*t, other[1], 60), (other[2]+3, other[3], 0), 2)
        beacon = Beacon('trusted', t, ref.position, ref.velocity, 2)
        x = {c.track_id:c for c in a.update(t, [ref, tr], [beacon])}
        y = {c.track_id:c for c in b.update(t, [tr, ref], [beacon])}
        assert x == y
