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

    def faulty(self, *faults, dropout=()):
        s = scenario()
        s["degradations"]["sensor_faults"] = list(faults)
        s["degradations"]["dropout"] = list(dropout)
        return Channel(s)

    def test_a_link_outage_cuts_one_node_only_while_it_lasts(self):
        ch = self.faulty({"node": "F2", "kind": "link_outage", "t_start": 10.0, "t_end": 20.0})
        for t in (5.0, 15.0, 25.0):
            ch.send(message("F2", int(t)), t)
        ch.send(message("F3", 99), 15.0)
        self.assertEqual(sorted(m["header"]["seq"] for m in ch.deliver(60.0)), [5, 25, 99])

    def test_a_dropout_is_for_good_including_the_older_dropout_list(self):
        ch = self.faulty({"node": "F4", "kind": "dropout", "t_start": 10.0}, dropout=[{"node": "F5", "t": 3.0}])
        ch.send(message("F4", 1), 9.0)
        ch.send(message("F4", 2), 100.0)
        ch.send(message("F5", 3), 2.0)
        ch.send(message("F5", 4), 4.0)
        self.assertEqual(sorted(m["header"]["seq"] for m in ch.deliver(200.0)), [1, 3])

    def test_a_delay_burst_delays_what_the_node_sends_inside_the_window(self):
        ch = self.faulty({"node": "GS2", "kind": "delay_burst", "t_start": 10.0, "t_end": 20.0, "extra_ms": 4000})
        ch.send(message("GS2", 1), 12.0)
        ch.send(message("GS2", 2), 25.0)
        self.assertEqual([m["header"]["seq"] for m in ch.deliver(13.0)], [])
        self.assertEqual([m["header"]["seq"] for m in ch.deliver(16.1)], [1])
        self.assertEqual([m["header"]["seq"] for m in ch.deliver(25.1)], [2])

    def test_a_scenario_with_no_faults_behaves_as_before(self):
        ch = Channel({"degradations": {"network": {"enabled": False}}})
        ch.send(message("F1"), 0.0)
        self.assertEqual(len(ch.deliver(0.0)), 1)

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
