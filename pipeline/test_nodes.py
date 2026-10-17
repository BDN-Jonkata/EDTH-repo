"""The distributed mode runs end to end and shares tracks only as local_track messages."""

import unittest

from friend_foe.sweep import Setup, load_preset, make_scenario_and_truth
from pipeline.run import Pipeline


class TestDistributedMode(unittest.TestCase):
    def test_the_merger_produces_tracks_from_messages_that_crossed_the_channel(self):
        scenario, _ = make_scenario_and_truth(Setup(load_preset("medium"), "tuning", 1, None, 0, 0), 0, "clear", 0.0, False)
        pipeline = Pipeline(scenario, scenario["seed"], distributed=True)
        sent_before = pipeline.channel.sent
        frames = [pipeline.step(round(k * 0.1, 6)) for k in range(300)]
        self.assertTrue(any(f.tracks for f in frames))
        self.assertGreater(pipeline.channel.sent, sent_before)
        self.assertTrue(all(tr.origin == "fused" for f in frames for tr in f.tracks))
        self.assertTrue(any(tr.friend_id for f in frames for tr in f.tracks))


if __name__ == "__main__":
    unittest.main()
