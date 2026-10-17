"""Tests for the identity keeper."""

import unittest

from predictor.identity import IdentityKeeper
from tracker.ekf import identity_like
from tracker.tracker import Track


def track(track_id, x, y, vx=10.0, vy=0.0, friend=None):
    return Track(track_id, [x, y, vx, vy], identity_like([25.0, 25.0, 1.0, 1.0]), 0.0, 0.0, confirmed=True, friend_id=friend)


class TestIdentityKeeper(unittest.TestCase):
    def test_a_track_that_starts_where_a_lost_one_was_heading_gets_its_id_back(self):
        keeper = IdentityKeeper()
        keeper.step(0.0, [track("T1", 100.0, 0.0)])
        keeper.step(1.0, [])                                          # lost
        out = keeper.step(9.0, [track("T7", 190.0, 3.0)])             # 9 s later, near 100 + 10 * 9
        self.assertEqual([tr.track_id for tr in out], ["T1"])
        self.assertEqual(keeper.step(9.5, [track("T7", 195.0, 3.0)])[0].track_id, "T1")

    def test_a_track_far_from_where_it_should_be_keeps_its_own_id(self):
        keeper = IdentityKeeper()
        keeper.step(0.0, [track("T1", 100.0, 0.0)])
        keeper.step(1.0, [])
        self.assertEqual(keeper.step(9.0, [track("T7", 190.0, 400.0)])[0].track_id, "T7")

    def test_a_different_heading_is_not_the_same_target(self):
        keeper = IdentityKeeper()
        keeper.step(0.0, [track("T1", 100.0, 0.0, 10.0, 0.0)])
        keeper.step(1.0, [])
        self.assertEqual(keeper.step(2.0, [track("T7", 110.0, 0.0, -10.0, 0.0)])[0].track_id, "T7")

    def test_two_new_tracks_cannot_take_the_same_id(self):
        keeper = IdentityKeeper()
        keeper.step(0.0, [track("T1", 100.0, 0.0)])
        keeper.step(1.0, [])
        ids = [tr.track_id for tr in keeper.step(3.0, [track("T7", 130.0, 0.0), track("T8", 132.0, 5.0)])]
        self.assertEqual(sorted(ids), ["T1", "T8"] if ids[0] == "T1" else ["T1", "T7"])

    def test_a_lost_id_is_forgotten_after_the_gap_limit(self):
        keeper = IdentityKeeper()
        keeper.step(0.0, [track("T1", 100.0, 0.0)])
        keeper.step(1.0, [])
        self.assertEqual(keeper.step(60.0, [track("T7", 700.0, 0.0)])[0].track_id, "T7")

    def test_friend_tracks_keep_their_ids(self):
        keeper = IdentityKeeper()
        out = keeper.step(0.0, [track("T1", 0.0, 0.0, friend="F1")])
        self.assertEqual(out[0].track_id, "T1")


if __name__ == "__main__":
    unittest.main()
