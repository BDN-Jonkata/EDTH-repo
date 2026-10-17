"""Score a run from files.

    python -m scoring.run out/<id>/truth.json tracks.jsonl [--gate 50] [--warmup 10]

`tracks.jsonl` holds `local_track` messages (one JSON object per line, see docs/data-formats.md).
"""

import argparse
import json
from dataclasses import asdict

from common.codec import decode
from scoring.metrics import ScoreConfig, score
from scoring.tracks import frames_from_local_tracks


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("truth")
    ap.add_argument("tracks")
    ap.add_argument("--gate", type=float, default=ScoreConfig.gate_m, help="metres within which a track is on an object")
    ap.add_argument("--warmup", type=float, default=0.0, help="seconds at the start that are not scored")
    args = ap.parse_args()
    with open(args.truth, encoding="utf-8") as f:
        truth = json.load(f)
    with open(args.tracks, encoding="utf-8") as f:
        messages = [decode(line) for line in f if line.strip()]
    result = score(truth, frames_from_local_tracks(messages), ScoreConfig(gate_m=args.gate, warmup_s=args.warmup))
    for name, value in asdict(result).items():
        print(f"{name:26s} {'-' if value is None else round(value, 3)}")


if __name__ == "__main__":
    main()
