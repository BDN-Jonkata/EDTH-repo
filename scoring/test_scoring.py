"""Tests for the scoring module: assignment, truth lookup, each metric on hand-made cases, and one seeder run."""

import math
import unittest

from common.seeder_import import ensure_seeder_on_path
from common.assignment import assign
from scoring.metrics import Estimate, ScoreConfig, ospa, score
from scoring.tracks import frames_from_estimator, frames_from_local_tracks
from scoring.truth import load_truth

TIMES = [i * 0.5 for i in range(21)]   # 0 .. 10 s


def moving(obj_id, kind, x0, y0, vx, vy, times=TIMES):
    return {"id": obj_id, "kind": kind, "samples": [[t, x0 + vx * t, y0 + vy * t, vx, vy] for t in times]}


def truth_of(*objects):
    return {"objects": list(objects)}


def est(track_id, t, x, y, vx=0.0, vy=0.0, cls=None):
    return Estimate(track_id, t, x, y, vx, vy, cls)


def perfect_frames(objects, ids=None, cls=None):
    """One estimate per object per step, exactly on the truth."""
    ids = ids or {o["id"]: o["id"] for o in objects}
    for k, t in enumerate(TIMES):
        yield t, [est(ids[o["id"]], t, *o["samples"][k][1:], cls=(cls or {}).get(o["id"])) for o in objects]


class TestAssign(unittest.TestCase):
    def test_picks_the_cheapest_total_not_the_greedy_pairs(self):
        cost = [[1, 2], [1, 100]]                       # greedy takes (0,0) and then pays 100
        self.assertEqual(sorted(assign(cost)), [(0, 1), (1, 0)])

    def test_more_columns_than_rows(self):
        self.assertEqual(assign([[5, 1, 9]]), [(0, 1)])

    def test_more_rows_than_columns(self):
        self.assertEqual(assign([[5], [1], [9]]), [(1, 0)])

    def test_gate_drops_far_pairs(self):
        self.assertEqual(assign([[10, 99], [99, 70]], gate=50), [(0, 0)])

    def test_empty(self):
        self.assertEqual(assign([]), [])


class TestTruth(unittest.TestCase):
    def test_interpolates_between_samples_and_is_none_outside(self):
        obj = load_truth(truth_of(moving("H1", "hostile", 0, 0, 10, 0, [0.0, 1.0, 2.0])))["H1"]
        self.assertEqual(obj.state_at(0.5)[0], 5.0)
        self.assertIsNone(obj.state_at(5.0))
        self.assertIsNone(obj.state_at(-1.0))


class TestOspa(unittest.TestCase):
    def test_identical_sets_are_zero_and_a_missing_point_costs_the_cutoff(self):
        self.assertEqual(ospa([(0, 0)], [(0, 0)], 100.0, 2), 0.0)
        self.assertAlmostEqual(ospa([(0, 0), (500, 0)], [(0, 0)], 100.0, 2), math.sqrt(100.0 ** 2 / 2))
        self.assertEqual(ospa([], [], 100.0, 2), 0.0)


