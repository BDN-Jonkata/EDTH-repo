"""Tests for the Kalman filter, the measurement models and the tracker."""

import math
import unittest

from tracker.ekf import identity_like, predict, scalar_update
from tracker.measurement import BEARING, RANGE_BEARING, Measurement, Pose2D, RssiRange, from_observation
from tracker.models import apply_measurement, fix_from_range_bearing, gate_cost, triangulate
from tracker.poses import PoseBook
from tracker.tracker import Track, Tracker, TrackerConfig

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


class TestRadialSpeedInAssociation(unittest.TestCase):
    def test_two_targets_a_few_metres_apart_are_told_apart_by_their_radial_speed(self):
        """At the crossing the ranges and bearings of the two targets are nearly the same; how fast each moves along
        the line of sight is not, so a return of one target must cost the other track more."""
        cov = identity_like([4.0, 4.0, 1.0, 1.0])
        toward, away = [200.0, 100.0, -8.0, -4.0], [205.0, 104.0, 8.0, 4.0]       # 6 m apart, opposite velocities
        reading = radar(0.0, 200.0, 100.0, vx=-8.0, vy=-4.0)                       # the first one's return
        own, other = gate_cost(toward, cov, reading), gate_cost(away, cov, reading)
        self.assertIsNotNone(own)
        self.assertTrue(other is None or other > own + 10.0)


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

    def rf(self, freq_mhz, rssi_dbm=-40.0 - 40.0):
        return {"kind": "bearing", "t_obs": 1.0, "header": {"source_id": "GS2"}, "sensor_id": "rf",
                "value": {"bearing_deg": 0.0, "rssi_dbm": rssi_dbm, "center_freq_mhz": freq_mhz},
                "cov_fields": ["bearing_deg", "rssi_dbm"], "covariance": [[144.0, 0.0], [0.0, 16.0]]}

    def test_an_rf_reading_on_a_hostile_link_gets_a_range_from_its_signal_strength_only_when_asked(self):
        module, rssi = {"sim": {"range_m": 300, "noise": {}}, "kind": "rf_receiver"}, RssiRange(-40.0, 6.0)
        self.assertIsNone(from_observation(self.rf(2437.0), Pose2D(0, 0), module).range_m)
        m = from_observation(self.rf(2437.0), Pose2D(0, 0), module, rssi)
        self.assertAlmostEqual(m.range_m, 100.0, places=3)                       # -40 dBm at 1 m, -80 dBm is 40 dB down: 100 m
        self.assertAlmostEqual(m.sigma_range, 100.0 * math.log(10) / 20 * math.hypot(4.0, 6.0), places=3)

    def test_an_rf_reading_on_the_friendly_link_gets_no_range(self):
        module = {"sim": {"range_m": 300, "noise": {}}, "kind": "rf_receiver"}
        self.assertIsNone(from_observation(self.rf(5745.0), Pose2D(0, 0), module, RssiRange(-40.0)).range_m)

    def test_a_bearing_with_a_range_is_gated_on_both_and_a_wrong_range_is_refused(self):
        module = {"sim": {"range_m": 300, "noise": {}}, "kind": "rf_receiver"}
        m = from_observation(self.rf(2437.0), Pose2D(0, 0), module, RssiRange(-40.0, 0.0))   # bearing north, 100 m
        near, far = [0.0, 100.0, 0.0, 0.0], [0.0, 1000.0, 0.0, 0.0]
        cov = identity_like([100.0, 100.0, 4.0, 4.0])
        self.assertIsNotNone(gate_cost(near, cov, m))
        self.assertIsNone(gate_cost(far, cov, m))


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


class TestFriendTrackLife(unittest.TestCase):
    def beacon(self, t):
        return {"friend_id": "F1", "position": [100.0, 100.0], "velocity": [0.0, 0.0], "covariance": [[9.0, 0, 0], [0, 9.0, 0], [0, 0, 9.0]]}

    def test_a_friendlys_track_outlives_a_long_silence_and_goes_after_its_limit(self):
        tracker = Tracker()
        tracker.step(0.0, [], [self.beacon(0.0)])
        self.assertEqual([tr.friend_id for tr in tracker.tracks], ["F1"])
        tracker.step(30.0, [])                       # 30 s with no beacon and no reading: a confirmed track would be long gone
        self.assertEqual([tr.friend_id for tr in tracker.tracks], ["F1"])
        tracker.step(61.0, [])
        self.assertEqual(tracker.tracks, [])
        self.assertEqual(tracker.friends, {})


