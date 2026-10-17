"""Tests for the sweep statistics and for the friend-track rules added to the tracker."""

import math
import unittest

from scoring.metrics import RunScore
from scoring.sweep import fmt_error, paired_difference, stats_of
from tracker.test_tracker import radar as radar_at
from tracker.tracker import Tracker, TrackerConfig


def run_score(**kw):
    base = dict(steps=1, count_error_mean_abs=0.0, count_error_bias=0.0, pos_rmse_m=0.0, vel_rmse_mps=0.0,
                heading_rmse_deg=0.0, ospa_m=0.0, id_swaps=0, hostile_detected_frac=0.0, friendlies_flagged=0,
                friendly_flag_frac=0.0, clutter_flagged_frac=0.0, false_tracks_mean=0.0)
    return RunScore(**{**base, **kw})


class TestStats(unittest.TestCase):
    def test_mean_and_standard_error(self):
        mean, error = stats_of([1.0, 2.0, 3.0, 4.0])
        self.assertAlmostEqual(mean, 2.5)
        self.assertAlmostEqual(error, math.sqrt(1.6667 / 4), places=3)
        self.assertEqual(stats_of([5.0]), (5.0, None))
        self.assertEqual(stats_of([]), (None, None))

    def test_a_paired_difference_is_tighter_than_two_separate_means(self):
        off = [run_score(false_tracks_mean=v) for v in (1.0, 5.0, 9.0, 3.0)]
        on = [run_score(false_tracks_mean=v + 0.5) for v in (1.0, 5.0, 9.0, 3.0)]    # always 0.5 more
        mean, error = paired_difference(off, on)["false_tracks_mean"]
        self.assertAlmostEqual(mean, 0.5)
        self.assertAlmostEqual(error, 0.0)
        self.assertGreater(stats_of([r.false_tracks_mean for r in off])[1], 1.0)      # the unpaired noise is large

    def test_the_format_shows_the_error_when_there_is_one(self):
        self.assertEqual(fmt_error((1.234, 0.056)), "1.23±0.06")
        self.assertEqual(fmt_error((1.234, None)), "1.23")
        self.assertEqual(fmt_error((None, None)), "-")


class TestFriendTrackRules(unittest.TestCase):
    def beacon(self, x, y):
        return {"friend_id": "F1", "position": [x, y, 60.0], "velocity": [0.0, 0.0, 0.0],
                "covariance": [[9.0, 0, 0], [0, 9.0, 0], [0, 0, 9.0]]}

    def test_while_beacons_are_fresh_a_sensor_reading_of_the_drone_does_not_move_its_track(self):
        tracker = Tracker(TrackerConfig())
        tracker.step(0.0, [], [self.beacon(200.0, 100.0)])
        before = list(tracker.friends["F1"].state)
        tracker.step(0.2, [radar_at(0.2, 205.0, 104.0)], [])
        self.assertEqual(tracker.friends["F1"].state[0] - before[0], 0.0)
        self.assertEqual(len(tracker.tracks), 1)                      # absorbed: no second track for the drone

    def test_without_recent_beacons_the_sensor_reading_does_update_it(self):
        tracker = Tracker(TrackerConfig())
        tracker.step(0.0, [], [self.beacon(200.0, 100.0)])
        t, state_before = 5.0, None
        tracker.step(t, [], [])
        state_before = list(tracker.friends["F1"].state)
        tracker.step(t + 0.2, [radar_at(t + 0.2, 204.0, 100.0)], [])
        self.assertNotEqual(tracker.friends["F1"].state[0], state_before[0])


if __name__ == "__main__":
    unittest.main()
