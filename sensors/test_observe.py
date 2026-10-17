"""Tests for the observation source and the beacon source."""

import math
import unittest

from common.codec import decode, encode
from sensors.beacons import BeaconSource
from sensors.native import compass_deg, math_rad
from sensors.observe import ObservationSource
from sensors.quality import load_modules

MODULES = load_modules()


def scenario(sensors, targets=None, weather="clear", friendlies=None, enabled=("eo_camera", "radar", "rf_receiver", "microphone")):
    """One ground sensor at (0, 0) looking east, and hostiles on straight paths."""
    return {
        "friendlies": friendlies or [], "clutter": [],
        "ground": [{"id": "GS1", "platform": "x", "position": [0, 0], "heading_deg": 90.0, "sensors": sensors}],
        "targets": targets or [],
        "sensor_set": {"enabled_kinds": list(enabled)},
        "environment": {"weather": weather, "time_of_day": "day", "clutter": {"false_alarms_per_min": 0}},
        "beacon": {"enabled": True, "rate_hz": 2, "pos_sigma_m": 3},
        "degradations": {"clock": {"enabled": False}, "pose": {"enabled": False}, "network": {"enabled": False}},
    }


def hostile(x, y, signature=None, emits=True, hid="H1"):
    return {"id": hid, "waypoints": [[0.0, x, y], [100.0, x, y]], "wobble_m": 0, "phase": 0, "altitude_m": 60.0,
            "signature": signature or {}, "emits": emits}


RADAR = [{"module": "radar_mmwave_small", "kind": "radar"}]
RF = [{"module": "rf_sdr_receiver", "kind": "rf_receiver"}]
EYE = [{"module": "eo_visible_basic", "kind": "eo_camera"}]
SURE = {"radar": 5.0, "eo": 5.0, "rf": 5.0, "acoustic": 5.0, "thermal": 5.0}   # a detection probability of 1 near the sensor


def collect(sc, seconds=10.0, seed=1):
    src, out = ObservationSource(sc, seed, MODULES), []
    for k in range(int(seconds * 10)):
        out += src.at(k * 0.1)
    return out


class TestAngles(unittest.TestCase):
    def test_compass_and_maths_angles_convert_both_ways(self):
        self.assertAlmostEqual(compass_deg(0.0), 90.0)             # east
        self.assertAlmostEqual(compass_deg(math.pi / 2), 0.0)      # north
        self.assertAlmostEqual(math_rad(compass_deg(1.234)), 1.234)


class TestDetection(unittest.TestCase):
    def test_radar_reports_range_azimuth_and_doppler_near_the_truth(self):
        obs = collect(scenario(RADAR, [hostile(200, 0, SURE)]))
        self.assertTrue(obs)
        o = obs[0]
        self.assertEqual((o["kind"], o["sensor_type"]), ("range_bearing", "radar"))
        self.assertAlmostEqual(o["value"]["range_m"], 200, delta=40)
        self.assertAlmostEqual(o["value"]["azimuth_deg"], 90, delta=15)
        self.assertEqual(o["cov_fields"], ["range_m", "azimuth_deg", "radial_mps"])

    def test_a_camera_reports_bearing_and_elevation_but_never_range(self):
        obs = collect(scenario(EYE, [hostile(100, 0, SURE)]))
        self.assertTrue(obs)
        self.assertEqual(set(obs[0]["value"]), {"bearing_deg", "elevation_deg", "class_hint"})

    def test_out_of_range_and_outside_the_field_of_view_are_not_seen(self):
        self.assertEqual(collect(scenario(RADAR, [hostile(900, 0, SURE)])), [])      # beyond 400 m
        self.assertEqual(collect(scenario(RADAR, [hostile(-200, 0, SURE)])), [])     # behind a forward radar
        self.assertEqual(collect(scenario(RADAR, [hostile(5, 0, SURE)])), [])        # inside the minimum range

    def test_a_silent_hostile_is_invisible_to_rf_but_not_to_radar(self):
        quiet = hostile(100, 0, SURE, emits=False)
        self.assertEqual(collect(scenario(RF, [quiet])), [])
        self.assertTrue(collect(scenario(RADAR, [quiet])))

    def test_a_zero_signature_is_never_seen_and_a_strong_one_is_seen_more(self):
        self.assertEqual(collect(scenario(RADAR, [hostile(200, 0, {"radar": 0.0})]), 30), [])
        weak = collect(scenario(RADAR, [hostile(300, 0, {"radar": 0.3})]), 30)
        strong = collect(scenario(RADAR, [hostile(300, 0, {"radar": 1.5})]), 30)
        self.assertGreater(len(strong), len(weak))

    def test_fog_costs_a_camera_detections(self):
        clear = collect(scenario(EYE, [hostile(120, 0, SURE)]), 30)
        fog = collect(scenario(EYE, [hostile(120, 0, SURE)], weather="fog"), 30)
        self.assertLess(len(fog), len(clear))

    def test_two_targets_inside_one_radar_cell_merge_into_one_detection(self):
        pair = [hostile(200, 0, SURE, hid="H1"), hostile(205, 1, SURE, hid="H2")]
        apart = [hostile(200, 0, SURE, hid="H1"), hostile(200, 80, SURE, hid="H2")]
        self.assertLess(len(collect(scenario(RADAR, pair), 20)), len(collect(scenario(RADAR, apart), 20)))


