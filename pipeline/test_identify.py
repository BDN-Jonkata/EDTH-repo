"""Tests for the identification of emitters from the bearings of RF receivers."""

import math
import unittest

from pipeline.identify import Emitters, IdentifyConfig
from tracker.ekf import identity_like
from tracker.measurement import BEARING, Measurement, Pose2D
from tracker.tracker import Track


def rf_bearing(t, node, pose, x, y):
    return Measurement(BEARING, t, node, "rf", pose, 300.0, bearing=math.atan2(y - pose.y, x - pose.x),
                       sigma_bearing=math.radians(5.0), sensor_kind="rf_receiver")


def camera_bearing(t, node, pose, x, y):
    return Measurement(BEARING, t, node, "eo", pose, 300.0, bearing=math.atan2(y - pose.y, x - pose.x),
                       sigma_bearing=math.radians(1.0), sensor_kind="eo_camera")


def track(track_id, x, y, friend=None):
    return Track(track_id, [x, y, 0.0, 0.0], identity_like([100.0, 100.0, 4.0, 4.0]), 0.0, 0.0, confirmed=True, friend_id=friend)


A, B = Pose2D(0.0, 0.0), Pose2D(300.0, 0.0)


class TestEmitters(unittest.TestCase):
    def run_fixes(self, emitters, tracks, x, y, seconds=3.0, kind=rf_bearing):
        for k in range(int(seconds * 5)):
            t = k / 5
            emitters.step(t, [kind(t, "A", A, x, y), kind(t, "B", B, x, y)], tracks)
        return seconds

    def test_two_receivers_whose_bearings_cross_on_a_track_call_it_hostile(self):
        emitters, tracks = Emitters(), [track("T1", 150.0, 120.0)]
        end = self.run_fixes(emitters, tracks, 150.0, 120.0)
        self.assertEqual(emitters.label("T1", end), "hostile")

    def test_a_track_far_from_where_the_bearings_cross_is_not_called(self):
        """A bird on the same line of sight from one receiver must not take the emitter's label."""
        emitters, tracks = Emitters(), [track("T1", 150.0, 120.0), track("T2", 260.0, 208.0)]   # T2 behind T1 as seen from A
        end = self.run_fixes(emitters, tracks, 150.0, 120.0)
        self.assertEqual(emitters.label("T1", end), "hostile")
        self.assertIsNone(emitters.label("T2", end))

    def test_one_receiver_alone_gives_no_label(self):
        emitters, tracks = Emitters(), [track("T1", 150.0, 120.0)]
        for k in range(20):
            emitters.step(k / 5, [rf_bearing(k / 5, "A", A, 150.0, 120.0)], tracks)
        self.assertIsNone(emitters.label("T1", 4.0))

    def test_a_camera_is_not_evidence_of_an_emitter(self):
        emitters, tracks = Emitters(), [track("T1", 150.0, 120.0)]
        end = self.run_fixes(emitters, tracks, 150.0, 120.0, kind=camera_bearing)
        self.assertIsNone(emitters.label("T1", end))

    def test_a_friendlys_radio_labels_nothing(self):
        emitters, tracks = Emitters(), [track("T1", 150.0, 120.0, friend="F2")]
        end = self.run_fixes(emitters, tracks, 150.0, 120.0)
        self.assertIsNone(emitters.label("T1", end))

    def test_the_label_goes_when_the_fixes_stop(self):
        emitters, tracks = Emitters(IdentifyConfig(window_s=6.0)), [track("T1", 150.0, 120.0)]
        end = self.run_fixes(emitters, tracks, 150.0, 120.0)
        emitters.step(end + 10.0, [], tracks)
        self.assertIsNone(emitters.label("T1", end + 10.0))


if __name__ == "__main__":
    unittest.main()
