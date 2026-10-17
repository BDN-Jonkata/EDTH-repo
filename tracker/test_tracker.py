"""Tests for the Kalman filter, the measurement models and the tracker."""

import math
import unittest

from tracker.ekf import identity_like, predict, scalar_update
from tracker.measurement import BEARING, RANGE_BEARING, Measurement, Pose2D, from_observation
from tracker.models import apply_measurement, fix_from_range_bearing, gate_cost, triangulate
from tracker.poses import PoseBook
from tracker.tracker import Tracker, TrackerConfig

RADAR_AT_ORIGIN = Pose2D(0.0, 0.0)


def radar(t, x, y, vx=0.0, vy=0.0, node="F4", sigma_r=3.0, sigma_b=0.02):
    r, az = math.hypot(x, y), math.atan2(y, x)
    return Measurement(RANGE_BEARING, t, node, "radar", RADAR_AT_ORIGIN, 400.0, bearing=az, sigma_bearing=sigma_b,
                       range_m=r, sigma_range=sigma_r, radial_mps=(vx * x + vy * y) / r, sigma_radial=0.5)


def bearing(t, node, pose, x, y, sigma=0.01):
    return Measurement(BEARING, t, node, "eo", pose, 300.0, bearing=math.atan2(y - pose.y, x - pose.x), sigma_bearing=sigma)


class TestFilter(unittest.TestCase):
    def test_a_scalar_update_pulls_the_state_and_shrinks_the_variance(self):
        state, cov = [0.0, 0.0, 0.0, 0.0], identity_like([100.0, 100.0, 100.0, 100.0])
        state, cov = scalar_update(state, cov, 10.0, [1.0, 0.0, 0.0, 0.0], 4.0)
        self.assertGreater(state[0], 9.0)
        self.assertLess(cov[0][0], 4.0)
        self.assertEqual(cov[1][1], 100.0)

    def test_prediction_moves_with_the_velocity_and_adds_uncertainty(self):
        state, cov = predict([0.0, 0.0, 10.0, -5.0], identity_like([1.0, 1.0, 1.0, 1.0]), 2.0, 3.0)
        self.assertEqual(state[:2], [20.0, -10.0])
        self.assertGreater(cov[0][0], 1.0)


class TestModels(unittest.TestCase):
    def test_a_radar_reading_gives_a_fix_where_the_object_is(self):
        x, y, cov = fix_from_range_bearing(radar(0.0, 200.0, 100.0))
        self.assertAlmostEqual(x, 200.0, places=3)
        self.assertAlmostEqual(y, 100.0, places=3)
        self.assertGreater(cov[0][0], 0.0)

    def test_two_bearings_cross_at_the_object_and_parallel_ones_do_not(self):
        a, b = Pose2D(0.0, 0.0), Pose2D(300.0, 0.0)
        fix = triangulate(bearing(0.0, "A", a, 150.0, 150.0), bearing(0.0, "B", b, 150.0, 150.0))
        self.assertAlmostEqual(fix[0], 150.0, places=3)
        self.assertAlmostEqual(fix[1], 150.0, places=3)
        far = Pose2D(0.0, 10.0)
        self.assertIsNone(triangulate(bearing(0.0, "A", a, 250.0, 0.0), bearing(0.0, "B", far, 250.0, 0.0)))

    def test_the_gate_accepts_a_close_reading_and_rejects_a_far_one(self):
        state, cov = [200.0, 100.0, 0.0, 0.0], identity_like([25.0, 25.0, 4.0, 4.0])
        self.assertIsNotNone(gate_cost(state, cov, radar(0.0, 203.0, 102.0)))
        self.assertIsNone(gate_cost(state, cov, radar(0.0, 260.0, 160.0)))

    def test_applying_a_reading_moves_the_state_towards_it(self):
        state, cov = [200.0, 100.0, 0.0, 0.0], identity_like([400.0, 400.0, 25.0, 25.0])
        new, _ = apply_measurement(state, cov, radar(0.0, 210.0, 100.0))
        self.assertGreater(new[0], 200.0)


