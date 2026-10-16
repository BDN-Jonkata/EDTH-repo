"""Generate a hand-made `local_tracks.jsonl` to develop the estimator against.

Scenario (2 Hz, 60 s, seeded):
  F1  friendly, beacon with 30% packet loss
  F2  friendly, beacon jammed completely after t = 20 s
  H1  unknown drone, never broadcasts
  A weak ghost track (low existence) that must be ignored

Run: python -m friend_foe.make_synthetic
"""

import json
import random
from pathlib import Path

OUT = Path(__file__).parent / "data" / "local_tracks.jsonl"
DT, DURATION, SEED = 0.5, 60.0, 7


def cov(sigma: float):
    v = sigma * sigma
    return [[v if i == j else 0.0 for j in range(6)] for i in range(6)]


def main() -> None:
    rng = random.Random(SEED)
    objects = {
        "F1": dict(p0=(0, 0, 40), v=(8, 2, 0)),
        "F2": dict(p0=(200, 300, 40), v=(-5, -3, 0)),
        "H1": dict(p0=(600, 500, 60), v=(-12, -9, 0)),
    }
    lines, seq = [], 0
    for k in range(int(DURATION / DT) + 1):
        t = k * DT
        for name, o in objects.items():
            pos = [p + v * t + rng.gauss(0, 1.5) for p, v in zip(o["p0"], o["v"])]
            seq += 1
            lines.append({
                "type": "local_track",
                "header": {"msg_id": f"n1-{seq}", "source_id": "node1", "t_sent": t, "seq": seq},
                "local_track_id": name,
                "t_state": t,
                "state": pos + list(o["v"]),
                "covariance": cov(2.0),
                "existence_prob": 0.95,
            })
            beacon_ok = (
                (name == "F1" and rng.random() > 0.3)
                or (name == "F2" and t <= 20.0)
            )
            if beacon_ok:
                seq += 1
                lines.append({
                    "type": "friendly_beacon",
                    "header": {"msg_id": f"{name}-{seq}", "source_id": name, "t_sent": t, "seq": seq},
                    "friend_id": name,
                    "position": [p + rng.gauss(0, 1.0) for p in pos],
                    "covariance": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                    "velocity": list(o["v"]),
                })
        seq += 1
        lines.append({
            "type": "local_track",
            "header": {"msg_id": f"n1-{seq}", "source_id": "node1", "t_sent": t, "seq": seq},
            "local_track_id": "ghost",
            "t_state": t,
            "state": [900, 900, 10, 0, 0, 0],
            "covariance": cov(30.0),
            "existence_prob": 0.1,
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for m in lines:
            f.write(json.dumps(m) + "\n")
    print(f"wrote {len(lines)} messages to {OUT}")


if __name__ == "__main__":
    main()
