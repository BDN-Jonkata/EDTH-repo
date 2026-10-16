"""Tests for the scenario generator. Run from the repo root:  python -m unittest discover -s seeder/tests -v"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "seeder"))

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
            self.assertEqual(sum(o["kind"] == "hostile" for o in truth["objects"]), len(scenario["targets"]))

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
                for t, x, y, z, vx, vy in o["samples"]:
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
        speeds = [(vx * vx + vy * vy) ** 0.5 for _, _, _, _, vx, vy in truth["objects"][-1]["samples"]]
        self.assertLess(min(speeds), 0.5)


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
        self.check(lambda c: c.update(environment={"weather": "snow"}), "weather must be")

    def test_rejects_ground_outside_area(self):
        self.check(lambda c: c.update(ground=[{"id": "G", "platform": "gs_radar_rf", "position": [2000, 5]}]), "outside the area")

    def test_seed_sets(self):
        self.assertEqual(sc.seed_for("tuning", 0), 1)
        self.assertEqual(sc.seed_for("test", 99), 1099)
        with self.assertRaises(ValueError):
            sc.seed_for("test", 100)


if __name__ == "__main__":
    unittest.main()
