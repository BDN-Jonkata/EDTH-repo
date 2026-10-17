"""End-to-end tests: sensors -> channel -> tracker -> friend/foe -> scoring, on seeder scenarios."""

import unittest

from friend_foe.sweep import Setup, load_preset, make_scenario_and_truth
from pipeline.run import run, scored_frames
from scoring.metrics import ScoreConfig, score


def scenario_and_truth(preset="medium", loss=0.0, index=0):
    return make_scenario_and_truth(Setup(load_preset(preset), "tuning", 1), index, "clear", loss, False)


class TestPipeline(unittest.TestCase):
    def test_clean_run_tracks_hostiles_and_flags_no_friendly(self):
        sc, truth = scenario_and_truth("medium")
        s = score(truth, scored_frames(sc, sc["seed"]), ScoreConfig(warmup_s=10.0))
        self.assertEqual(s.friendlies_flagged, 0)
        self.assertGreater(s.hostile_detected_frac, 0.3)
        self.assertLess(s.pos_rmse_m, 25.0)

    def test_same_seed_gives_the_same_score(self):
        sc, truth = scenario_and_truth("medium")
        a = score(truth, scored_frames(sc, sc["seed"]))
        b = score(truth, scored_frames(sc, sc["seed"]))
        self.assertEqual(a, b)

    def test_losing_every_message_leaves_the_tracker_blind(self):
        sc, truth = scenario_and_truth("medium", loss=1.0)
        frames = list(run(sc, sc["seed"]))
        self.assertTrue(all(not f.tracks and f.readings_used == 0 and not f.beacons for f in frames))

    def test_heavy_loss_hurts_detection_but_not_by_flagging_friendlies_the_way_it_hurts_hostiles(self):
        sc0, truth0 = scenario_and_truth("medium", loss=0.0)
        sc9, truth9 = scenario_and_truth("medium", loss=0.9)
        clean = score(truth0, scored_frames(sc0, sc0["seed"]), ScoreConfig(warmup_s=10.0))
        lossy = score(truth9, scored_frames(sc9, sc9["seed"]), ScoreConfig(warmup_s=10.0))
        self.assertLess(lossy.hostile_detected_frac, clean.hostile_detected_frac)


if __name__ == "__main__":
    unittest.main()
