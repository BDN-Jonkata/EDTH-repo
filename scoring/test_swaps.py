"""The ID swap log: each swap is recorded with its context and sorted into a cause."""

import unittest

from scoring.metrics import Estimate, ScoreConfig, swap_log
from scoring.swaps import cause, summarise


def truth(*objects):
    return {"objects": [{"id": i, "kind": k, "samples": [[0.0, x, y, 0.0, 0.0], [100.0, x, y, 0.0, 0.0]]} for i, k, x, y in objects]}


def est(track_id, x, y):
    return Estimate(track_id, 0.0, x, y)


class TestSwapLog(unittest.TestCase):
    def test_a_dropped_track_and_a_new_one_is_a_restart(self):
        frames = [(1.0, [est("T1", 0, 0)]), (2.0, []), (3.0, [est("T9", 1, 0)])]
        events = swap_log(truth(("H1", "hostile", 0, 0)), frames)
        self.assertEqual([cause(e) for e in events], ["restart"])
        self.assertEqual(events[0]["old"], "T1")
        self.assertEqual(events[0]["new"], "T9")

    def test_two_hostiles_trading_tracks_is_a_crossing_with_the_other_close(self):
        t = truth(("H1", "hostile", 0, 0), ("H2", "hostile", 100, 0))
        # H1 is on T1, H2 on T2; then the tracks swap places
        frames = [(1.0, [est("T1", 0, 0), est("T2", 100, 0)]), (2.0, [est("T1", 100, 0), est("T2", 0, 0)])]
        s = summarise(swap_log(t, frames, ScoreConfig(continuity_m=0.0)))
        self.assertEqual(s["crossing"], 2)
        self.assertEqual(s["total"], 2)

    def test_a_ghost_left_behind_when_the_hostile_jumps_to_another_track(self):
        t = truth(("H1", "hostile", 0, 0))
        frames = [(1.0, [est("T1", 0, 0)]), (2.0, [est("T1", 300, 0), est("T2", 2, 0)])]
        events = swap_log(t, frames)
        self.assertEqual([cause(e) for e in events], ["ghost"])

    def test_no_swap_no_events(self):
        frames = [(1.0, [est("T1", 0, 0)]), (2.0, [est("T1", 1, 0)])]
        self.assertEqual(swap_log(truth(("H1", "hostile", 0, 0)), frames), [])

    def test_swap_count_matches_the_scored_number(self):
        from scoring.metrics import score
        t = truth(("H1", "hostile", 0, 0))
        frames = [(1.0, [est("T1", 0, 0)]), (2.0, []), (3.0, [est("T9", 1, 0)]), (4.0, [est("T9", 1, 0)])]
        self.assertEqual(score(t, frames).id_swaps, len(swap_log(t, frames)))


if __name__ == "__main__":
    unittest.main()
