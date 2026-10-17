"""Covariance intersection: merge two estimates of one object whose errors may be correlated.

Two nodes that track the same target have usually seen some of the same things (the same beacons, the
same pose errors), so adding their information as if independent would make the merged track too sure.
Covariance intersection takes a weighted mix of the two information matrices,

    P^-1 = w P1^-1 + (1 - w) P2^-1,   x = P (w P1^-1 x1 + (1 - w) P2^-1 x2),

which is never over-confident whatever the correlation. `w` is picked to make the position block smallest.
"""

from typing import List, Sequence, Tuple

Vec = List[float]
Mat = List[List[float]]
WEIGHT_STEPS = 20


def inverse(m: Mat) -> Mat:
    """Gauss-Jordan inverse with partial pivoting (the matrices here are 4x4 and positive definite)."""
    n = len(m)
    a = [list(row) + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(m)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        a[col], a[pivot] = a[pivot], a[col]
        scale = a[col][col]
        a[col] = [v / scale for v in a[col]]
        for r in range(n):
            if r != col:
                factor = a[r][col]
                a[r] = [v - factor * p for v, p in zip(a[r], a[col])]
    return [row[n:] for row in a]


def _mix(w: float, info1: Mat, info2: Mat) -> Mat:
    return [[w * a + (1.0 - w) * b for a, b in zip(r1, r2)] for r1, r2 in zip(info1, info2)]


def _times(m: Mat, v: Vec) -> Vec:
    return [sum(a * b for a, b in zip(row, v)) for row in m]


def intersect(x1: Vec, p1: Mat, x2: Vec, p2: Mat) -> Tuple[Vec, Mat]:
    """The covariance-intersection merge of two estimates, weighted to the smallest position uncertainty."""
    info1, info2 = inverse(p1), inverse(p2)
    best = None
    for step in range(1, WEIGHT_STEPS):
        w = step / WEIGHT_STEPS
        p = inverse(_mix(w, info1, info2))
        size = p[0][0] + p[1][1]
        if best is None or size < best[0]:
            best = (size, w, p)
    _, w, p = best
    mixed = [w * a + (1.0 - w) * b for a, b in zip(_times(info1, x1), _times(info2, x2))]
    return _times(p, mixed), p


def intersect_all(estimates: Sequence[Tuple[Vec, Mat]]) -> Tuple[Vec, Mat]:
    x, p = estimates[0]
    for x2, p2 in estimates[1:]:
        x, p = intersect(x, p, x2, p2)
    return x, p
