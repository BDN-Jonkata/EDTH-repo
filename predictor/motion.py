"""A learned motion model: how far a track's real position strays from a straight-line extrapolation, and how much
its velocity changes, as a function of the time horizon.

It is learned from the tracker's own output (the positions and velocities of confirmed tracks that were really
being updated), never from `truth.json`, and used by the identity keeper to size its gate and its velocity test
instead of the guessed acceleration noise. The numbers describe the simulated hostiles and the tracker's noise
as they are in the training runs, so they are only as good as those scenarios (`predictor/train.py`).
"""

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

HORIZONS_S = (1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0, 30.0)   # samples are one second apart, so these are whole steps
SPEED_QUANTILE = 0.95
MODEL_PATH = Path(__file__).with_name("motion_model.json")

Sample = Tuple[float, float, float, float, float]          # t, x, y, vx, vy


@dataclass
class MotionModel:
    horizons_s: List[float]
    spread_m: List[float]            # rms distance from the straight-line extrapolation
    speed_change_mps: List[float]    # 95th percentile of the velocity change

    def spread(self, dt: float) -> float:
        return _at(self.horizons_s, self.spread_m, dt)

    def speed_change(self, dt: float) -> float:
        return _at(self.horizons_s, self.speed_change_mps, dt)

    def save(self, path: Path = MODEL_PATH) -> None:
        path.write_text(json.dumps(self.__dict__, indent=1), encoding="utf-8")

    @staticmethod
    def load(path: Path = MODEL_PATH) -> "MotionModel":
        return MotionModel(**json.loads(path.read_text(encoding="utf-8")))


def _at(xs: Sequence[float], ys: Sequence[float], x: float) -> float:
    """Linear between the learned horizons; before the first it shrinks towards zero, after the last it keeps growing at the same rate."""
    if x <= xs[0]:
        return ys[0] * max(x, 0.0) / xs[0]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            return ys[i - 1] + (ys[i] - ys[i - 1]) * (x - xs[i - 1]) / (xs[i] - xs[i - 1])
    return ys[-1] * x / xs[-1]


def fit(histories: Dict[str, List[Sample]], horizons_s: Sequence[float] = HORIZONS_S) -> MotionModel:
    """Pool every pair of samples of one track that lies a horizon apart (histories: one sample a second)."""
    spreads: List[List[float]] = [[] for _ in horizons_s]
    changes: List[List[float]] = [[] for _ in horizons_s]
    for samples in histories.values():
        by_second = {round(s[0]): s for s in samples}
        for second, a in by_second.items():
            for k, h in enumerate(horizons_s):
                b = by_second.get(second + round(h))
                if b is not None:
                    spreads[k].append(math.hypot(b[1] - (a[1] + a[3] * h), b[2] - (a[2] + a[4] * h)))
                    changes[k].append(math.hypot(b[3] - a[3], b[4] - a[4]))
    return MotionModel(list(horizons_s), [_rms(v) for v in spreads], [_quantile(v, SPEED_QUANTILE) for v in changes])


def _rms(values: List[float]) -> float:
    return math.sqrt(sum(v * v for v in values) / len(values)) if values else 0.0


def _quantile(values: List[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))] if ordered else 0.0
