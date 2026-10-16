"""End-to-end check on scenarios made by the seeder generator."""

import json
from pathlib import Path

from common.seeder_import import ensure_seeder_on_path
from friend_foe.estimator import FriendFoeEstimator
from friend_foe.investigation import InvestigationTrigger
from friend_foe.scenario_adapter import frames_from_scenario
from sensors.quality import modules_in_scenario
from sensors.weather import weather_from_scenario

ensure_seeder_on_path()
import scenario as seeder_scenario  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def make_scenario(preset="medium", **env):
    config = json.loads((ROOT / "scenarios" / f"{preset}.json").read_text(encoding="utf-8"))
    config.setdefault("environment", {}).update(env)
    scenario, _truth = seeder_scenario.generate(config)
    return scenario


def run(scenario):
    est = FriendFoeEstimator()
    trigger = InvestigationTrigger(weather_from_scenario(scenario), modules_in_scenario(scenario))
    classes, requests = {}, []
    for t, tracks, beacons in frames_from_scenario(scenario):
        found = est.update(t, tracks, beacons)
        classes.update({c.track_id: c.cls for c in found})
        requests += trigger.update(t, found, tracks)
    return classes, requests


def test_friendlies_friendly_hostiles_suspicious():
    scenario = make_scenario()
    classes, _ = run(scenario)
    friendlies = [f["id"] for f in scenario["friendlies"]]
    hostiles = [t["id"] for t in scenario["targets"]]
    assert all(classes[i] == "friendly" for i in friendlies)
    assert all(classes[i] == "suspicious" for i in hostiles)


def test_no_friendly_is_ever_investigated():
    scenario = make_scenario()
    _, requests = run(scenario)
    friendlies = {f["id"] for f in scenario["friendlies"]}
    assert requests and not any(r["track_id"] in friendlies for r in requests)


def test_hostiles_stay_suspicious_when_beacons_are_lost():
    scenario = make_scenario()
    scenario["degradations"]["network"]["loss"] = 0.6
    classes, _ = run(scenario)
    assert all(classes[t["id"]] != "friendly" for t in scenario["targets"])


def test_fog_shrinks_the_requested_standoff():
    clear = run(make_scenario(weather="clear", time_of_day="day"))[1][0]
    fog = run(make_scenario(weather="fog", time_of_day="night"))[1][0]
    assert fog["standoff_m"] <= clear["standoff_m"]
    assert fog["weather_confidence"] < clear["weather_confidence"]


def test_adapter_is_deterministic_for_a_seed():
    scenario = make_scenario()
    a = [(t, [x.position for x in tr]) for t, tr, _ in frames_from_scenario(scenario, seed=1)]
    b = [(t, [x.position for x in tr]) for t, tr, _ in frames_from_scenario(scenario, seed=1)]
    assert a == b
