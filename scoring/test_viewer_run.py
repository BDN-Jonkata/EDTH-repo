"""Tests for the reader of the viewer's run JSON. Run from the repo root:  python -m unittest scoring.test_viewer_run"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common.seeder_import import ensure_seeder_on_path
from scoring.viewer_run import frames_from_viewer_run, score_viewer_run, truth_from_viewer_run

ROOT = Path(__file__).resolve().parents[1]
ensure_seeder_on_path()
from tables import unpack  # noqa: E402


def track(track_id, x, cls, st="confirmed"):
    return {"id": track_id, "cls": cls, "st": st, "x": x, "y": 0.0, "vx": 5.0, "vy": 0.0}


def truth_row(object_id, kind, x):
    return {"id": object_id, "kind": kind, "x": x, "y": 0.0, "vx": 5.0, "vy": 0.0}


def small_run():
    """Three frames: a hostile and a friendly in view; a hostile track, a friendly track, a tentative ghost and an unknown."""
    frames = []
    for k in range(3):
        t = k * 0.1
        x = 100.0 + 5.0 * t
        frames.append({
            "t": t, "truth": [truth_row("H1", "hostile", x), truth_row("F1", "friendly", x + 200)],
            "tracks": [track("T1", x + 1, "hostile"), track("T2", x + 201, "friendly"),
                       track("T3", 900.0, "hostile", st="tentative"), track("T4", 700.0, "unknown")],
        })
    # the compact form the exporter writes: a list of same-shaped objects becomes {cols, rows}
    packed = {"cols": list(frames[0]), "rows": [[f[c] for c in frames[0]] for f in frames]}
    return {"params": {}, "scenario": {"id": "small"}, "result": {"frames": packed, "summary": {}}}


class TestReader(unittest.TestCase):
    def test_truth_comes_from_the_frames_with_the_kinds(self):
        truth = truth_from_viewer_run(small_run())
        self.assertEqual({o["id"]: o["kind"] for o in truth["objects"]}, {"H1": "hostile", "F1": "friendly"})
        self.assertEqual(len(truth["objects"][0]["samples"]), 3)
        self.assertEqual(truth["objects"][0]["samples"][0], [0.0, 100.0, 0.0, 5.0, 0.0])

    def test_tentative_tracks_are_left_out_and_the_class_is_kept(self):
        _t, ests = next(frames_from_viewer_run(small_run()))
        self.assertEqual([(e.track_id, e.cls) for e in ests], [("T1", "hostile"), ("T2", "friendly"), ("T4", "unknown")])

    def test_hostile_only_matches_the_mocks_own_count(self):
        _t, ests = next(frames_from_viewer_run(small_run(), hostile_only=True))
        self.assertEqual([e.track_id for e in ests], ["T1"])

    def test_the_window_keeps_only_the_frames_in_it(self):
        self.assertEqual([round(t, 1) for t, _ in frames_from_viewer_run(small_run(), window_s=(0.05, 0.15))], [0.1])

    def test_scoring_a_clean_run(self):
        s = score_viewer_run(small_run(), hostile_only=True)
        self.assertEqual((s.steps, s.id_swaps, s.friendlies_flagged), (3, 0, 0))
        self.assertEqual(s.count_error_mean_abs, 0)
        self.assertEqual(s.hostile_detected_frac, 1.0)
        self.assertLess(s.pos_rmse_m, 2.0)

    def test_an_unknown_track_counts_as_a_false_track_unless_hostile_only(self):
        s = score_viewer_run(small_run())
        self.assertGreater(s.false_tracks_mean, 0.9)
        self.assertGreater(s.count_error_mean_abs, 0.9)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the mock simulation")
class TestAgainstTheMock(unittest.TestCase):
    def test_the_count_error_matches_what_the_mock_recorded_in_its_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([sys.executable, str(ROOT / "seeder" / "generate.py"), str(ROOT / "scenarios" / "medium.json"),
                            "--out", tmp], check=True, capture_output=True)
            out = subprocess.run(["node", str(ROOT / "ui" / "viewer" / "export-run.js"), "--scenario", str(Path(tmp) / "scenario.json")],
                                 check=True, capture_output=True, text=True, encoding="utf-8").stdout
        run = json.loads(out)
        frames = [f for f in unpack(run["result"])["frames"] if 45 <= f["t"] <= 90]
        recorded = sum(abs(f["m"]["countErr"]) for f in frames) / len(frames)
        s = score_viewer_run(run, hostile_only=True, window_s=(45, 90))
        self.assertEqual(s.steps, len(frames))
        self.assertAlmostEqual(s.count_error_mean_abs, recorded, delta=0.05)
        self.assertEqual(s.friendlies_flagged, 0)


if __name__ == "__main__":
    unittest.main()
