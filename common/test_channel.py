"""Tests for the lossy, delayed channel."""

import unittest

from common.channel import Channel


def scenario(loss=0.0, burst=False, latency=(0, 0), enabled=True, dropout=(), **network):
    net = {"enabled": enabled, "loss": loss, "burst": burst, "latency_ms": list(latency), **network}
    return {"degradations": {"network": net, "dropout": list(dropout)}}


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


ZONE = {"x": 500, "y": 500, "radius_m": 100, "loss": 0.9, "t_start": 10, "t_end": 20}


def where(node, t):
    return (500.0, 500.0) if node == "F1" else (0.0, 0.0)


def lost_share(ch, source, t, n=3000):
    for i in range(n):
        ch.send(message(source, i), t)
    return ch.lost / ch.sent


class TestJamming(unittest.TestCase):
    def test_a_node_inside_an_active_zone_loses_at_the_zones_rate(self):
        ch = Channel(scenario(loss=0.1, jamming_zones=[ZONE]), seed=1, position_of=where)
        self.assertAlmostEqual(lost_share(ch, "F1", 15.0), 0.9, delta=0.03)

    def test_outside_the_zone_or_the_time_only_the_base_loss_applies(self):
        for source, t in (("F2", 15.0), ("F1", 5.0), ("F1", 20.0)):
            ch = Channel(scenario(loss=0.1, jamming_zones=[ZONE]), seed=1, position_of=where)
            self.assertAlmostEqual(lost_share(ch, source, t), 0.1, delta=0.03, msg=(source, t))

    def test_a_zone_weaker_than_the_base_loss_changes_nothing(self):
        weak = dict(ZONE, loss=0.05)
        a = Channel(scenario(loss=0.3, jamming_zones=[weak]), seed=2, position_of=where)
        b = Channel(scenario(loss=0.3), seed=2)
        self.assertEqual(lost_share(a, "F1", 15.0), lost_share(b, "F1", 15.0))

    def test_zones_are_ignored_when_the_network_is_off_or_there_is_no_position(self):
        off = Channel(scenario(loss=0.0, enabled=False, jamming_zones=[ZONE]), position_of=where)
        self.assertEqual(lost_share(off, "F1", 15.0, 200), 0.0)
        blind = Channel(scenario(loss=0.0, jamming_zones=[ZONE]))
        self.assertEqual(lost_share(blind, "F1", 15.0, 200), 0.0)


class TestBandwidth(unittest.TestCase):
    def test_a_cap_spaces_the_messages_out_and_drops_the_oldest_backlog(self):
        ch = Channel(scenario(bandwidth_kbps=8))
        for n in range(40):
            ch.send({"type": "observation", "header": {"source_id": "F1", "seq": n}, "pad": "x" * 100}, 0.0)
        got = [m["header"]["seq"] for t in range(0, 60) for m in ch.deliver(float(t))]
        self.assertEqual(got, sorted(got))
        self.assertEqual(got[-1], 39, "the newest message survives")
        dropped = ch.cap.summary()["observation"]["dropped"]
        self.assertTrue(0 < dropped and len(got) + dropped == 40)

    def test_no_cap_is_the_old_behaviour(self):
        self.assertIsNone(Channel(scenario()).cap)
        self.assertIsNone(Channel(scenario(bandwidth_kbps=None)).cap)

    def test_messages_lost_on_the_link_still_used_their_airtime(self):
        ch = Channel(scenario(loss=1.0, bandwidth_kbps=8))
        for n in range(5):
            ch.send({"type": "x", "header": {"source_id": "F1", "seq": n}, "pad": "y" * 250}, 0.0)
        ch.deliver(60.0)
        self.assertEqual((ch.sent, ch.lost), (5, 5))
        self.assertGreater(ch.cap.links["F1"].busy_until, 1.0)


class TestDropout(unittest.TestCase):
    def test_a_dead_node_sends_nothing_from_its_time_on(self):
        ch = Channel(scenario(dropout=[{"node": "F3", "t": 5.0}]))
        for t in (1.0, 4.9, 5.0, 9.0):
            ch.send(message("F3"), t)
            ch.send(message("F2"), t)
        self.assertEqual(sorted((m["header"]["source_id"] for m in ch.deliver(20.0))), ["F2"] * 4 + ["F3"] * 2)
        self.assertEqual((ch.silent, ch.sent), (2, 6))


if __name__ == "__main__":
    unittest.main()