class TestObservationToMeasurement(unittest.TestCase):
    def test_compass_bearing_becomes_a_maths_angle(self):
        obs = {"kind": "bearing", "t_obs": 1.0, "header": {"source_id": "GS1"}, "sensor_id": "eo",
               "value": {"bearing_deg": 0.0}, "cov_fields": ["bearing_deg"], "covariance": [[1.0]]}
        m = from_observation(obs, Pose2D(0.0, 0.0), {"sim": {"range_m": 150, "noise": {}}})
        self.assertAlmostEqual(m.bearing, math.pi / 2)         # compass north is maths 90 degrees
        self.assertAlmostEqual(m.sigma_bearing, math.radians(1.0))

    def test_the_sensors_own_position_error_widens_a_bearing(self):
        obs = {"kind": "bearing", "t_obs": 1.0, "header": {"source_id": "F1"}, "sensor_id": "eo",
               "value": {"bearing_deg": 0.0}, "cov_fields": ["bearing_deg"], "covariance": [[1.0]]}
        module = {"sim": {"range_m": 100, "noise": {}}}
        exact = from_observation(obs, Pose2D(0.0, 0.0), module).sigma_bearing
        unsure = from_observation(obs, Pose2D(0.0, 0.0, sigma=5.0), module).sigma_bearing   # 5 m at half of 100 m
        self.assertGreater(unsure, exact)
        self.assertAlmostEqual(unsure, math.hypot(math.radians(1.0), 5.0 / 50.0))

    def test_a_single_microphone_gives_a_range_and_other_detections_are_unusable(self):
        mic = {"kind": "detection", "t_obs": 1.0, "header": {"source_id": "F5"}, "sensor_id": "m",
               "value": {"level_db": 50.0}, "cov_fields": ["level_db"], "covariance": [[16.0]]}
        module = {"sim": {"range_m": 60, "noise": {"source_level_db": 90.0}}}
        self.assertAlmostEqual(from_observation(mic, Pose2D(0, 0), module).range_m, 100.0, places=3)
        self.assertIsNone(from_observation(mic, Pose2D(0, 0), {"sim": {"range_m": 60, "noise": {}}}))


class TestTracker(unittest.TestCase):
    def run_radar(self, tracker, seconds, x0=100.0, y0=200.0, vx=10.0, vy=0.0, hz=5):
        out = []
        for k in range(int(seconds * hz)):
            t = k / hz
            out = tracker.step(t, [radar(t, x0 + vx * t, y0 + vy * t, vx, vy)])
        return out

    def test_a_radar_target_is_confirmed_and_followed(self):
        tracker = Tracker()
        tracks = self.run_radar(tracker, 6.0)
        self.assertEqual(len(tracks), 1)
        t = 5.8
        self.assertAlmostEqual(tracks[0].state[0], 100.0 + 10.0 * t, delta=4.0)
        self.assertAlmostEqual(tracks[0].state[2], 10.0, delta=2.0)

    def test_one_bearing_sensor_alone_never_confirms_a_track(self):
        tracker = Tracker()
        pose = Pose2D(0.0, 0.0)
        for k in range(100):
            t = k * 0.2
            self.assertEqual(tracker.step(t, [bearing(t, "A", pose, 150.0, 100.0)]), [])
        self.assertEqual(tracker.tracks, [])

    def test_two_bearing_sensors_start_and_confirm_a_track(self):
        tracker = Tracker()
        a, b = Pose2D(0.0, 0.0), Pose2D(300.0, 0.0)
        tracks = []
        for k in range(60):
            t = k * 0.2
            tracks = tracker.step(t, [bearing(t, "A", a, 150.0, 150.0), bearing(t + 0.01, "B", b, 150.0, 150.0)])
        self.assertEqual(len(tracks), 1)
        self.assertAlmostEqual(tracks[0].state[0], 150.0, delta=5.0)

    def test_a_track_is_dropped_after_its_readings_stop(self):
        tracker = Tracker()
        self.run_radar(tracker, 6.0)
        tracks = []
        for k in range(1, 80):
            tracks = tracker.step(6.0 + k * 0.2, [])
        self.assertEqual(tracks, [])
        self.assertEqual(tracker.tracks, [])

    def test_two_targets_in_one_scan_keep_two_tracks(self):
        tracker = Tracker()
        tracks = []
        for k in range(40):
            t = k * 0.2
            scan = [radar(t, 100.0 + 10 * t, 200.0, 10, 0), radar(t, 100.0 + 10 * t, 300.0, 10, 0)]
            tracks = tracker.step(t, scan)
        self.assertEqual(len(tracks), 2)
        self.assertEqual(len({tr.track_id for tr in tracks}), 2)

    def test_a_beacon_makes_a_friend_track_that_absorbs_a_sensor_reading_of_that_drone(self):
        tracker = Tracker(TrackerConfig())
        beacon = {"friend_id": "F1", "position": [200.0, 100.0, 60.0], "velocity": [0.0, 0.0, 0.0],
                  "covariance": [[9.0, 0, 0], [0, 9.0, 0], [0, 0, 9.0]]}
        tracks = tracker.step(0.0, [], [beacon])
        self.assertEqual([tr.friend_id for tr in tracks], ["F1"])
        for k in range(1, 30):
            tracks = tracker.step(k * 0.2, [radar(k * 0.2, 201.0, 101.0)], [])
        self.assertEqual([tr.friend_id for tr in tracks], ["F1"])      # no second track for the same drone