class TestScore(unittest.TestCase):
    def setUp(self):
        self.h1 = moving("H1", "hostile", 0, 0, 10, 0)
        self.h2 = moving("H2", "hostile", 0, 300, 10, 0)
        self.f1 = moving("F1", "friendly", 0, -300, 5, 0)

    def test_perfect_tracking_scores_zero_error(self):
        s = score(truth_of(self.h1, self.h2, self.f1),
                  perfect_frames([self.h1, self.h2, self.f1], cls={"F1": "friendly"}))
        self.assertEqual((s.count_error_mean_abs, s.id_swaps, s.friendlies_flagged), (0.0, 0, 0))
        self.assertAlmostEqual(s.pos_rmse_m, 0.0)
        self.assertAlmostEqual(s.vel_rmse_mps, 0.0)
        self.assertAlmostEqual(s.ospa_m, 0.0)
        self.assertEqual((s.hostile_detected_frac, s.friendly_flag_frac), (1.0, 0.0))

    def test_position_and_heading_error(self):
        frames = [(t, [est("a", t, x + 3.0, y, 10, 0), est("b", t, x2, y2 + 4.0, 0, 10)])
                  for (t, x, y, x2, y2) in [(s[0], *self.h1["samples"][k][1:3], *self.h2["samples"][k][1:3])
                                            for k, s in enumerate(self.h1["samples"])]]
        s = score(truth_of(self.h1, self.h2), frames)
        self.assertAlmostEqual(s.pos_rmse_m, math.sqrt((9 + 16) / 2))
        self.assertAlmostEqual(s.heading_rmse_deg, math.sqrt(90 ** 2 / 2))   # one track points 90 degrees off

    def test_missing_track_is_a_count_error(self):
        s = score(truth_of(self.h1, self.h2), perfect_frames([self.h1]))
        self.assertEqual((s.count_error_mean_abs, s.count_error_bias), (1.0, -1.0))
        self.assertEqual(s.hostile_detected_frac, 0.5)

    def test_id_swap_is_counted_once_per_change(self):
        frames = []
        for k, t in enumerate(TIMES):
            name = "a" if k < 10 else "b"               # the same hostile changes track id halfway
            frames.append((t, [est(name, t, *self.h1["samples"][k][1:3], cls="hostile")]))
        self.assertEqual(score(truth_of(self.h1), frames).id_swaps, 1)

    def test_noise_between_close_objects_is_not_an_id_swap(self):
        a, b = moving("H1", "hostile", 0, 0, 10, 0), moving("H2", "hostile", 0, 6, 10, 0)
        frames = []
        for k, t in enumerate(TIMES):
            x = a["samples"][k][1]
            ya, yb = (0.0, 6.0) if k < 3 else (4.5, 1.5)   # after a few exact steps each track sits nearer the other object
            frames.append((t, [est("a", t, x, ya, cls="hostile"), est("b", t, x, yb, cls="hostile")]))
        self.assertEqual(score(truth_of(a, b), frames).id_swaps, 0)
        self.assertEqual(score(truth_of(a, b), frames, ScoreConfig(continuity_m=0.0)).id_swaps, 2)   # both objects trade tracks

    def test_friendly_called_hostile_is_a_false_alarm(self):
        s = score(truth_of(self.f1), perfect_frames([self.f1], cls={"F1": "suspicious"}))
        self.assertEqual((s.friendlies_flagged, s.friendly_flag_frac), (1, 1.0))
        self.assertEqual(s.false_tracks_mean, 0.0)      # it sits on a friendly, so it is not a ghost

    def test_peaceful_clutter_is_not_flagged_and_a_bird_called_hostile_is(self):
        bird = moving("B1", "clutter", 0, 100, 8, 0)
        quiet = score(truth_of(bird), perfect_frames([bird], cls={"B1": "peaceful"}))
        loud = score(truth_of(bird), perfect_frames([bird], cls={"B1": "hostile"}))
        self.assertEqual((quiet.clutter_flagged_frac, loud.clutter_flagged_frac), (0.0, 1.0))
        self.assertEqual(loud.count_error_bias, 1.0)    # the operator counts one hostile too many

    def test_ghost_track_far_from_everything(self):
        frames = [(t, [est("ghost", t, 5000.0, 5000.0)]) for t in TIMES]
        s = score(truth_of(self.h1), frames)
        self.assertEqual(s.false_tracks_mean, 1.0)
        self.assertEqual(s.hostile_detected_frac, 0.0)

    def test_warmup_skips_early_steps(self):
        s = score(truth_of(self.h1), perfect_frames([self.h1]), ScoreConfig(warmup_s=5.0))
        self.assertEqual(s.steps, 11)


class TestTracks(unittest.TestCase):
    def test_local_track_messages_group_into_steps(self):
        def msg(i, t, cls=None):
            m = {"type": "local_track", "local_track_id": i, "t_state": t, "state": [1, 2, 3, 4, 5, 6]}
            return {**m, "class": cls} if cls else m
        frames = list(frames_from_local_tracks([msg("a", 0.01), msg("b", 0.02, "friendly"), msg("a", 0.52),
                                                {"type": "friendly_beacon"}]))
        self.assertEqual([t for t, _ in frames], [0.0, 0.5])
        self.assertEqual([(e.track_id, e.vx, e.cls) for e in frames[0][1]], [("a", 4, None), ("b", 4, "friendly")])


class TestSeederRun(unittest.TestCase):
    """The estimator on a generated scenario, scored with the real `truth.json` rows."""

    def test_clean_run_flags_no_friendly_and_swaps_no_id(self):
        ensure_seeder_on_path()
        import scenario as seeder_scenario
        from friend_foe.estimator import FriendFoeEstimator, for_scenario
        from friend_foe.scenario_adapter import frames_from_scenario
        from friend_foe.sweep import load_preset

        config = load_preset("easy")
        config["seed_set"], config["seed"] = "tuning", seeder_scenario.seed_for("tuning", 0)
        scenario, truth = seeder_scenario.generate(config)
        estimator = FriendFoeEstimator(for_scenario(scenario))
        frames = frames_from_estimator(frames_from_scenario(scenario, seed=scenario["seed"]), estimator.update)
        s = score(truth, frames, ScoreConfig(warmup_s=10.0))
        self.assertEqual((s.friendlies_flagged, s.id_swaps), (0, 0))
        self.assertLess(s.pos_rmse_m, 10.0)
        self.assertGreater(s.hostile_detected_frac, 0.9)


if __name__ == "__main__":
    unittest.main()
