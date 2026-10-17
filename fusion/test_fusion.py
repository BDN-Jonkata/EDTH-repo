"""Tests for covariance intersection, the local_track message and the merger."""

import math
import random
import unittest

from common.codec import Sequencer
from fusion.ci import WEIGHT_STEPS, _mix as mix, intersect, intersect_all, inverse
from fusion.merger import Merger
from fusion.messages import local_track_message, state_and_cov
from tracker.ekf import identity_like
from tracker.tracker import Track


def diag(*values):
    return identity_like(list(values))


def message(node, local_id, t, x, y, sigma=5.0, vx=10.0, vy=0.0, friend=None, vel_sigma=1.0):
    track = Track(local_id, [x, y, vx, vy], diag(sigma ** 2, sigma ** 2, vel_sigma ** 2, vel_sigma ** 2),
                  0.0, t, confirmed=True, friend_id=friend)
    return local_track_message(node, track, t, Sequencer(node))


def random_covariance(rng):
    """A positive definite 4x4 matrix with correlated entries."""
    a = [[rng.gauss(0, 1) for _ in range(4)] for _ in range(4)]
    scale = rng.choice([1.0, 10.0, 100.0])
    return [[scale * sum(a[i][k] * a[j][k] for k in range(4)) + (1.0 if i == j else 0.0) for j in range(4)] for i in range(4)]


class TestCovarianceIntersection(unittest.TestCase):
    def test_inverse(self):
        m = [[4.0, 1.0], [1.0, 3.0]]
        i = inverse(m)
        product = [[sum(m[r][k] * i[k][c] for k in range(2)) for c in range(2)] for r in range(2)]
        for r in range(2):
            for c in range(2):
                self.assertAlmostEqual(product[r][c], 1.0 if r == c else 0.0)

    def test_the_merge_is_never_more_certain_than_the_better_input_allows_for_correlation(self):
        x, p = intersect([0.0, 0.0, 0.0, 0.0], diag(25.0, 25.0, 1.0, 1.0), [0.0, 0.0, 0.0, 0.0], diag(25.0, 25.0, 1.0, 1.0))
        self.assertAlmostEqual(p[0][0], 25.0, places=6)         # the same information twice adds nothing

    def test_a_sharper_estimate_dominates_and_the_merge_lies_between(self):
        x, p = intersect([0.0, 0.0, 0.0, 0.0], diag(4.0, 4.0, 1.0, 1.0), [30.0, 0.0, 0.0, 0.0], diag(400.0, 400.0, 1.0, 1.0))
        self.assertLess(x[0], 10.0)
        self.assertLess(p[0][0], 4.5)                           # about the sharper one's own 4 (the weight grid stops at 0.95)

    def test_the_fast_weight_search_picks_the_same_weight_as_trying_every_one(self):
        rng = random.Random(7)
        for _ in range(60):
            p1, p2 = random_covariance(rng), random_covariance(rng)
            info1, info2 = inverse(p1), inverse(p2)
            sizes = [(inverse(mix(s / WEIGHT_STEPS, info1, info2))[0][0] + inverse(mix(s / WEIGHT_STEPS, info1, info2))[1][1], s)
                     for s in range(1, WEIGHT_STEPS)]
            _, p = intersect([0.0] * 4, p1, [0.0] * 4, p2)
            expected = inverse(mix(min(sizes)[1] / WEIGHT_STEPS, info1, info2))
            for r in range(4):
                for c in range(4):
                    self.assertAlmostEqual(p[r][c], expected[r][c], places=9)

    def test_a_covariance_with_no_spread_in_one_direction_does_not_stop_the_merge(self):
        x, p = intersect([0.0] * 4, [[0.0] * 4 for _ in range(4)], [1.0, 1.0, 0.0, 0.0], diag(25.0, 25.0, 1.0, 1.0))
        self.assertTrue(all(math.isfinite(v) for v in x))

    def test_three_estimates_fold(self):
        e = ([1.0, 1.0, 0.0, 0.0], diag(9.0, 9.0, 1.0, 1.0))
        x, p = intersect_all([e, e, e])
        self.assertAlmostEqual(x[0], 1.0)
        self.assertAlmostEqual(p[0][0], 9.0, places=5)


