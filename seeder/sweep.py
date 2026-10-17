"""Generate every seed of a set: one folder per run for scoring to read.

    python seeder/generate.py scenarios/hard.json --sweep tuning
    python seeder/generate.py scenarios/hard.json --sweep test --out out/final   (run once, at the end)

Layout: <out>/index.json lists the runs; <out>/<seed>/ holds scenario.json, truth.json and run.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import scenario as sc


def write_run(folder, scenario, truth):
    """The two files every generated run has: scenario.json for the system, truth.json for scoring only."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "scenario.json").write_text(json.dumps(scenario, indent=1), encoding="utf-8")
    (folder / "truth.json").write_text(json.dumps(truth, separators=(",", ":")), encoding="utf-8")


def run_summary(scenario, truth, seed_set, index):
    crossings = [e for e in truth["events"] if e["type"] == "crossing"]
    benign = [t for t in scenario["targets"] if t.get("role") == "benign"]
    return {"scenario_id": scenario["id"], "seed": scenario["seed"], "seed_set": seed_set, "index": index,
            "hostiles": len(scenario["targets"]) - len(benign), "benign": len(benign), "crossings": len(crossings)}


def sweep(config, seed_set, out, truth_dt=0.1, count=None, progress=None):
    """Generate the seeds of `seed_set` (all of them, or the first `count`) into `out`; return the index."""
    lo, hi = sc.SEED_SETS[seed_set]
    total = hi - lo + 1 if count is None else min(count, hi - lo + 1)
    runs = []
    for index in range(total):
        cfg = dict(config, seed_set=seed_set, seed=sc.seed_for(seed_set, index))
        scenario, truth = sc.generate(cfg, truth_dt=truth_dt)
        summary = run_summary(scenario, truth, seed_set, index)
        write_run(out / str(scenario["seed"]), scenario, truth)
        (out / str(scenario["seed"]) / "run.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
        runs.append(summary)
        if progress:
            progress(index + 1, total)
    index_doc = {"seed_set": seed_set, "runs": runs}
    (out / "index.json").write_text(json.dumps(index_doc, indent=1), encoding="utf-8")
    return index_doc
