"""Read `truth.json` (`edth.truth/2`). Only the scoring module may do this."""

from bisect import bisect_left
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

State = Tuple[float, float, float, float]   # x, y, vx, vy


@dataclass(frozen=True)
class TruthObject:
    id: str
    kind: str                     # hostile | friendly | benign | clutter
    times: Tuple[float, ...]
    rows: Tuple[Tuple[float, ...], ...]   # (t, x, y, vx, vy) per sample, in time order

    def state_at(self, t: float, tolerance_s: float = 0.25) -> Optional[State]:
        """Position and velocity at `t`, linearly interpolated; None while the object is not in the area."""
        if not self.times or t < self.times[0] - tolerance_s or t > self.times[-1] + tolerance_s:
            return None
        if len(self.times) == 1:
            return self.rows[0][1:]
        k = min(max(bisect_left(self.times, t), 1), len(self.times) - 1)
        (t0, *s0), (t1, *s1) = self.rows[k - 1], self.rows[k]
        w = min(max((t - t0) / (t1 - t0), 0.0), 1.0)
        return tuple(a + w * (b - a) for a, b in zip(s0, s1))


def load_truth(truth: dict) -> Dict[str, TruthObject]:
    objects = {}
    for o in truth["objects"]:
        rows = tuple(tuple(r) for r in o["samples"])
        objects[o["id"]] = TruthObject(o["id"], o["kind"], tuple(r[0] for r in rows), rows)
    return objects


def present_at(objects: Dict[str, TruthObject], t: float) -> List[Tuple[TruthObject, State]]:
    out = []
    for obj in objects.values():
        state = obj.state_at(t)
        if state is not None:
            out.append((obj, state))
    return out
