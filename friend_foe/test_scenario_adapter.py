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


# ---- degradations: each acts only when `enabled`, and the scenario's numbers are honoured

def beacons_of(scenario, **kw):
    return [b for _, _, bs in frames_from_scenario(scenario, **kw) for b in bs]


def test_network_loss_is_ignored_when_the_network_degradation_is_disabled():
    scenario = make_scenario()
    scenario["degradations"]["network"].update({"enabled": False, "loss": 0.9, "latency_ms": [0, 0]})
    total = len(beacons_of(scenario))
    scenario["degradations"]["network"].update({"enabled": True, "loss": 0.0})
    assert total == len(beacons_of(scenario))


def test_full_loss_delivers_no_beacons_and_partial_loss_some():
    scenario = make_scenario()
    net = scenario["degradations"]["network"]
    net.update({"enabled": True, "loss": 0.0, "latency_ms": [0, 0]})
    everything = len(beacons_of(scenario))
    net["loss"] = 1.0
    assert len(beacons_of(scenario)) == 0
    net["loss"] = 0.5
    assert 0.35 * everything < len(beacons_of(scenario)) < 0.65 * everything


def test_bursty_loss_has_the_configured_average_but_longer_runs():
    import random
    from common.channel import Loss as _Loss

    def run_lengths(burst):
        loss, n = _Loss(random.Random(4), 0.3, burst), 20000
        drops = [loss.drops() for _ in range(n)]
        runs, current = [], 0
        for d in drops:
            if d:
                current += 1
            elif current:
                runs.append(current)
                current = 0
        return sum(drops) / n, sum(runs) / len(runs)

    plain_rate, plain_run = run_lengths(False)
    burst_rate, burst_run = run_lengths(True)
    assert abs(plain_rate - 0.3) < 0.02 and abs(burst_rate - 0.3) < 0.03
    assert burst_run > 2 * plain_run


def test_latency_delays_beacons_and_clock_offset_stamps_them():
    scenario = make_scenario()
    scenario["degradations"]["network"].update({"enabled": True, "loss": 0.0, "latency_ms": [400, 400]})
    scenario["degradations"]["clock"].update({"enabled": True, "offset_ms": [100, 100], "drift_ppm": 0})
    ages = [t - b.t for t, _, bs in frames_from_scenario(scenario) for b in bs]
    assert ages and all(abs(abs(a - 0.4) - 0.1) < 0.51 for a in ages)   # delay 0.4 s +/- 0.1 s offset, plus frame step
    assert max(ages) > 0.4 and min(ages) < 0.6


def test_pose_error_widens_the_honest_sigma():
    scenario = make_scenario()
    scenario["degradations"]["pose"].update({"enabled": True, "position_err_m": 12})
    _, tracks, beacons = next(frames_from_scenario(scenario))
    assert all(tr.pos_sigma > 12 for tr in tracks) and all(b.pos_sigma > 12 for b in beacons)