class TestMessage(unittest.TestCase):
    def test_roundtrip_through_the_six_vector(self):
        m = message("N1", "T3", 5.0, 100.0, 200.0, friend="F1")
        state, cov = state_and_cov(m)
        self.assertEqual(state, [100.0, 200.0, 10.0, 0.0])
        self.assertEqual(cov[0][0], 25.0)
        self.assertEqual(m["type"], "local_track")
        self.assertEqual(m["friend_id"], "F1")
        self.assertEqual(len(m["state"]), 6)


class TestBearingHub(unittest.TestCase):
    def report(self, node, sensor, t, bearing_deg, x, y):
        import math
        from fusion.messages import bearing_report_message
        from tracker.measurement import BEARING, Measurement, Pose2D
        m = Measurement(BEARING, t, node, sensor, Pose2D(x, y), 400.0, bearing=math.radians(bearing_deg), sigma_bearing=0.02)
        return bearing_report_message(m, Sequencer(node))

    def test_the_report_roundtrips_into_a_measurement(self):
        from fusion.messages import measurement_from_report
        m = measurement_from_report(self.report("D1", "cam", 3.0, 40.0, 10.0, 20.0))
        self.assertEqual((m.node, m.sensor_id, m.t, m.pose.x, m.pose.y), ("D1", "cam", 3.0, 10.0, 20.0))

    def test_two_nodes_bearings_that_cross_start_a_track_at_the_merger(self):
        import math
        from fusion.hub import BearingHub
        hub = BearingHub()
        target = (200.0, 150.0)
        tracks = []
        for k in range(40):
            t = k * 0.2
            batch = []
            for node, (px, py) in (("D1", (0.0, 0.0)), ("D2", (400.0, 0.0))):
                bearing = math.degrees(math.atan2(target[1] - py, target[0] - px))
                batch.append(self.report(node, "cam", t, bearing, px, py))
            tracks = hub.step(t, batch)
        self.assertTrue(tracks)
        self.assertAlmostEqual(tracks[0]["state"][0], 200.0, delta=15.0)


