"""A small Kalman filter for the state [x, y, vx, vy] (constant velocity), in plain Python lists.

Measurements are scalars (a bearing, a range, a radial speed), each with its own residual, Jacobian row
and variance, applied one after another, so no matrix is ever inverted. Fine for a few dozen tracks.
"""

import math
from typing import List

Vec = List[float]
Mat = List[List[float]]
MIN_VARIANCE = 1e-6


def identity_like(diagonal: Vec) -> Mat:
    return [[diagonal[i] if i == j else 0.0 for j in range(len(diagonal))] for i in range(len(diagonal))]


def _transpose(m: Mat) -> Mat:
    return [list(row) for row in zip(*m)]


def _matmul(a: Mat, b: Mat) -> Mat:
    bt = _transpose(b)
    return [[sum(x * y for x, y in zip(row, col)) for col in bt] for row in a]


def predict(state: Vec, cov: Mat, dt: float, accel_noise: float):
    """Move the state `dt` seconds ahead; `accel_noise` is the 1-sigma random acceleration in m/s^2."""
    f = [[1, 0, dt, 0], [0, 1, 0, dt], [0, 0, 1, 0], [0, 0, 0, 1]]
    q = accel_noise ** 2
    d2, d3, d4 = dt ** 2, dt ** 3, dt ** 4
    process = [[q * d4 / 4, 0, q * d3 / 2, 0], [0, q * d4 / 4, 0, q * d3 / 2],
               [q * d3 / 2, 0, q * d2, 0], [0, q * d3 / 2, 0, q * d2]]
    new_cov = _matmul(_matmul(f, cov), _transpose(f))
    new_cov = [[new_cov[i][j] + process[i][j] for j in range(4)] for i in range(4)]
    return [state[0] + state[2] * dt, state[1] + state[3] * dt, state[2], state[3]], new_cov


def scalar_update(state: Vec, cov: Mat, residual: float, h: Vec, variance: float):
    """Apply one scalar measurement: `residual` = measured - predicted, `h` its Jacobian row."""
    ph = [sum(cov[i][j] * h[j] for j in range(4)) for i in range(4)]
    s = sum(h[i] * ph[i] for i in range(4)) + variance
    gain = [v / s for v in ph]
    new_state = [state[i] + gain[i] * residual for i in range(4)]
    new_cov = [[cov[i][j] - gain[i] * ph[j] for j in range(4)] for i in range(4)]
    return new_state, _symmetric(new_cov)


def innovation_variance(cov: Mat, h: Vec, variance: float) -> float:
    return sum(h[i] * cov[i][j] * h[j] for i in range(4) for j in range(4)) + variance


def _symmetric(m: Mat) -> Mat:
    out = [[(m[i][j] + m[j][i]) / 2 for j in range(4)] for i in range(4)]
    for i in range(4):
        out[i][i] = max(out[i][i], MIN_VARIANCE)
    return out


def wrap_pi(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))
