"""Link health: states from sequence gaps and silence, trust, and the friend/foe estimator's use of it."""

import unittest

from friend_foe.estimator import Beacon, EstimatorConfig, FriendFoeEstimator, TrackState
from health.link import DEGRADED, OFFLINE, OK, PRESUMED_DEAD, HealthConfig, LinkHealth, wilson
from health.monitor import HealthMonitor
from health.trust import weighted
from tracker.measurement import BEARING, Measurement, Pose2D


def feed(link, seqs, rate=2.0, start=0.0):
    for k, seq in enumerate(seqs):
        link.observe(seq, start + k / rate)


class TestLink(unittest.TestCase):
    def test_a_clean_link_is_ok_and_loses_nothing(self):
        link = LinkHealth(HealthConfig())
        feed(link, range(1, 61))
        self.assertEqual(link.state(30.0), OK)
        self.assertLess(link.p_bad, 0.05)
        self.assertEqual(link.loss_rate, 0.0)

    def test_a_third_of_the_messages_missing_makes_it_degraded_and_a_clean_run_recovers_it(self):
        link = LinkHealth(HealthConfig())
        feed(link, [s for s in range(1, 121) if s % 3])
        self.assertEqual(link.state(link.last_heard + 0.1), DEGRADED)
        feed(link, range(121, 301), start=link.last_heard + 0.5)
        self.assertEqual(link.state(link.last_heard + 0.1), OK)

    def test_silence_makes_it_offline_then_presumed_dead(self):
        link = LinkHealth(HealthConfig())
        feed(link, range(1, 11))
        self.assertEqual(link.state(5.0 + 3.0), OK)
        self.assertEqual(link.state(5.0 + 4.1), OFFLINE)
        self.assertEqual(link.state(5.0 + 15.5), PRESUMED_DEAD)

    def test_a_duplicate_or_resent_number_says_nothing_new(self):
        link = LinkHealth(HealthConfig())
        feed(link, [1, 2, 3, 4, 5])
        before = (link.p_bad, len(link.outcomes))
        link.observe(3, 10.0)
        self.assertEqual((link.p_bad, len(link.outcomes)), before)

    def test_the_cusum_alarms_on_a_loss_burst_and_stays_quiet_on_a_clean_link(self):
        quiet, noisy = LinkHealth(HealthConfig()), LinkHealth(HealthConfig())
        feed(quiet, range(1, 200))
        feed(noisy, [s for s in range(1, 100) if s % 2])
        self.assertFalse(quiet.alarm)
        self.assertTrue(noisy.alarm)

    def test_the_wilson_interval_contains_the_rate_and_shrinks_with_more_outcomes(self):
        lo, hi = wilson(4, 40, 1.96)
        self.assertLess(lo, 0.1)
        self.assertGreater(hi, 0.1)
        lo2, hi2 = wilson(40, 400, 1.96)
        self.assertLess(hi2 - lo2, hi - lo)
        self.assertEqual(wilson(0, 0, 1.96), (0.0, 1.0))


class TestMonitor(unittest.TestCase):
    def message(self, source, seq):
        return {"header": {"source_id": source, "seq": seq}}

    def test_nodes_are_judged_separately_and_an_unknown_node_is_ok(self):
        monitor = HealthMonitor()
        for k in range(10):
            monitor.observe(self.message("F1", k + 1), k * 0.5)
        for k, seq in enumerate(s for s in range(1, 60) if s % 2):
            monitor.observe(self.message("F2", seq), k * 0.5)
        self.assertEqual(monitor.state("F1", 5.0), OK)
        self.assertEqual(monitor.state("F2", 14.0), DEGRADED)
        self.assertEqual(monitor.state("F9", 5.0), OK)

    def test_trust_falls_with_age_and_with_a_bad_state(self):
        monitor = HealthMonitor()
        for k in range(10):
            monitor.observe(self.message("F1", k + 1), k * 0.5)
        self.assertAlmostEqual(monitor.trust("F1", 5.0, 0.0), 1.0)
        self.assertAlmostEqual(monitor.trust("F1", 5.0, 10.0), 0.5)         # the half-life
        self.assertLess(monitor.trust("F1", 5.0 + 5.0), 0.3)                # silent 5 s: offline
        self.assertEqual(monitor.trust("F1", 5.0 + 20.0), 0.0)              # presumed dead

    def test_a_cut_off_node_explains_its_silence_but_a_healthy_one_does_not(self):
        monitor = HealthMonitor()
        for k in range(10):
            monitor.observe(self.message("F1", k + 1), k * 0.5)
        self.assertLess(monitor.explains_silence("F1", 5.0), 0.2)
        self.assertEqual(monitor.explains_silence("F1", 5.0 + 6.0), 1.0)    # offline
        self.assertEqual(monitor.explains_silence("F1", 5.0 + 20.0), 0.5)   # presumed dead: only in part

    def test_late_readings_are_flagged(self):
        monitor = HealthMonitor()
        self.assertFalse(monitor.is_late(2.9))
        self.assertTrue(monitor.is_late(3.1))


class TestWeighted(unittest.TestCase):
    def reading(self):
        return Measurement(BEARING, 0.0, "F1", "cam", Pose2D(0.0, 0.0), 400.0, bearing=1.0, sigma_bearing=0.02)

    def test_full_trust_leaves_it_alone_less_trust_widens_it_and_none_drops_it(self):
        m = self.reading()
        self.assertIs(weighted(m, 1.0), m)
        self.assertAlmostEqual(weighted(m, 0.25).sigma_bearing, 0.04)
        self.assertIsNone(weighted(m, 0.0))


class TestEstimatorUsesIt(unittest.TestCase):
    def run_outage(self, explained):
        """F1's beacons stop at 5 s; F2 keeps sending, so the delivery rate the estimator measures stays high."""
        est = FriendFoeEstimator(EstimatorConfig(min_updates=2))
        if explained is not None:
            est.silence_explained = lambda friend_id, t: explained
        cls = None
        for k in range(80):
            t = k * 0.5
            t1 = TrackState("T1", t, (100.0 + 10 * t, 100.0, 60.0), (10.0, 0.0, 0.0), 3.0, observed_t=t)
            t2 = TrackState("T2", t, (100.0 + 10 * t, 400.0, 60.0), (10.0, 0.0, 0.0), 3.0, observed_t=t)
            beacons = [Beacon("F2", t, t2.position, t2.velocity, 3.0)]
            if t < 5.0:
                beacons.append(Beacon("F1", t, t1.position, t1.velocity, 3.0))
            cls = est.update(t, [t1, t2], beacons)[0].cls
        return cls
    def test_without_a_hook_a_drone_whose_beacons_stop_fades_out_of_friendly(self):
        self.assertNotEqual(self.run_outage(None), "friendly")

    def test_while_its_link_is_known_to_be_down_it_stays_friendly(self):
        self.assertEqual(self.run_outage(1.0), "friendly")

    def test_an_unexplained_silence_fades_it_like_before(self):
        self.assertNotEqual(self.run_outage(0.0), "friendly")


if __name__ == "__main__":
    unittest.main()
