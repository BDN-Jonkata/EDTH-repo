"""The pipeline's safe mode for the behaviour module, and the dispatcher's use of classes."""

import unittest

from friend_foe.estimator import Classification, TrackState
from pipeline.behaviour import automatic_estimator
from pipeline.cueing import Cue
from pipeline.dispatch import Investigator

SCENARIO = {"beacon": {"rate_hz": 2}, "friendlies": []}


def steady_transit(estimator, seconds=40):
    last = None
    for k in range(int(seconds / 0.5) + 1):
        t = k / 2
        track = TrackState("T1", t, (100 + 10 * t, 100.0, 60.0), (10.0, 0.0, 0.0), 2.0, observed_t=t)
        last = estimator.update(t, [track], [])
    return last[0].cls


class TestSafeMode(unittest.TestCase):
    def test_the_module_alone_calls_a_steady_unidentified_flight_peaceful(self):
        self.assertEqual(steady_transit(automatic_estimator(SCENARIO, motion_peaceful=True)), "peaceful")

    def test_safe_mode_never_lets_motion_alone_clear_a_track(self):
        self.assertNotEqual(steady_transit(automatic_estimator(SCENARIO)), "peaceful")


class FakeInvestigator(Investigator):
    def __init__(self, classes):
        self._classes = classes


class TestCuePriority(unittest.TestCase):
    def classes(self):
        return {"T1": Classification("T1", 0.0, "friendly", 0.9, 0.9), "T2": Classification("T2", 0.0, "peaceful", 0.9, 0.5, p_hostile=0.05),
                "T3": Classification("T3", 0.0, "unknown", 0.5, 0.2, p_hostile=0.3),
                "T4": Classification("T4", 0.0, "suspicious", 0.5, 0.1, p_hostile=0.8)}

    def test_harmless_tracks_get_no_drone_and_the_likeliest_hostile_goes_first(self):
        cues = [Cue((0, 0), track_id=i) for i in ("T1", "T2", "T3", "T4")] + [Cue((5, 5), node="D1")]
        ordered = FakeInvestigator(self.classes())._by_risk(cues)
        self.assertEqual([c.track_id for c in ordered], ["T4", "T3", ""])


if __name__ == "__main__":
    unittest.main()
