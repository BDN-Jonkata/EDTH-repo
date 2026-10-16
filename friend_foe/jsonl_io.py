"""Read JSON Lines files of `local_track` and `friendly_beacon` messages.

Stand-in for the `common/` codec until the shared schemas exist. Messages are
grouped into frames by timestamp so the estimator can be driven step by step.
"""

import json
from collections import defaultdict
from pathlib import Path
from typing import Iterator, List, Tuple

from friend_foe.estimator import Beacon, TrackState


def _sigma(cov) -> float:
    """Isotropic 1-sigma position uncertainty from the position block of a covariance."""
    n = min(3, len(cov))
    return (sum(cov[i][i] for i in range(n)) / n) ** 0.5


def track_from_message(m: dict) -> TrackState:
    x, y, z, vx, vy, vz = m["state"]
    return TrackState(
        track_id=m["local_track_id"],
        t=m["t_state"],
        position=(x, y, z),
        velocity=(vx, vy, vz),
        pos_sigma=_sigma(m["covariance"]),
        existence_prob=m.get("existence_prob", 1.0),
    )


def beacon_from_message(m: dict) -> Beacon:
    return Beacon(
        friend_id=m["friend_id"],
        t=m["header"]["t_sent"],
        position=tuple(m["position"]),
        velocity=tuple(m.get("velocity") or (0.0, 0.0, 0.0)),
        pos_sigma=_sigma(m["covariance"]),
    )


def read_frames(path) -> Iterator[Tuple[float, List[TrackState], List[Beacon]]]:
    """Yield (t, tracks, beacons) in time order, one frame per distinct timestamp."""
    tracks, beacons = defaultdict(list), defaultdict(list)
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = json.loads(line)
            if m["type"] == "local_track":
                tr = track_from_message(m)
                tracks[tr.t].append(tr)
            elif m["type"] == "friendly_beacon":
                b = beacon_from_message(m)
                beacons[b.t].append(b)
    for t in sorted(set(tracks) | set(beacons)):
        yield t, tracks.get(t, []), beacons.get(t, [])
