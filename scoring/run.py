"""Score a run from files.

    python -m scoring.run out/<id>/truth.json tracks.jsonl [--gate 50] [--warmup 10]
    python -m scoring.run --viewer run.json [--hostile-only] [--from 45 --to 90]

`tracks.jsonl` holds `local_track` messages (one JSON object per line, see docs/data-formats.md).
`run.json` is a run exported from the viewer's mock simulation (`node ui/viewer/export-run.js`); it carries its own truth.
"""

import argparse
import json
from dataclasses import asdict

from common.codec import decode
from scoring.metrics import ScoreConfig, score
from scoring.tracks import frames_from_local_tracks
from scoring.viewer_run import score_viewer_run


def score_from_files(truth_path: str, tracks_path: str, config: ScoreConfig):
    with open(truth_path, encoding="utf-8") as f:
        truth = json.load(f)
    with open(tracks_path, encoding="utf-8") as f:
        messages = [decode(line) for line in f if line.strip()]
    return score(truth, frames_from_local_tracks(messages), config)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("truth", nargs="?")
    ap.add_argument("tracks", nargs="?")
    ap.add_argument("--viewer", help="score a run exported from the viewer instead of truth.json and tracks.jsonl")
    ap.add_argument("--hostile-only", action="store_true", help="with --viewer: count only tracks the mock called hostile")
    ap.add_argument("--from", dest="start", type=float, help="with --viewer: first second scored")
    ap.add_argument("--to", dest="end", type=float, help="with --viewer: last second scored")
    ap.add_argument("--gate", type=float, default=ScoreConfig.gate_m, help="metres within which a track is on an object")
    ap.add_argument("--warmup", type=float, default=0.0, help="seconds at the start that are not scored")
    args = ap.parse_args()
    config = ScoreConfig(gate_m=args.gate, warmup_s=args.warmup)
    if args.viewer:
        with open(args.viewer, encoding="utf-8") as f:
            window = (args.start or 0.0, args.end if args.end is not None else float("inf"))
            result = score_viewer_run(json.load(f), args.hostile_only, window, config)
    elif args.truth and args.tracks:
        result = score_from_files(args.truth, args.tracks, config)
    else:
        ap.error("give truth.json and tracks.jsonl, or --viewer run.json")
    for name, value in asdict(result).items():
        print(f"{name:26s} {'-' if value is None else round(value, 3)}")


if __name__ == "__main__":
    main()
