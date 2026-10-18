"""Export a run of the Python pipeline in the saved-run shape the viewer's COP page (`ui/viewer/cop.html`) reads.

    python -m pipeline.export_run --preset challenge --index 0 --loss 0.3 --out out/py-run.json

The file is `{engine, params, scenario, result}` like `ui/viewer/export-run.js` writes for the JavaScript mock
(docs/data-formats.md, "Saved simulation run"), so `scoring.viewer_run` reads it too. Frames are one per 0.1 s with the
confirmed tracks (`id x y vx vy st cls`), the true state of every object (`id kind x y vx vy`, for the evaluation
overlay only) and `m` = `{est, presumed, tru}`: hostile-labelled tracks, tracks that are neither friendly nor peaceful,
and true hostiles. Not in it, because the Python pipeline has no such thing: sensors, missions, coverage, node health,
measurements, alerts.
"""

import argparse
import json
import math
from pathlib import Path
from typing import Dict, List

from friend_foe.sweep import Setup, load_preset, make_scenario_and_truth
from common.seeder_import import ensure_seeder_on_path
from pipeline.run import scored_frames
from scoring.challenge import diagnose
from scoring.truth import load_truth, present_at, with_recorded_samples

ensure_seeder_on_path()
from tables import pack_rows  # noqa: E402  (seeder/tables.py)

ENGINE = "python-pipeline"
OPTIONS = ("cue", "investigate", "distributed")     # the pipeline options the exporter passes on


def _round(v: float, digits: int) -> float:
    return round(v, digits)


def _frame(k: int, t: float, estimates, objects) -> dict:
    tracks = [{"id": e.track_id, "x": _round(e.x, 1), "y": _round(e.y, 1), "vx": _round(e.vx, 2), "vy": _round(e.vy, 2),
               "st": "confirmed", "cls": e.cls or "unknown"} for e in estimates]
    truth = [{"id": o.id, "kind": o.kind, "x": _round(s[0], 1), "y": _round(s[1], 1), "vx": _round(s[2], 2), "vy": _round(s[3], 2)}
             for o, s in present_at(objects, t)]
    m = {"est": sum(tr["cls"] == "hostile" for tr in tracks),
         "presumed": sum(tr["cls"] not in ("friendly", "peaceful") for tr in tracks),
         "tru": sum(o["kind"] == "hostile" for o in truth)}
    return {"k": k, "t": t, "tracks": pack_rows(tracks), "truth": pack_rows(truth), "m": m}


def _finite(value):
    """JSON has no NaN: a metric that could not be computed becomes null."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_finite(v) for v in value]
    return value


def build_run(scenario: dict, truth: dict, options: Dict[str, bool], params: dict) -> dict:
    recorded: dict = {}
    scored = list(scored_frames(scenario, scenario["seed"], recorded=recorded, **options))
    objects_truth = with_recorded_samples(truth, recorded)       # a commanded drone is not where the patrol says
    objects = load_truth(objects_truth)
    frames: List[dict] = [_frame(k, t, estimates, objects) for k, (t, estimates) in enumerate(scored)]
    summary = _finite(diagnose(objects_truth, scored))
    return {"engine": ENGINE, "params": dict(params, options=options), "scenario": scenario,
            "result": {"frames": frames, "summary": summary, "T_END": scenario["duration_s"], "DT": 0.1}}


def export(preset: str, seed_set: str, index: int, loss: float, weather: str, options: Dict[str, bool]) -> dict:
    setup = Setup(load_preset(preset), seed_set, index + 1)
    scenario, truth = make_scenario_and_truth(setup, index, weather, loss, False)
    params = {"preset": preset, "seed_set": seed_set, "index": index, "seed": scenario["seed"], "loss": loss, "weather": weather}
    return build_run(scenario, truth, options, params)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--preset", default="challenge")
    ap.add_argument("--seed-set", default="tuning", choices=("tuning", "test"))
    ap.add_argument("--index", type=int, default=0, help="which seed of the set")
    ap.add_argument("--loss", type=float, default=0.0, help="message loss, 0 to 1")
    ap.add_argument("--weather", default="clear")
    for name in OPTIONS:
        ap.add_argument("--" + name, action="store_true")
    ap.add_argument("--out", default="out/py-run.json")
    args = ap.parse_args()
    run = export(args.preset, args.seed_set, args.index, args.loss, args.weather, {n: getattr(args, n) for n in OPTIONS})
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(run, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {path} ({path.stat().st_size / 1e6:.1f} MB, {len(run['result']['frames'])} frames)")


if __name__ == "__main__":
    main()
