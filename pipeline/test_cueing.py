"""Cueing: a bearing nothing explains, seen repeatedly, makes a cue; one a track explains does not."""

import math
import unittest

from pipeline.cueing import Cueing, explained
from tracker.ekf import identity_like
from tracker.measurement import BEARING, Measurement, Pose2D
from tracker.tracker import Track


def bearing(t, degrees, node="D1"):
    return Measurement(BEARING, t, node, "cam", Pose2D(0.0, 0.0), 400.0, bearing=math.radians(degrees), sigma_bearing=0.02)


def track_at(x, y):
    return Track("T1", [x, y, 0.0, 0.0], identity_like([25.0, 25.0, 1.0, 1.0]), 0.0, 0.0, confirmed=True)


class TestCueing(unittest.TestCase):
    def test_a_track_along_the_bearing_explains_it(self):
        self.assertTrue(explained(bearing(0.0, 0.0), [track_at(200.0, 2.0)], 3.0))
        self.assertFalse(explained(bearing(0.0, 0.0), [track_at(0.0, 200.0)], 3.0))
        self.assertFalse(explained(bearing(0.0, 0.0), [track_at(900.0, 0.0)], 3.0))     # beyond the sensor's reach

    def test_repeated_unexplained_bearings_make_one_cue_along_the_bearing(self):
        cueing = Cueing()
        cues = []
        for k in range(4):
            cues += cueing.step(k * 0.5, [bearing(k * 0.5, 90.0)], [])
        self.assertEqual(len(cues), 1)
        (x, y) = cues[0].xy
        self.assertEqual(cues[0].node, "D1")
        self.assertAlmostEqual(x, 0.0, delta=1.0)
        self.assertAlmostEqual(y, 150.0, delta=1.0)

    def test_a_bearing_a_track_explains_makes_no_cue(self):
        cueing = Cueing()
        self.assertEqual([c for k in range(6) for c in cueing.step(k * 0.3, [bearing(k * 0.3, 0.0)], [track_at(100.0, 0.0)])], [])

    def test_a_scattered_bearing_makes_no_cue(self):
        cueing = Cueing()
        cues = [c for k, deg in enumerate((0.0, 40.0, 80.0)) for c in cueing.step(k * 0.5, [bearing(k * 0.5, deg)], [])]
        self.assertEqual(cues, [])

    def test_a_new_non_friend_track_is_handed_off_once_when_old_enough(self):
        cueing = Cueing()
        tr = track_at(100.0, 50.0)
        self.assertEqual(cueing.step(1.0, [], [tr]), [])                       # too young
        first = cueing.step(2.5, [], [tr])
        self.assertEqual([(c.track_id, c.xy) for c in first], [("T1", (100.0, 50.0))])
        self.assertEqual(cueing.step(3.0, [], [tr]), [])                       # only once
        cueing.retry("T1")
        self.assertEqual(len(cueing.step(3.5, [], [tr])), 1)                   # unless no drone was free

    def test_a_friend_track_is_not_handed_off(self):
        tr = track_at(100.0, 50.0)
        tr.friend_id = "F1"
        self.assertEqual(Cueing().step(5.0, [], [tr]), [])

    def test_no_second_cue_at_the_same_place_during_the_cooldown(self):
        cueing = Cueing()
        cues = [c for k in range(12) for c in cueing.step(k * 0.5, [bearing(k * 0.5, 90.0)], [])]
        self.assertEqual(len(cues), 1)


if __name__ == "__main__":
    unittest.main()
