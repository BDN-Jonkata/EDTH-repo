"""Tests for the learned motion model."""

import tempfile
import unittest
from pathlib import Path

from predictor.identity import IdentityConfig, IdentityKeeper
from predictor.motion import MotionModel, fit
from tracker.ekf import identity_like
from tracker.tracker import Track


def straight(seconds, vx=10.0):
    return [(float(s), vx * s, 0.0, vx, 0.0) for s in range(seconds)]


def turning(seconds):
    """Speed 10 m/s with the heading turning 6 degrees a second."""
    import math
    out, x, y = [], 0.0, 0.0
    for s in range(seconds):
        a = math.radians(6 * s)
        out.append((float(s), x, y, 10 * math.cos(a), 10 * math.sin(a)))
        x, y = x + 10 * math.cos(a), y + 10 * math.sin(a)
    return out


class TestMotionModel(unittest.TestCase):
    def test_straight_tracks_learn_no_spread_and_turning_ones_learn_a_lot(self):
        flat = fit({"a": straight(40)})
        bendy = fit({"a": turning(40)})
        self.assertAlmostEqual(flat.spread(10.0), 0.0, places=6)
        self.assertGreater(bendy.spread(10.0), 20.0)
        self.assertGreater(bendy.spread(20.0), bendy.spread(5.0))

    def test_spread_grows_past_the_last_horizon_and_shrinks_to_zero_at_zero(self):
        model = fit({"a": turning(60)})
        self.assertGreater(model.spread(60.0), model.spread(30.0))
        self.assertEqual(model.spread(0.0), 0.0)

    def test_save_and_load_round_trip(self):
        model = fit({"a": turning(40)})
        path = Path(tempfile.mkdtemp()) / "m.json"
        model.save(path)
        self.assertEqual(MotionModel.load(path), model)

    def test_the_keeper_uses_the_learned_gate(self):
        def track(i, x):
            return Track(i, [x, 0.0, 10.0, 0.0], identity_like([25.0, 25.0, 1.0, 1.0]), 0.0, 0.0, confirmed=True)
        tight = fit({"a": straight(40)})                     # learned: nothing deviates from a straight line
        keeper = IdentityKeeper(IdentityConfig(model=tight, min_gate_m=1.0))
        keeper.step(0.0, [track("T1", 100.0)])
        keeper.step(1.0, [])
        # 8 s later the straight line says x = 190; 60 m off is outside the learned gate, inside the guessed one
        self.assertEqual(keeper.step(9.0, [track("T7", 250.0)])[0].track_id, "T7")


if __name__ == "__main__":
    unittest.main()
