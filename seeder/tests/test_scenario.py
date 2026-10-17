"""Tests for the scenario generator. Run from the repo root:  python -m unittest discover -s seeder/tests -v"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "seeder"))

import catalog as cat  # noqa: E402
import scenario as sc  # noqa: E402

PRESETS = sorted((ROOT / "scenarios").glob("*.json"))


def load(name):
    return json.loads((ROOT / "scenarios" / (name + ".json")).read_text(encoding="utf-8"))


class Generator(unittest.TestCase):
    def test_all_presets_generate(self):
        self.assertGreaterEqual(len(PRESETS), 4)
        for p in PRESETS:
            scenario, truth = sc.generate(json.loads(p.read_text(encoding="utf-8")))
            self.assertEqual(scenario["schema"], sc.SCHEMA)
            self.assertEqual(len(scenario["friendlies"]), 5)
            self.assertEqual(len(scenario["ground"]), 2)
            for role in ("hostile", "benign"):
                self.assertEqual(sum(o["kind"] == role for o in truth["objects"]),
                                 sum(t.get("role", "hostile") == role for t in scenario["targets"]))

    def test_busy_has_genuinely_mixed_traffic_and_only_the_fleet_has_beacons(self):
        scene, truth = sc.generate(load("busy"))
        self.assertEqual(len(scene["targets"]), 8)
        self.assertEqual(sum(t["role"] == "benign" for t in scene["targets"]), 4)
        self.assertEqual(sum(t["role"] == "hostile" for t in scene["targets"]), 4)
        self.assertEqual(sum(o["kind"] == "hostile" for o in truth["objects"]), 4)
        self.assertEqual(sum(o["kind"] == "benign" for o in truth["objects"]), 4)
        self.assertEqual({e['id'] for e in truth['events'] if e['type'] == 'enter'},
                         {t['id'] for t in scene['targets']})
        self.assertTrue(all(e['a'].startswith('H') and e['b'].startswith('H')
                            for e in truth['events'] if e['type'] == 'crossing'))
        from friend_foe.scenario_adapter import frames_from_scenario
        fleet = {f["id"] for f in scene["friendlies"]}
        for _, _, beacons in frames_from_scenario(scene):
            self.assertTrue(all(b.friend_id in fleet for b in beacons))

    def test_mixed_traffic_is_reproducible_and_keeps_existing_streams(self):
        config = load("medium")
        original, _ = sc.generate(config)
        config["targets"]["count"] = 5
        config["targets"]["benign_count"] = 2
        mixed, _ = sc.generate(config)
        self.assertEqual(original["targets"], mixed["targets"][:3])
        self.assertEqual(original["friendlies"], mixed["friendlies"])
        self.assertEqual(sc.generate(config), sc.generate(config))

    def test_benign_count_is_validated(self):
        for value in (-1, 1.5, True, 9, None, '4'):
            config = load("busy")
            config["targets"]["benign_count"] = value
            with self.assertRaisesRegex(ValueError, 'benign_count'):
                sc.generate(config)

    def test_behavior_demo_is_a_boolean_switch(self):
        config = load("busy")
        config["targets"]["behavior_demo"] = "false"
        with self.assertRaisesRegex(ValueError, 'behavior_demo'):
            sc.generate(config)

    def test_explicit_benign_role_reaches_scoring_truth(self):
        config = load("easy")
        config["targets"] = [{"id": "opaque", "role": "benign", "waypoints": [[0, 100, 100], [120, 900, 100]]}]
        scene, truth = sc.generate(config)
        self.assertEqual(scene["targets"][0]["role"], 'benign')
        self.assertEqual(next(o for o in truth["objects"] if o["id"] == 'opaque')["kind"], 'benign')
        config["targets"][0]["role"] = 'peaceful'  # an estimated flag is not a scoring role
        with self.assertRaisesRegex(ValueError, 'role'):
            sc.generate(config)

    def test_same_seed_is_identical(self):
        a = sc.generate(load("hard"))
        b = sc.generate(load("hard"))
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_different_seed_changes_targets(self):
        cfg = load("medium")
        a, _ = sc.generate(cfg)
        cfg["seed"] = 5
        b, _ = sc.generate(cfg)
        self.assertNotEqual(a["targets"][0]["waypoints"], b["targets"][0]["waypoints"])
        self.assertEqual(len(a["friendlies"]), len(b["friendlies"]))

    def test_target_streams_are_independent(self):
        # changing the friendly platforms must not move the hostiles
        cfg = load("challenge")
        a, _ = sc.generate(cfg)
        cfg["friendlies"] = {"platforms": ["skydio_x10"] * 5}
        b, _ = sc.generate(cfg)
        self.assertEqual(a["targets"], b["targets"])

    def test_crossing_is_close(self):
        for seed in range(1, 11):
            cfg = load("challenge")
            cfg["seed"] = seed
            _, truth = sc.generate(cfg)
            crossings = [e for e in truth["events"] if e["type"] == "crossing"]
            self.assertEqual(len(crossings), 1, "seed %d" % seed)
            self.assertLess(crossings[0]["sep_m"], 25, "seed %d" % seed)
            self.assertAlmostEqual(crossings[0]["t"], 51, delta=3, msg="seed %d" % seed)

    def test_easy_has_no_crossing(self):
        _, truth = sc.generate(load("easy"))
        self.assertEqual([e for e in truth["events"] if e["type"] == "crossing"], [])

    def test_hostiles_stay_in_area_and_speed_is_sane(self):
        for seed in range(1, 8):
            cfg = load("hard")
            cfg["seed"] = seed
            _, truth = sc.generate(cfg)
            for o in truth["objects"]:
                for t, x, y, vx, vy in o["samples"]:
                    self.assertTrue(0 <= x <= 1000 and 0 <= y <= 1000, (o["id"], t, x, y))
                    self.assertLess((vx * vx + vy * vy) ** 0.5, 40)

    def test_friendly_patrols_stay_in_area(self):
        scenario, _ = sc.generate(load("challenge"))
        for f in scenario["friendlies"]:
            lp = f["loop"]
            self.assertGreaterEqual(lp["cx"] - lp["R"], 0)
            self.assertLessEqual(lp["cx"] + lp["R"], 1000)
            self.assertGreaterEqual(lp["cy"] - lp["R"], 0)
            self.assertLessEqual(lp["cy"] + lp["R"], 1000)

    def test_truth_is_kept_out_of_the_scenario(self):
        scenario, truth = sc.generate(load("challenge"))
        text = json.dumps(scenario)
        self.assertNotIn('"samples"', text)
        self.assertNotIn('"events"', text)
        self.assertIn("samples", truth["objects"][0])

    def test_truth_sampling(self):
        scenario, truth = sc.generate(load("challenge"), truth_dt=0.5)
        friendly = [o for o in truth["objects"] if o["kind"] == "friendly"][0]
        self.assertEqual(len(friendly["samples"]), int(scenario["duration_s"] / 0.5) + 1)

    def test_sensors_resolved_from_catalog(self):
        scenario, _ = sc.generate(load("challenge"))
        kinds = {s["kind"] for s in scenario["friendlies"][0]["sensors"]}
        self.assertEqual(kinds, {"eo_camera", "microphone"})  # mini4pro: camera + mic (gnss/imu are not detection sensors)

    def test_sensor_set_switch(self):
        cfg = load("challenge")
        cfg["sensor_set"] = {"enabled_kinds": ["eo_camera", "microphone"]}
        scenario, _ = sc.generate(cfg)
        for node in scenario["friendlies"] + scenario["ground"]:
            for s in node["sensors"]:
                self.assertIn(s["kind"], ("eo_camera", "microphone"))

    def test_explicit_targets(self):
        cfg = load("challenge")
        cfg["targets"] = [{"id": "X1", "waypoints": [[5, 100, 100], [60, 600, 600], [90, 900, 700]]}]
        scenario, truth = sc.generate(cfg)
        self.assertEqual([t["id"] for t in scenario["targets"]], ["X1"])
        self.assertEqual(sum(o["kind"] == "hostile" for o in truth["objects"]), 1)

    def test_hover_has_zero_speed(self):
        cfg = load("easy")
        cfg["targets"] = {"count": 1, "motion": "hover", "crossing": {"enabled": False}}
        _, truth = sc.generate(cfg)
        speeds = [(vx * vx + vy * vy) ** 0.5 for _, _, _, vx, vy in truth["objects"][-1]["samples"]]
        self.assertLess(min(speeds), 0.5)


class Commands(unittest.TestCase):
    def test_commands_are_sorted_and_marked_in_truth(self):
        cfg = load("easy")
        cfg["commands"] = [{"t": 30, "drone_id": "F1", "command": "return_to_patrol"},
                           {"t": 10, "drone_id": "F1", "command": "goto", "target": [500, 500], "face_target": [600, 600]}]
        scenario, truth = sc.generate(cfg)
        self.assertEqual([c["t"] for c in scenario["commands"]], [10, 30])
        self.assertTrue(truth["scripted_baseline_only"])

    def test_no_commands_by_default(self):
        scenario, truth = sc.generate(load("easy"))
        self.assertEqual(scenario["commands"], [])
        self.assertNotIn("scripted_baseline_only", truth)

    def test_every_uas_has_flight_limits(self):
        for p in cat.load_catalog()["platforms"]:
            if p["platform"] == "uas":
                self.assertEqual(sorted(p["spec"]["flight"]), ["assumed", "max_accel_mps2", "max_speed_mps", "max_turn_dps"], p["id"])


def with_clutter(name, birds=3, vehicles=2):
    cfg = load(name)
    cfg["environment"] = dict(cfg.get("environment", {}), clutter={"false_alarms_per_min": 3, "birds": birds, "vehicles": vehicles})
    return cfg


class Clutter(unittest.TestCase):
    def test_none_unless_the_preset_asks_for_them(self):
        for p in PRESETS:
            config = json.loads(p.read_text(encoding="utf-8"))
            asked = config.get("environment", {}).get("clutter", {})
            if asked.get("birds") or asked.get("vehicles"):
                continue
            scenario, truth = sc.generate(config)
            self.assertEqual(scenario["clutter"], [], p.stem)
            self.assertFalse([o for o in truth["objects"] if o["kind"] == "clutter"], p.stem)

    def test_counts_types_and_no_rf(self):
        scenario, _ = sc.generate(with_clutter("challenge"))
        self.assertEqual([c["id"] for c in scenario["clutter"]], ["B1", "B2", "B3", "V1", "V2"])
        for c in scenario["clutter"]:
            self.assertEqual(c["role"], "clutter")
            self.assertIn(c["type"], sc.CLUTTER_KINDS)
            self.assertFalse(c["emits"])
            self.assertEqual(c["signature"]["rf"], 0)
        self.assertTrue(all(c["altitude_m"] <= 2 for c in scenario["clutter"] if c["type"] == "vehicle"), "vehicles stay on the ground")

    def test_does_not_move_the_hostiles_or_friendlies(self):
        for name in ("easy", "challenge"):
            plain, _ = sc.generate(load(name))
            cluttered, _ = sc.generate(with_clutter(name))
            self.assertEqual(plain["targets"], cluttered["targets"], name)
            self.assertEqual(plain["friendlies"], cluttered["friendlies"], name)

    def test_same_seed_is_identical(self):
        a, b = sc.generate(with_clutter("hard")), sc.generate(with_clutter("hard"))
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_truth_lists_clutter_apart_from_hostiles(self):
        scenario, truth = sc.generate(with_clutter("medium"))
        clutter = [o for o in truth["objects"] if o["kind"] == "clutter"]
        self.assertEqual([o["id"] for o in clutter], [c["id"] for c in scenario["clutter"]])
        self.assertTrue(all(o["samples"] and o["type"] in sc.CLUTTER_KINDS for o in clutter))
        self.assertFalse([e for e in truth["events"] if e.get("id", "").startswith(("B", "V"))], "events are about hostiles only")
        first = clutter[0]["samples"][0]
        self.assertEqual(first[1:3], [round(v, 1) for v in sc._target_pos(scenario["clutter"][0], first[0])], "same motion as hostiles")


class NewFeaturePresets(unittest.TestCase):
    def test_dusk_has_a_sky_with_a_sunset_and_a_fog_event(self):
        env = sc.generate(load("dusk"), truth_dt=5.0)[0]["environment"]
        self.assertEqual(env["sky"]["time_scale"], 60)
        self.assertTrue(env["weather_events"][0]["zone"])
        self.assertGreater(env["clutter"]["birds"], 0)

    def test_jammed_has_zones_and_a_bandwidth_cap(self):
        net = sc.generate(load("jammed"), truth_dt=5.0)[0]["degradations"]["network"]
        self.assertEqual(net["bandwidth_kbps"], 32)
        self.assertEqual(len(net["jamming_zones"]), 2)


class VerificationWorksheet(unittest.TestCase):
    def test_lists_exactly_the_unverified_entries(self):
        import unverified
        catalog = cat.load_catalog()
        text = unverified.worksheet(catalog)
        for m in catalog["modules"]:
            self.assertEqual("### %s (" % m["id"] in text, not m.get("verified"), m["id"])
        for p in catalog["platforms"]:
            self.assertEqual("### %s" % p["id"] + chr(10) in text, not p.get("verified"), p["id"])


class Validation(unittest.TestCase):
    def check(self, mutate, text):
        cfg = load("challenge")
        mutate(cfg)
        with self.assertRaises(ValueError) as cm:
            sc.generate(cfg)
        self.assertIn(text, str(cm.exception))

    def test_rejects_unknown_friendly_platform(self):
        self.check(lambda c: c.update(friendlies={"platforms": ["nope"]}), "not a UAS")

    def test_rejects_ground_platform_on_drone(self):
        self.check(lambda c: c.update(friendlies={"platforms": ["gs_radar_rf"]}), "not a UAS")

    def test_rejects_seed_outside_set(self):
        self.check(lambda c: c.update(seed=500, seed_set="test"), "outside the test seed set")

    def test_rejects_bad_loss(self):
        self.check(lambda c: c.update(degradations={"network": {"loss": 1.5}}), "loss must be between")

    def test_rejects_bad_weather(self):
        self.check(lambda c: c.update(environment={"weather": "snow"}), "weather must be clear or")

    def test_accepts_combined_weather_events_and_sky(self):
        cfg = load("challenge")
        cfg.setdefault("environment", {}).update(
            weather="fog:0.5+wind",
            weather_events=[{"weather": "rain", "t_start": 40, "t_end": 80, "zone": {"x": 500, "y": 500, "radius_m": 100}}],
            sky={"date": "2026-06-21", "hour": 20.5, "lat": 45.0, "lon": 0.0, "time_scale": 60})
        env = sc.generate(cfg)[0]["environment"]
        self.assertEqual(env["weather"], "fog:0.5+wind")
        self.assertEqual(env["weather_events"][0]["zone"]["radius_m"], 100)
        self.assertEqual(env["sky"]["time_scale"], 60)

    def test_weather_does_not_change_the_paths(self):
        plain, fogged = load("challenge"), load("challenge")
        fogged.setdefault("environment", {}).update(weather="fog+rain", sky={"date": "2026-12-21", "hour": 17, "lat": 55, "lon": 0})
        self.assertEqual(sc.generate(plain)[0]["targets"], sc.generate(fogged)[0]["targets"])

    def test_rejects_bad_weather_forms(self):
        for text in ("fog+fog", "fog:0", "fog:1.5", "clear+fog", "fog+"):
            self.check(lambda c, text=text: c.setdefault("environment", {}).update(weather=text), "weather")

    def test_rejects_bad_events(self):
        self.check(lambda c: c.setdefault("environment", {}).update(weather_events=[{"t_start": 3}]), "missing")
        self.check(lambda c: c.setdefault("environment", {}).update(weather_events=[{"weather": "fog", "t_start": 9, "t_end": 5}]), "end after")
        self.check(lambda c: c.setdefault("environment", {}).update(weather_events=[{"weather": "fog", "zone": {"x": 1}}]), "missing")

    def test_rejects_a_sky_without_a_place_or_date(self):
        self.check(lambda c: c.setdefault("environment", {}).update(sky={"date": "2026-06-21", "hour": 20}), "sky needs")
        self.check(lambda c: c.setdefault("environment", {}).update(sky={"date": "2026-13-45", "hour": 20, "lat": 1, "lon": 1}), "sky")
        self.check(lambda c: c.setdefault("environment", {}).update(sky={"date": "2026-06-21", "hour": 24, "lat": 1, "lon": 1}), "hour")

    def test_accepts_and_passes_on_jamming_zones(self):
        cfg = load("challenge")
        zone = {"x": 500, "y": 500, "radius_m": 150, "loss": 0.8, "t_start": 40, "t_end": 80, "rf_noise_mult": 3}
        cfg["degradations"] = {"network": {"jamming_zones": [zone]}}
        self.assertEqual(sc.generate(cfg)[0]["degradations"]["network"]["jamming_zones"], [zone])

    def test_jamming_does_not_change_the_paths(self):
        plain, jammed = load("challenge"), load("challenge")
        jammed["degradations"] = {"network": {"jamming_zones": [{"x": 1, "y": 2, "radius_m": 50, "loss": 1}]}}
        self.assertEqual(sc.generate(plain)[0]["targets"], sc.generate(jammed)[0]["targets"])

    def test_rejects_bad_jamming_zones(self):
        def zones(*z):
            return lambda c: c.setdefault("degradations", {}).update(network={"jamming_zones": list(z)})
        self.check(zones({"x": 1, "y": 2, "radius_m": 0, "loss": 0.5}), "radius_m must be positive")
        self.check(zones({"x": 1, "y": 2, "radius_m": 5, "loss": 1.5}), "loss must be between")
        self.check(zones({"x": 1, "y": 2, "radius_m": 5, "loss": 0.5, "t_start": 9, "t_end": 5}), "t_end must be after")
        self.check(zones({"x": 1, "y": 2, "radius_m": 5, "loss": 0.5, "rf_noise_mult": 0.5}), "at least 1")
        self.check(zones({"x": 1}), "is required")
        self.check(lambda c: c.setdefault("degradations", {}).update(network={"jamming_zones": "all"}), "must be a list")

    def test_bandwidth_cap_is_null_or_positive(self):
        for kbps in (None, 8, 0.5):
            cfg = load("challenge")
            cfg["degradations"] = {"network": {"bandwidth_kbps": kbps}}
            self.assertEqual(sc.generate(cfg)[0]["degradations"]["network"]["bandwidth_kbps"], kbps)
        for kbps in (0, -5, "fast", True):
            self.check(lambda c, kbps=kbps: c.setdefault("degradations", {}).update(network={"bandwidth_kbps": kbps}), "bandwidth_kbps")

    def test_rejects_ground_outside_area(self):
        self.check(lambda c: c.update(ground=[{"id": "G", "platform": "gs_radar_rf", "position": [2000, 5]}]), "outside the area")

    def test_rejects_command_to_unknown_drone(self):
        self.check(lambda c: c.update(commands=[{"t": 5, "drone_id": "F9", "command": "hold"}]), "drone_id must be one of")

    def test_rejects_goto_outside_area(self):
        self.check(lambda c: c.update(commands=[{"t": 5, "drone_id": "F1", "command": "goto", "target": [1500, 5]}]), "target must be")

    def test_rejects_unknown_command(self):
        self.check(lambda c: c.update(commands=[{"t": 5, "drone_id": "F1", "command": "dance"}]), "command must be one of")

    def test_rejects_bad_clutter_counts(self):
        self.check(lambda c: c.update(environment={"clutter": {"birds": -1}}), "clutter.birds must be")
        self.check(lambda c: c.update(environment={"clutter": {"vehicles": 11}}), "clutter.vehicles must be")
        self.check(lambda c: c.update(environment={"clutter": {"birds": True}}), "clutter.birds must be")

    def test_seed_sets(self):
        self.assertEqual(sc.seed_for("tuning", 0), 1)
        self.assertEqual(sc.seed_for("test", 99), 1099)
        with self.assertRaises(ValueError):
            sc.seed_for("test", 100)


if __name__ == "__main__":
    unittest.main()