class TestDuplicateTracks(unittest.TestCase):
    def two_tracks(self, config, offset, dv):
        tracker = Tracker(config)
        for k, (x, vx) in enumerate(((100.0, 10.0), (100.0 + offset, 10.0 + dv))):
            tr = tracker._add(Track(f"T{k + 1}", [x, 50.0, vx, 0.0], identity_like([25.0, 25.0, 4.0, 4.0]), float(k), 0.0, confirmed=True))
            tr.last_update = 0.0
        tracker._t = 0.0
        return tracker

    def test_two_close_tracks_moving_alike_become_one_and_the_older_stays(self):
        tracker = self.two_tracks(TrackerConfig(), offset=15.0, dv=1.0)
        tracker._drop_duplicates()
        self.assertEqual([tr.track_id for tr in tracker.tracks], ["T1"])

    def test_close_tracks_with_different_velocities_are_two_targets(self):
        tracker = self.two_tracks(TrackerConfig(), offset=15.0, dv=-25.0)
        tracker._drop_duplicates()
        self.assertEqual(len(tracker.tracks), 2)

    def test_tracks_farther_apart_than_the_limit_stay_separate(self):
        tracker = self.two_tracks(TrackerConfig(), offset=80.0, dv=0.0)
        tracker._drop_duplicates()
        self.assertEqual(len(tracker.tracks), 2)

    def test_it_can_be_switched_off(self):
        tracker = self.two_tracks(TrackerConfig(duplicate_distance_m=0.0), offset=5.0, dv=0.0)
        tracker._drop_duplicates()
        self.assertEqual(len(tracker.tracks), 2)


class TestFreshReplay(unittest.TestCase):
    """`oosm_min_age_s` below the usual 1 s also replays readings that are only a fraction of a second old; one no
    track explains still starts a track while it is younger than `oosm_start_max_age_s`."""

    @staticmethod
    def steps(config, age_s):
        tracker = Tracker(config)
        for k in range(30):
            t = round(k * 0.1, 6)
            tracker.step(t, [radar(round(t - age_s, 6), 100.0 + 10.0 * (t - age_s), 50.0, 10.0, 0.0, sigma_r=2.0, sigma_b=0.005)])
        return tracker

    def test_a_target_seen_only_through_slightly_old_readings_is_still_tracked(self):
        tracker = self.steps(TrackerConfig(oosm=True, oosm_min_age_s=0.2), 0.3)
        self.assertEqual(len(tracker.tracks), 1)
        self.assertAlmostEqual(tracker.tracks[0].state[0], 100.0 + 10.0 * (2.9 - 0.3), delta=3.0)

    def test_the_start_age_limit_is_what_keeps_old_readings_from_starting_tracks(self):
        tracker = self.steps(TrackerConfig(oosm=True, oosm_min_age_s=0.2, oosm_start_max_age_s=0.2), 0.3)
        self.assertEqual(len(tracker.tracks), 0)


class TestOutOfSequence(unittest.TestCase):
    """A reading that arrives late is applied at the time it was taken (tracker/oosm.py)."""

    SPEED = 10.0

    @staticmethod
    def reading(t, offset=0.0):
        x = 100.0 + TestOutOfSequence.SPEED * t + offset      # a target flying east at 10 m/s, seen by a radar at the origin
        return radar(t, x, 50.0, TestOutOfSequence.SPEED, 0.0, sigma_r=2.0, sigma_b=0.005)

    def run_track(self, config, delayed=(), delay_s=3.0, until=6.0, offset=0.0):
        """Drive one tracker every 0.1 s; the readings taken at the times in `delayed` arrive `delay_s` later.
        `offset` shifts the delayed readings along the track, so only a tracker that uses them at their own time agrees."""
        tracker, backlog, k = Tracker(config), [], 0
        while k * 0.1 <= until + 1e-9:
            t = round(k * 0.1, 6)
            arrived = [m for due, m in backlog if due <= t + 1e-9]
            backlog = [(due, m) for due, m in backlog if due > t + 1e-9]
            if any(abs(t - d) < 1e-6 for d in delayed):
                backlog.append((round(t + delay_s, 6), self.reading(t, offset)))
            else:
                arrived.append(self.reading(t))
            tracker.step(t, arrived)
            k += 1
        return tracker

    def only_track(self, tracker):
        self.assertEqual(len(tracker.tracks), 1)
        return tracker.tracks[0]

    def test_a_late_reading_gives_the_state_it_would_have_given_on_time(self):
        """Four readings 3 m off the track, young track: taken at 0.3 to 0.6 s, arriving 1.5 s late."""
        kwargs = dict(delayed=[0.3, 0.4, 0.5, 0.6], until=2.5, offset=3.0)
        on_time = self.only_track(self.run_track(TrackerConfig(oosm=True), delay_s=0.0, **kwargs))
        late = self.only_track(self.run_track(TrackerConfig(oosm=True), delay_s=1.5, **kwargs))
        at_arrival = self.only_track(self.run_track(TrackerConfig(), delay_s=1.5, **kwargs))
        self.assertAlmostEqual(late.state[0], on_time.state[0], delta=0.3)
        self.assertGreater(abs(at_arrival.state[0] - on_time.state[0]), abs(late.state[0] - on_time.state[0]))
        self.assertGreater(abs(on_time.state[0] - 125.0), 0.1)     # the readings did move the track, so the test can tell

    def test_stale_readings_used_at_arrival_start_a_ghost_track_and_replayed_ones_do_not(self):
        kwargs = dict(delayed=[x / 10 for x in range(20, 40)], delay_s=3.0, until=6.0)
        self.assertEqual(len(self.run_track(TrackerConfig(), **kwargs).tracks), 2)
        tracker = self.run_track(TrackerConfig(oosm=True), **kwargs)
        self.assertEqual(len(tracker.tracks), 1)
        self.assertAlmostEqual(tracker.tracks[0].state[0], 160.0, delta=1.0)

    def test_a_reading_older_than_the_window_is_dropped(self):
        tracker = self.run_track(TrackerConfig(oosm=True, oosm_window_s=2.0), until=8.0)
        before = list(tracker.tracks[0].state)
        tracker.step(8.1, [self.reading(1.0, offset=200.0)])      # taken 7 s ago: outside the 2 s window
        self.assertAlmostEqual(tracker.tracks[0].state[0], before[0] + self.SPEED * 0.1, delta=0.5)

    def test_a_late_reading_starts_no_track(self):
        tracker = Tracker(TrackerConfig(oosm=True))
        tracker.step(5.0, [self.reading(2.0)])
        self.assertEqual(tracker.tracks, [])

    def test_a_late_reading_does_not_keep_a_dead_track_alive(self):
        tracker = self.run_track(TrackerConfig(oosm=True), until=3.0)
        tracker.step(3.0 + 14.0, [])
        tracker.step(3.1 + 14.0, [self.reading(3.0)])
        self.assertEqual(tracker.tracks, [])      # confirmed_ttl_s (10 s) has passed since the last update

    def test_the_log_is_folded_into_the_checkpoint_so_it_stays_short(self):
        tr = self.only_track(self.run_track(TrackerConfig(oosm=True, oosm_window_s=2.0), until=10.0))
        self.assertLessEqual(len(tr.log), 2.0 / 0.1 + 2)
        self.assertGreater(tr.checkpoint[0], 7.0)

    def test_off_by_default_nothing_is_logged(self):
        tr = self.only_track(self.run_track(TrackerConfig()))
        self.assertIsNone(tr.checkpoint)
        self.assertEqual(tr.log, [])


