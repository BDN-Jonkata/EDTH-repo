"""Tests for the estimator evaluation."""

from friend_foe.estimator import EstimatorConfig
from friend_foe.evaluate import evaluate
from friend_foe.test_scenario_adapter import make_scenario


def clean(scenario):
    scenario["degradations"]["network"].update({"enabled": True, "loss": 0.0, "latency_ms": [0, 0]})
    scenario["degradations"]["clock"]["enabled"] = False
    return scenario


def test_clean_run_flags_every_hostile_and_no_friendly():
    m = evaluate(clean(make_scenario()))
    assert m.friendlies_flagged == 0 and m.friendly_flag_frac == 0.0
    assert m.hostile_as_friendly_frac == 0.0 and m.hostiles_never_flagged == 0
    assert m.friendlies_never_confirmed == 0 and m.requests_on_friendlies == 0
    assert 0 < m.time_to_friendly_s < 5 and 0 < m.time_to_flag_s < 10 and m.requests > 0


def test_no_beacons_at_all_flags_friendlies_too():
    scenario = clean(make_scenario())
    scenario["degradations"]["network"]["loss"] = 1.0
    m = evaluate(scenario)
    assert m.friendlies_never_confirmed == len(scenario["friendlies"])
    assert m.hostile_as_friendly_frac == 0.0


def test_evaluation_is_reproducible():
    scenario = make_scenario()
    assert evaluate(scenario, seed=3) == evaluate(scenario, seed=3)


def test_a_stricter_config_changes_the_result():
    scenario = clean(make_scenario())
    slow = evaluate(scenario, EstimatorConfig(min_updates=40))
    fast = evaluate(scenario, EstimatorConfig(min_updates=5))
    assert slow.time_to_flag_s > fast.time_to_flag_s