class TestMessages(unittest.TestCase):
    def test_same_seed_same_observations_and_unique_message_ids(self):
        sc = scenario(RADAR + EYE, [hostile(100, 0, SURE)])
        a, b = collect(sc, 10, seed=7), collect(sc, 10, seed=7)
        self.assertEqual(a, b)
        ids = [m["header"]["msg_id"] for m in a]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_observation_survives_the_codec_and_has_a_diagonal_covariance(self):
        for o in collect(scenario(RADAR + EYE, [hostile(100, 0, SURE)]), 5):
            self.assertEqual(decode(encode(o)), o)
            n = len(o["cov_fields"])
            self.assertEqual(len(o["covariance"]), n)
            self.assertTrue(all(o["covariance"][i][j] == 0 for i in range(n) for j in range(n) if i != j))

    def test_beacons_share_the_message_counter_with_observations(self):
        friendly = {"id": "F1", "platform": "x", "altitude_m": 60, "sensors": EYE,
                    "loop": {"cx": 100, "cy": 100, "R": 50, "v": 10, "dir": 1, "th0": 0.0}}
        sc = scenario([], [hostile(120, 100, SURE)], friendlies=[friendly])
        seq = {}
        obs, beacons = ObservationSource(sc, 1, MODULES, seq), BeaconSource(sc, 2, seq)
        messages = []
        for k in range(50):
            messages += obs.at(k * 0.1) + beacons.at(k * 0.1)
        f1 = [m["header"]["seq"] for m in messages if m["header"]["source_id"] == "F1"]
        self.assertEqual(f1, list(range(1, len(f1) + 1)))
        self.assertTrue(any(m["type"] == "friendly_beacon" for m in messages))


class TestBeacons(unittest.TestCase):
    def test_rate_noise_and_clock(self):
        friendly = {"id": "F1", "platform": "x", "altitude_m": 60, "sensors": [],
                    "loop": {"cx": 100, "cy": 100, "R": 50, "v": 10, "dir": 1, "th0": 0.0}}
        sc = scenario([], friendlies=[friendly])
        sc["degradations"]["clock"] = {"enabled": True, "offset_ms": [100, 100], "drift_ppm": 0}
        src = BeaconSource(sc, 3)
        out = [m for k in range(100) for m in src.at(k * 0.1)]
        self.assertEqual(len(out), 20)                       # 2 Hz for 10 s
        self.assertAlmostEqual(abs(out[0]["header"]["t_sent"] - 0.0), 0.1, places=6)   # the drone's clock is 100 ms off
        self.assertEqual(out[0]["covariance"][0][0], 9.0)    # sigma 3 m


if __name__ == "__main__":
    unittest.main()
