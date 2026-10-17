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

# ---- clutter: birds and vehicles are real objects without beacons, and not threats

CLUTTER = {"false_alarms_per_min": 4, "birds": 2, "vehicles": 2}


def with_clutter():
    return clean(make_scenario(clutter=CLUTTER))


def oracle(threat_for):
    """A stand-in for a behaviour module that knows the answer (test only): threat_for maps a track id to evidence."""
    return lambda tr: threat_for(tr.track_id)


def test_the_adapter_makes_tracks_for_clutter_and_none_of_them_has_a_beacon():
    from friend_foe.scenario_adapter import frames_from_scenario
    scenario = with_clutter()
    ids, beacon_ids = set(), set()
    for _, tracks, beacons in frames_from_scenario(scenario):
        ids |= {tr.track_id for tr in tracks}
        beacon_ids |= {b.friend_id for b in beacons}
    assert {"B1", "B2", "V1", "V2"} <= ids
    assert not beacon_ids & {"B1", "B2", "V1", "V2"}


def test_a_scenario_without_clutter_scores_zero_on_clutter():
    m = evaluate(clean(make_scenario()))
    assert m.clutter_flagged_frac == 0.0 and m.requests_on_clutter == 0 and m.clutter_peaceful_frac == 0.0


def test_without_behaviour_evidence_clutter_looks_like_a_hostile_and_drones_are_sent_at_it():
    m = evaluate(with_clutter())
    assert m.clutter_flagged_frac > 0.5 and m.requests_on_clutter > 0
    assert m.clutter_peaceful_frac == 0.0 and m.hostile_as_peaceful_frac == 0.0


def test_a_good_behaviour_module_saves_the_drones_and_keeps_the_hostiles():
    good = oracle(lambda tid: -0.5 if tid[0] in "BV" else (+0.5 if tid[0] == "H" else 0.0))
    m = evaluate(with_clutter(), threat_llr=good)
    assert m.clutter_peaceful_frac > 0.8 and m.requests_on_clutter == 0
    assert m.hostile_as_peaceful_frac == 0.0 and m.hostiles_never_flagged == 0 and m.requests_on_friendlies == 0


def test_a_wrong_behaviour_module_is_caught_by_the_hostile_as_peaceful_metric():
    wrong = oracle(lambda tid: -0.5 if tid[0] in "BVH" else 0.0)
    m = evaluate(with_clutter(), threat_llr=wrong)
    assert m.hostile_as_peaceful_frac > 0.8 and m.hostiles_never_flagged > 0