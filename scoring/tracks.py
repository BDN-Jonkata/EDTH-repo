"""Turn track outputs into the frames `scoring.metrics.score` reads."""

from collections import defaultdict
from typing import Dict, Iterable, Iterator, List, Sequence, Tuple

from scoring.metrics import Estimate

Frames = Iterator[Tuple[float, List[Estimate]]]


def frames_from_local_tracks(messages: Iterable[dict], step_s: float = 0.5) -> Frames:
    """Group `local_track` messages into time steps of `step_s` by their `t_state`.

    Position and velocity come from `state` = [x, y, z, vx, vy, vz]; the class is the message's `class`, if any.
    """
    steps: Dict[int, List[Estimate]] = defaultdict(list)
    for m in messages:
        if m.get("type") != "local_track":
            continue
        x, y, _z, vx, vy, _vz = m["state"]
        steps[round(m["t_state"] / step_s)].append(
            Estimate(m["local_track_id"], m["t_state"], x, y, vx, vy, m.get("class")))
    for k in sorted(steps):
        yield k * step_s, steps[k]


def frames_from_estimator(frames: Iterable, classify) -> Frames:
    """Frames from `friend_foe` input frames `(t, tracks, beacons)`, calling `classify(t, tracks, beacons)`
    for the classifications. Lets the scoring run on what the estimator produced."""
    for t, tracks, beacons in frames:
        cls = {c.track_id: c.cls for c in classify(t, tracks, beacons)}
        yield t, [Estimate(tr.track_id, t, tr.position[0], tr.position[1], tr.velocity[0], tr.velocity[1],
                           cls.get(tr.track_id)) for tr in tracks]
