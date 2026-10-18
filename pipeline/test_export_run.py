"""The exported run must be readable by the viewer's COP page and by `scoring.viewer_run`, and say the same thing."""

import json
import math
import sys
import unittest
from functools import lru_cache

from common.seeder_import import ensure_seeder_on_path
from pipeline.export_run import ENGINE, export
from scoring.metrics import ScoreConfig
from scoring.viewer_run import score_viewer_run

ensure_seeder_on_path()
from tables import pack_rows, unpack  # noqa: E402


@lru_cache(maxsize=1)
def exported_run() -> dict:
    run = export("challenge", "tuning", 0, 0.3, "clear", {"cue": False, "investigate": False, "distributed": False})
    return json.loads(json.dumps(run, allow_nan=False))       # what a file holds: plain JSON, no NaN


class TestExportedRun(unittest.TestCase):
    def test_it_says_which_engine_made_it_and_how(self):
        run = exported_run()
        self.assertEqual(run["engine"], ENGINE)
        self.assertEqual((run["params"]["preset"], run["params"]["loss"], run["params"]["seed"]), ("challenge", 0.3, run["scenario"]["seed"]))

    def test_one_frame_per_tenth_of_a_second_with_tracks_truth_and_counts(self):
        frames = unpack(exported_run()["result"])["frames"]
        self.assertEqual(len(frames), int(exported_run()["scenario"]["duration_s"] / 0.1) + 1)
        self.assertEqual(sorted(frames[300]), ["k", "m", "t", "tracks", "truth"])
        self.assertEqual(sorted(frames[300]["tracks"][0]), ["cls", "id", "st", "vx", "vy", "x", "y"])
        self.assertEqual(sorted(frames[300]["truth"][0]), ["id", "kind", "vx", "vy", "x", "y"])
        self.assertEqual(sorted(frames[300]["m"]), ["est", "presumed", "tru"])

    def test_the_counts_match_the_tracks_and_the_truth_in_the_frame(self):
        for f in unpack(exported_run()["result"])["frames"][::97]:
            self.assertEqual(f["m"]["est"], sum(tr["cls"] == "hostile" for tr in f["tracks"]))
            self.assertEqual(f["m"]["tru"], sum(o["kind"] == "hostile" for o in f["truth"]))
            self.assertEqual(f["m"]["presumed"], sum(tr["cls"] not in ("friendly", "peaceful") for tr in f["tracks"]))

    def test_the_scoring_reader_gets_the_same_result_as_the_summary_written_with_it(self):
        run = exported_run()
        read_back = score_viewer_run(run, config=ScoreConfig(warmup_s=10.0, continuity_m=0.0))
        written = run["result"]["summary"]["whole_run"]
        # Positions are stored to 0.1 m and the truth is re-sampled at the frame times, so a match at the edge of the
        # scoring gate can flip: close, not identical.
        for field in ("hostile_tracked_frac", "count_error_mean_abs", "false_tracks_mean"):
            self.assertAlmostEqual(getattr(read_back, field), written[field], delta=0.01, msg=field)
        self.assertAlmostEqual(read_back.pos_rmse_m, written["pos_rmse_m"], delta=0.3)
        self.assertLessEqual(abs(read_back.id_swaps - written["id_swaps"]), 1)
        self.assertEqual(read_back.friendlies_flagged, written["friendlies_flagged"])

    def test_the_summary_has_no_nan(self):
        json.dumps(exported_run()["result"]["summary"], allow_nan=False)


class TestPackRows(unittest.TestCase):
    def test_same_shaped_rows_become_a_table_and_unpack_returns_them(self):
        rows = [{"id": "a", "x": 1}, {"id": "b", "x": 2}]
        self.assertEqual(pack_rows(rows), {"cols": ["id", "x"], "rows": [["a", 1], ["b", 2]]})
        self.assertEqual(unpack(pack_rows(rows)), rows)

    def test_one_row_empty_or_differently_shaped_rows_stay_as_they_are(self):
        for rows in ([], [{"id": "a"}], [{"id": "a"}, {"x": 1}]):
            self.assertEqual(pack_rows(rows), rows)
            self.assertEqual(unpack(pack_rows(rows)), rows)


if __name__ == "__main__":
    unittest.main()
