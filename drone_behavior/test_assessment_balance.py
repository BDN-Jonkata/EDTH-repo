"""Behavioral regressions: exercise decisions, not just Python/JS agreement."""
import math

import pytest

from drone_behavior import BehaviorConfig
from friend_foe.automatic import AutomaticEstimator
from friend_foe.estimator import TrackState


def simulate(path, duration=40, sigma=2):
    model = AutomaticEstimator(BehaviorConfig.for_area([500, 500]))
    found = []
    for k in range(int(duration * 2) + 1):
        t = k / 2
        x, y, vx, vy = path(t)
        found.extend(model.update(t, [TrackState('opaque', t, (x, y, 60), (vx, vy, 0), sigma)], []))
    return model, found


def test_silence_without_a_threatening_pattern_stays_unknown():
    _, found = simulate(lambda t: (100, 100, 0, 0))
    assert {c.cls for c in found} == {'unknown'}


def test_sustained_safe_transit_can_be_peaceful_without_an_authorized_corridor():
    model, found = simulate(lambda t: (100 + 10 * t, 100, 10, 0))
    assert found[-1].cls == 'peaceful'
    assert all(c.cls != 'friendly' for c in found)
    assert 'sustained_safe_transit' in model.explain('opaque')['reasons']


def test_a_single_protected_area_crossing_does_not_establish_hostile_intent():
    _, found = simulate(lambda t: (200 + 10 * t, 500, 10, 0), duration=60)
    assert 'suspicious' in {c.cls for c in found}
    assert all(c.cls != 'hostile' for c in found)


def test_low_quality_motion_stays_unknown_instead_of_accusing_a_silent_object():
    _, found = simulate(lambda t: (200 + 10 * t, 500, 10, 0), sigma=100)
    assert all(c.cls == 'unknown' for c in found)


def test_persistent_loiter_is_different_from_an_ordinary_crossing():
    _, loiter = simulate(lambda t: (500, 500, 0, 0))
    assert loiter[-1].cls == 'hostile'
    assert all(c.cls != 'hostile' for c in loiter if c.t < 18)


def test_sustained_history_is_required_before_peaceful_and_new_risk_revokes_it():
    def path(t):
        if t < 25:
            return (250 + 10 * t, 100, 10, 0)
        if t < 65:
            return (500, 100 + 10 * (t - 25), 0, 10)
        return (500, 500, 0, 0)
    _, found = simulate(path, duration=95)
    assert any(c.cls == 'peaceful' for c in found if c.t < 25)
    assert all(c.cls != 'peaceful' for c in found if 60 <= c.t <= 65)
    assert found[-1].cls == 'hostile'


def test_velocity_noise_does_not_make_a_consistent_transit_erratic():
    def path(t):
        return (100 + 10 * t + math.sin(7 * t), 100 + math.cos(5 * t),
                10 + 3 * math.sin(11 * t), 3 * math.cos(9 * t))
    model, found = simulate(path)
    assert all(c.cls == 'peaceful' for c in found if c.t >= 22)
    assert model.explain('opaque')['pattern'] == 'transit'


@pytest.mark.parametrize('noisy', [False, True])
def test_consistent_offsite_orbit_is_peaceful_throughout_its_cycle(noisy):
    def path(t):
        a, noise = t / 6, int(noisy)
        return (500 + 50 * math.cos(a), 850 + 50 * math.sin(a),
                -50 / 6 * math.sin(a) + noise * 2 * math.sin(11 * t),
                50 / 6 * math.cos(a) + noise * 2 * math.cos(9 * t))
    model, found = simulate(path, duration=65)
    assert all(c.cls == 'peaceful' for c in found if c.t >= 25)
    assert model.explain('opaque')['pattern'] == 'orbit'
    assert 'consistent_safe_orbit' in model.explain('opaque')['reasons']


def test_repeated_boundary_intrusions_need_multiple_observed_entries():
    def path(t):
        return (650 + 35 * math.cos(t / 2), 500, -17.5 * math.sin(t / 2), 0)
    model, found = simulate(path, duration=20)
    assert any(c.cls == 'suspicious' for c in found)
    first_hostile = next(c for c in found if c.cls == 'hostile')
    assert first_hostile.t >= 15  # a second complete outside-to-inside entry
    assert 'repeated_protected_intrusions' in model.explain('opaque')['reasons']


def test_association_jump_discards_the_previous_objects_peaceful_history():
    model = AutomaticEstimator(BehaviorConfig.for_area([500, 500]))
    for k in range(51):
        t = k / 2
        result = model.update(t, [TrackState('opaque', t, (100 + 10*t, 100, 60), (10, 0, 0), 2)], [])
    assert result[0].cls == 'peaceful'
    result = model.update(25.5, [TrackState('opaque', 25.5, (500, 500, 60), (0, 0, 0), 2)], [])
    assert result[0].cls == 'unknown'
    assert model.explain('opaque')['observed_s'] == 0