class TestRadarFixBesideAFriendly(unittest.TestCase):
    """A radar fix 40 m from a friendly's track (more than the 25 m spawn clearance) is the friendly when its radial speed
    is the friendly's, and a new target when it is not."""

    def friend_and_fix(self, fix_vx, config=None):
        tracker = Tracker(config)
        beacon = {"friend_id": "F1", "position": [200.0, 100.0, 60.0], "velocity": [10.0, 0.0, 0.0],
                  "covariance": [[9.0, 0, 0], [0, 9.0, 0], [0, 0, 9.0]]}
        tracker.step(0.0, [], [beacon])
        tracker.step(0.1, [radar(0.1, 240.0, 100.0, fix_vx, 0.0)])
        return [tr for tr in tracker.tracks if tr.friend_id is None]

    def test_a_fix_with_the_friendlys_radial_speed_starts_no_track(self):
        self.assertEqual(self.friend_and_fix(10.0), [])

    def test_a_fix_moving_the_other_way_starts_a_track(self):
        self.assertEqual(len(self.friend_and_fix(-10.0)), 1)

    def test_the_rule_can_be_switched_off(self):
        self.assertEqual(len(self.friend_and_fix(10.0, TrackerConfig(friend_spawn_clearance_m=0.0))), 1)

    def test_a_fix_farther_than_the_clearance_starts_a_track(self):
        self.assertEqual(len(self.friend_and_fix(10.0, TrackerConfig(friend_spawn_clearance_m=30.0))), 1)


class TestTrackThatLeftTheArea(unittest.TestCase):
    """A target track beyond the margin outside the defended square is dropped; a friendly's, one inside the margin, and everything with the rule off stay."""

    def survivors(self, x, config, friend=None):
        tracker = Tracker(config)
        tracker.tracks = [Track("T1", [x, 500.0, 0.0, 0.0], identity_like([100.0, 100.0, 4.0, 4.0]), 0.0, 0.0, confirmed=True, friend_id=friend)]
        tracker.step(0.1, [])
        return [tr.track_id for tr in tracker.tracks]

    def test_a_track_beyond_the_margin_is_dropped(self):
        self.assertEqual(self.survivors(1030.0, TrackerConfig(area_m=1000.0, outside_area_margin_m=20.0)), [])

    def test_a_track_inside_the_margin_or_the_square_stays(self):
        config = TrackerConfig(area_m=1000.0, outside_area_margin_m=20.0)
        self.assertEqual(self.survivors(1010.0, config), ["T1"])
        self.assertEqual(self.survivors(500.0, config), ["T1"])

    def test_the_rule_is_off_by_default_and_never_applies_to_a_friendly(self):
        self.assertEqual(self.survivors(1030.0, TrackerConfig(area_m=1000.0)), ["T1"])
        self.assertEqual(self.survivors(1030.0, TrackerConfig(area_m=1000.0, outside_area_margin_m=20.0), friend="F1"), ["T1"])


if __name__ == "__main__":
    unittest.main()


