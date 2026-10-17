"""Tests for the lossy, delayed channel."""

import unittest

from common.channel import Channel


def scenario(loss=0.0, burst=False, latency=(0, 0), enabled=True):
    return {"degradations": {"network": {"enabled": enabled, "loss": loss, "burst": burst, "latency_ms": list(latency)}}}


def message(source, n=0):
    return {"type": "x", "header": {"source_id": source, "seq": n}}


class TestChannel(unittest.TestCase):
    def test_lossless_channel_delivers_everything_in_order(self):
        ch = Channel(scenario())
        for n in range(5):
            ch.send(message("F1", n), 0.1 * n)
        self.assertEqual([m["header"]["seq"] for m in ch.deliver(10.0)], [0, 1, 2, 3, 4])

    def test_nothing_arrives_before_its_delay_is_over(self):
        ch = Channel(scenario(latency=(500, 500)))
        ch.send(message("F1"), 1.0, extra_delay_s=0.25)
        self.assertEqual(ch.deliver(1.7), [])
        self.assertEqual(len(ch.deliver(1.76)), 1)

    def test_loss_rate_matches_the_setting_and_is_counted(self):
        ch = Channel(scenario(loss=0.3), seed=4)
        for n in range(5000):
            ch.send(message("F1", n), 0.0)
        self.assertAlmostEqual(ch.lost / ch.sent, 0.3, delta=0.03)
        self.assertEqual(len(ch.deliver(1.0)), ch.sent - ch.lost)

    def test_disabled_network_loses_nothing(self):
        ch = Channel(scenario(loss=0.9, enabled=False))
        for n in range(100):
            ch.send(message("F1", n), 0.0)
        self.assertEqual(len(ch.deliver(1.0)), 100)

    def test_each_source_has_its_own_burst_chain(self):
        ch = Channel(scenario(loss=0.5, burst=True), seed=2)
        for n in range(200):
            ch.send(message("F1", n), 0.0)
            ch.send(message("F2", n), 0.0)
        self.assertEqual(set(ch.links), {"F1", "F2"})
        self.assertIsNot(ch.links["F1"], ch.links["F2"])


if __name__ == "__main__":
    unittest.main()
