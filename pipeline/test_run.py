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


class TestChannelFeatures(unittest.TestCase):
    """Jamming zones, a link cap and node dropout from the scenario reach the pipeline (they are in `common/channel.py`)."""

    def delivered(self, change):
        sc, _ = scenario_and_truth("medium")
        sc["degradations"]["network"]["enabled"] = True
        change(sc["degradations"])
        sc["duration_s"] = 40
        return sum(f.readings_used + len(f.beacons) for f in run(sc, sc["seed"]))

    def test_a_jamming_zone_over_the_whole_area_lowers_what_arrives(self):
        zone = {"x": 500, "y": 500, "radius_m": 2000, "loss": 0.9}
        clean = self.delivered(lambda d: None)
        jammed = self.delivered(lambda d: d["network"].update(jamming_zones=[zone]))
        self.assertLess(jammed, 0.4 * clean)

    def test_a_low_link_cap_lowers_what_arrives(self):
        self.assertLess(self.delivered(lambda d: d["network"].update(bandwidth_kbps=2)), self.delivered(lambda d: None))

    def test_a_dropped_node_stops_sending(self):
        every_node = lambda d: d.update(dropout=[{"node": n, "t": 10.0} for n in ("F1", "F2", "F3", "F4", "F5", "GS1", "GS2")])
        self.assertLess(self.delivered(every_node), 0.5 * self.delivered(lambda d: None))


if __name__ == "__main__":
    unittest.main()
