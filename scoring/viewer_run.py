"""Read a run exported from the viewer's mock simulation (`ui/viewer/export-run.js`, or the `simulations` table).

A run is `{params, scenario, result}` (docs/data-formats.md, "Saved simulation run"). Every frame holds the tracks
the mock produced and the true state of every object at that moment, so the truth comes from the run itself and is
right for commanded drones too (they leave the patrol in `truth.json`, see `scoring.truth.with_recorded_samples`).

    from scoring.viewer_run import score_viewer_run
    result = score_viewer_run(json.load(open("run.json")), window_s=(45, 90))
"""

from typing import Dict, Iterator, List, Optional, Tuple

from common.seeder_import import ensure_seeder_on_path
from scoring.metrics import Estimate, RunScore, ScoreConfig, score

ensure_seeder_on_path()
from tables import unpack  # noqa: E402  (seeder/tables.py reads the compact run format)

Frames = Iterator[Tuple[float, List[Estimate]]]


def frames_from_viewer_run(run: dict, hostile_only: bool = False, window_s: Optional[Tuple[float, float]] = None) -> Frames:
    """(t, [Estimate]) per frame, from the tracks the mock had confirmed or coasting (not tentative).

    The track's class is kept. The mock counts only `hostile` tracks as hostiles, whereas `scoring` counts every class
    except friendly and peaceful; `hostile_only` leaves the other tracks out, which matches the mock's own summary.
    `window_s` = (from, to) keeps only the frames in that time window (the mock's summary uses one around the crossing)."""
    for f in unpack(run["result"])["frames"]:
        if window_s and not window_s[0] <= f["t"] <= window_s[1]:
            continue
        tracks = [tr for tr in f["tracks"] if tr["st"] != "tentative" and (tr["cls"] == "hostile" or not hostile_only)]
        yield f["t"], [Estimate(tr["id"], f["t"], tr["x"], tr["y"], tr["vx"], tr["vy"], tr["cls"]) for tr in tracks]


def truth_from_viewer_run(run: dict) -> dict:
    """A `truth.json`-shaped dict (`objects` with `[t, x, y, vx, vy]` samples) built from the true states in the frames."""
    objects: Dict[str, dict] = {}
    for f in unpack(run["result"])["frames"]:
        for o in f["truth"]:
            obj = objects.setdefault(o["id"], {"id": o["id"], "kind": o["kind"], "samples": []})
            obj["samples"].append([f["t"], o["x"], o["y"], o["vx"], o["vy"]])
    return {"scenario_id": run["scenario"].get("id"), "objects": list(objects.values())}


def score_viewer_run(run: dict, hostile_only: bool = False, window_s: Optional[Tuple[float, float]] = None,
                     config: Optional[ScoreConfig] = None) -> RunScore:
    return score(truth_from_viewer_run(run), frames_from_viewer_run(run, hostile_only, window_s), config)
