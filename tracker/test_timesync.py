"""Node clock estimation from arrival times (tracker/timesync.py)."""

import random
import unittest

from tracker.timesync import TimeSync


def feed(sync, node, offset_s, drift=0.0, seconds=30.0, burst=None, seed=1):
    """Messages stamped every 0.1 s by a clock that is `offset_s` ahead, delivered on a 0.1 s grid after 50 to 400 ms."""
    rng, t = random.Random(seed), 0.0
    while t <= seconds:
        extra = burst[2] if burst and burst[0] <= t < burst[1] else 0.0
        arrival = t + rng.uniform(0.05, 0.4) + extra
        delivered = round(-(-arrival // 0.1) * 0.1, 6)       # handed over on the next step
        sync.observe(node, t * (1 + drift) + offset_s, delivered)
        t = round(t + 0.1, 6)


class TestTimeSync(unittest.TestCase):
    def sync(self):
        return TimeSync(floor_s=0.1)            # a 50 ms shortest delay, on a 0.1 s grid

    def test_it_finds_the_offset_of_a_clock_that_runs_ahead_or_behind(self):
        for offset in (0.15, -0.2, 0.0):
            sync = self.sync()
            feed(sync, "F1", offset)
            self.assertAlmostEqual(sync.offset("F1"), offset, delta=0.005)

    def test_a_burst_of_delay_does_not_pull_the_estimate(self):
        sync = self.sync()
        feed(sync, "F1", 0.1, seconds=30.0, burst=(10.0, 25.0, 4.0))
        self.assertAlmostEqual(sync.offset("F1"), 0.1, delta=0.005)

    def test_it_follows_a_clock_that_gains_or_loses_time(self):
        for drift in (50e-6, -50e-6):
            sync = self.sync()
            feed(sync, "F1", 0.1, drift=drift, seconds=120.0)
            self.assertAlmostEqual(sync.offset("F1"), 0.1 + drift * 120.0, delta=0.01)

    def test_an_unknown_node_has_no_offset(self):
        self.assertEqual(self.sync().offset("F9"), 0.0)

    def test_apply_puts_stamps_on_the_c2_clock_and_leaves_the_originals(self):
        sync = self.sync()
        feed(sync, "F1", 0.15)
        obs = {"type": "observation", "header": {"source_id": "F1", "t_sent": 40.15}, "t_obs": 40.15}
        beacon = {"type": "friendly_beacon", "header": {"source_id": "F1", "t_sent": 40.15}}
        ack = {"type": "c2_ack", "header": {"source_id": "F1", "t_sent": 40.15}}
        out = sync.apply([obs, beacon, ack], 40.2, lambda m: 0.0)
        self.assertAlmostEqual(out[0]["t_obs"], 40.0, delta=0.01)
        self.assertAlmostEqual(out[0]["header"]["t_sent"], 40.0, delta=0.01)
        self.assertAlmostEqual(out[1]["header"]["t_sent"], 40.0, delta=0.01)
        self.assertEqual(out[2], ack)
        self.assertEqual(obs["t_obs"], 40.15)                  # the delivered message itself is untouched


if __name__ == "__main__":
    unittest.main()
