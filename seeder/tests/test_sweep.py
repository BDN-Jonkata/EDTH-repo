"""Tests for scenario sweeps. Run from the repo root:  python -m unittest discover -s seeder/tests -v"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "seeder"))

import scenario as sc  # noqa: E402
import sweep as sw  # noqa: E402

CONFIG = json.loads((ROOT / "scenarios" / "medium.json").read_text(encoding="utf-8"))


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class Sweep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_folder_per_seed_with_the_three_files(self):
        index = sw.sweep(CONFIG, "tuning", self.out, count=3)
        self.assertEqual([r["seed"] for r in index["runs"]], [1, 2, 3])
        for seed in (1, 2, 3):
            for name in ("scenario.json", "truth.json", "run.json"):
                self.assertTrue((self.out / str(seed) / name).exists(), "%s/%s" % (seed, name))
        self.assertEqual(read(self.out / "index.json"), index)

    def test_the_test_set_uses_its_own_seed_range(self):
        index = sw.sweep(CONFIG, "test", self.out, count=2)
        self.assertEqual([r["seed"] for r in index["runs"]], [1000, 1001])
        self.assertEqual({r["seed_set"] for r in index["runs"]}, {"test"})

    def test_a_run_matches_a_single_generate_with_the_same_seed(self):
        sw.sweep(CONFIG, "tuning", self.out, count=2)
        scenario, truth = sc.generate(dict(CONFIG, seed_set="tuning", seed=2))
        self.assertEqual(read(self.out / "2" / "scenario.json"), json.loads(json.dumps(scenario)))
        self.assertEqual(read(self.out / "2" / "truth.json"), json.loads(json.dumps(truth)))

    def test_the_summary_says_what_the_run_is(self):
        sw.sweep(CONFIG, "tuning", self.out, count=1)
        run = read(self.out / "1" / "run.json")
        self.assertEqual((run["seed"], run["seed_set"], run["index"]), (1, "tuning", 0))
        self.assertEqual(run["hostiles"], len(read(self.out / "1" / "scenario.json")["targets"]))

    def test_the_whole_tuning_set_is_99_seeds_and_the_test_set_100(self):
        self.assertEqual(len(sw.sweep(CONFIG, "tuning", self.out, truth_dt=5.0)["runs"]), 99)
        self.assertEqual(len(sw.sweep(CONFIG, "test", self.out / "t", truth_dt=5.0)["runs"]), 100)


class Command(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "seeder" / "generate.py"), str(ROOT / "scenarios" / "medium.json"), *args],
                              capture_output=True, text=True, cwd=ROOT)

    def test_sweep_cannot_be_mixed_with_one_seed(self):
        for extra in (["--seed", "5"], ["--seed-set", "test"]):
            r = self.run_cli("--sweep", "tuning", *extra)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("picks the seeds itself", r.stderr)

    def test_the_test_set_prints_the_reminder(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = self.run_cli("--sweep", "test", "--count", "1", "--out", tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("run it once", r.stdout)


if __name__ == "__main__":
    unittest.main()