class TestPoseBook(unittest.TestCase):
    def scenario(self):
        loop = {"cx": 100.0, "cy": 100.0, "R": 50.0, "v": 10.0, "dir": 1, "th0": 0.0}
        return {"ground": [{"id": "GS1", "position": [300, 400]}], "friendlies": [{"id": "F1", "loop": loop}]}

    def test_ground_sensors_use_the_scenario_and_drones_use_their_beacons_then_the_plan(self):
        book = PoseBook(self.scenario())
        self.assertEqual((book.pose("GS1", 5.0).x, book.pose("GS1", 5.0).y), (300, 400))
        book.note_beacon(self.beacon(4.0, 10.0, 20.0))
        p = book.pose("F1", 5.0)
        self.assertEqual((p.x, p.y), (11.0, 22.0))
        self.assertEqual(book.fallbacks, 0)
        book.pose("F1", 60.0)                       # the last beacon is far too old
        self.assertEqual(book.fallbacks, 1)

    def beacon(self, t_sent, x, y, vx=1.0, vy=2.0, sigma=3.0):
        return {"friend_id": "F1", "position": [x, y, 60.0], "velocity": [vx, vy, 0.0], "header": {"t_sent": t_sent},
                "covariance": [[sigma ** 2, 0, 0], [0, sigma ** 2, 0], [0, 0, sigma ** 2]]}

    def test_smoothing_many_noisy_beacons_beats_trusting_the_latest_one(self):
        import random
        rng, book, worst_raw, worst_smooth = random.Random(5), PoseBook(self.scenario()), 0.0, 0.0
        for k in range(60):
            t = k * 0.5
            noisy = self.beacon(t, 100.0 + 10 * t + rng.gauss(0, 3), 50.0 + rng.gauss(0, 3), 10.0, 0.0)
            book.note_beacon(noisy)
            if k >= 20:
                worst_raw += (noisy["position"][0] - (100.0 + 10 * t)) ** 2
                worst_smooth += (book.pose("F1", t).x - (100.0 + 10 * t)) ** 2
        self.assertLess(worst_smooth, worst_raw * 0.6)

    def test_the_pose_carries_its_uncertainty_and_the_plan_fallback_is_vaguer(self):
        book = PoseBook(self.scenario())
        book.note_beacon(self.beacon(4.0, 10.0, 20.0))
        fresh = book.pose("F1", 4.0).sigma
        self.assertGreater(fresh, 0.0)
        self.assertGreater(book.pose("F1", 20.0).sigma, fresh)        # no beacon for 16 s: the plan, with a wide sigma
        self.assertEqual(book.pose("GS1", 5.0).sigma, 0.0)            # a ground sensor's position is known


if __name__ == "__main__":
    unittest.main()