class TestMerger(unittest.TestCase):
    def test_two_nodes_seeing_one_object_become_one_track_with_a_tighter_position(self):
        merger = Merger()
        merger.ingest([message("N1", "N1/T1", 0.0, 100.0, 100.0, 8.0), message("N2", "N2/T1", 0.0, 104.0, 98.0, 8.0)])
        tracks = merger.step(0.0)
        self.assertEqual(len(tracks), 1)
        self.assertAlmostEqual(tracks[0].state[0], 102.0, delta=3.0)

    def test_far_apart_tracks_stay_separate(self):
        merger = Merger()
        merger.ingest([message("N1", "N1/T1", 0.0, 100.0, 100.0), message("N2", "N2/T1", 0.0, 400.0, 100.0)])
        self.assertEqual(len(merger.step(0.0)), 2)

    def test_two_tracks_of_one_node_are_never_merged(self):
        merger = Merger()
        merger.ingest([message("N1", "N1/T1", 0.0, 100.0, 100.0), message("N1", "N1/T2", 0.0, 101.0, 100.0)])
        self.assertEqual(len(merger.step(0.0)), 2)

    def test_the_global_id_survives_a_node_dropping_out_and_a_new_local_id(self):
        merger = Merger()
        merger.ingest([message("N1", "N1/T1", 0.0, 100.0, 100.0), message("N2", "N2/T1", 0.0, 102.0, 100.0)])
        gid = merger.step(0.0)[0].track_id
        merger.ingest([message("N1", "N1/T1", 1.0, 110.0, 100.0)])           # N2 went quiet
        self.assertEqual(merger.step(1.0)[0].track_id, gid)
        merger.ingest([message("N1", "N1/T1", 2.0, 120.0, 100.0), message("N3", "N3/T9", 2.0, 121.0, 100.0)])
        self.assertEqual({t.track_id for t in merger.step(2.0)}, {gid})       # a third node joins the same object

    def test_silent_nodes_expire_and_their_id_is_freed(self):
        merger = Merger()
        merger.ingest([message("N1", "N1/T1", 0.0, 100.0, 100.0)])
        merger.step(0.0)
        self.assertEqual(merger.step(10.0), [])

    def test_friend_identity_is_kept_on_the_merged_track(self):
        merger = Merger()
        merger.ingest([message("N1", "N1/T1", 0.0, 100.0, 100.0, friend="F1"), message("N2", "N2/T2", 0.0, 101.0, 100.0)])
        self.assertEqual(merger.step(0.0)[0].friend_id, "F1")

    def test_a_delayed_update_does_not_roll_back_the_latest_state(self):
        newest = message("N1", "T1", 10.0, 100.0, 100.0)
        delayed = message("N1", "T1", 9.0, 80.0, 100.0)
        delayed["header"]["seq"] = 99   # a new packet can still carry an older state
        for batch in ([newest, delayed], [delayed, newest]):
            with self.subTest(order=[m["t_state"] for m in batch]):
                merger = Merger()
                merger.ingest(batch)
                self.assertEqual(merger.step(10.0)[0].state, [100.0, 100.0, 10.0, 0.0])

    def test_same_time_updates_keep_the_newest_sequence_and_ignore_replays(self):
        merger = Merger()
        newest = message("N1", "T1", 10.0, 100.0, 100.0)
        newest["header"]["seq"] = 20
        replay = message("N1", "T1", 10.0, 80.0, 100.0)
        replay["header"]["seq"] = 19
        merger.ingest([newest, replay])
        self.assertEqual(merger.step(10.0)[0].state[0], 100.0)
        correction = message("N1", "T1", 10.0, 101.0, 100.0)
        correction["header"]["seq"] = 21
        merger.ingest([correction, newest])
        self.assertEqual(merger.step(10.0)[0].state[0], 101.0)
        self.assertEqual(merger.step(15.0), [])
        merger.ingest([replay])
        self.assertEqual(merger.step(15.0), [])

    def test_distinct_verified_friends_do_not_merge_even_through_an_unidentified_track(self):
        merger = Merger()
        merger.ingest([message("N1", "T1", 0.0, 100.0, 100.0, friend="F1"),
                       message("N2", "T1", 0.0, 101.0, 100.0),
                       message("N3", "T1", 0.0, 102.0, 100.0, friend="F2")])
        tracks = merger.step(0.0)
        self.assertEqual(len(tracks), 2)
        self.assertEqual({tr.friend_id for tr in tracks}, {"F1", "F2"})

    def test_opposite_moving_targets_keep_two_global_ids_through_the_crossing(self):
        merger = Merger()
        identities = None
        for t in (0.0, 0.5, 1.0, 1.5, 2.0):
            batch = [message(node, local_id, t, x + offset, 100.0, vx=vx)
                     for node, offset in (("N1", 0.0), ("N2", 1.0))
                     for local_id, x, vx in (("T1", 90.0 + 10.0 * t, 10.0),
                                             ("T2", 110.0 - 10.0 * t, -10.0))]
            merger.ingest(batch)
            tracks = merger.step(t)
            self.assertEqual(len(tracks), 2)
            by_direction = {tr.state[2] > 0: tr.track_id for tr in tracks}
            if identities is None:
                identities = by_direction
            self.assertEqual(by_direction, identities)

    def test_opposing_targets_from_different_nodes_are_not_one_object(self):
        merger = Merger()
        merger.ingest([message("N1", "T1", 0.0, 100.0, 100.0, vx=10.0),
                       message("N2", "T1", 0.0, 105.0, 100.0, vx=-10.0)])
        self.assertEqual(len(merger.step(0.0)), 2)

    def test_a_vague_velocity_cannot_bridge_two_incompatible_targets(self):
        merger = Merger()
        merger.ingest([message("N1", "T1", 0.0, 100.0, 100.0, vx=10.0),
                       message("N2", "T1", 0.0, 101.0, 100.0, vx=0.0, vel_sigma=10.0),
                       message("N3", "T1", 0.0, 102.0, 100.0, vx=-10.0)])
        self.assertEqual(len(merger.step(0.0)), 2)

    def test_velocity_gate_allows_measurement_noise_according_to_its_uncertainty(self):
        merger = Merger()
        merger.ingest([message("N1", "T1", 0.0, 100.0, 100.0, vx=10.0, vel_sigma=10.0),
                       message("N2", "T1", 0.0, 101.0, 100.0, vx=-2.0, vel_sigma=10.0)])
        self.assertEqual(len(merger.step(0.0)), 1)


if __name__ == "__main__":
    unittest.main()
