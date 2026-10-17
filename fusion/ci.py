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
SINGULAR_FLOOR = 1e-6


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


def _position_size(info: Mat) -> float:
    """The trace of the position block of `inverse(info)` without inverting all of it: that block is the inverse
    of the Schur complement A - B D^-1 B^T, a 2x2. Only the weight search needs it, 19 times per merge."""
    a, b, c, d = info[0][0], info[0][1], info[1][0], info[1][1]          # A, the position block
    p, q, r, s = info[0][2], info[0][3], info[1][2], info[1][3]          # B, position against velocity
    e, f, g, h = info[2][2], info[2][3], info[3][2], info[3][3]          # D, the velocity block
    det = e * h - f * g
    t00, t01 = (p * h - q * g) / det, (q * e - p * f) / det              # B D^-1
    t10, t11 = (r * h - s * g) / det, (s * e - r * f) / det
    s00, s01 = a - (t00 * p + t01 * q), b - (t00 * r + t01 * s)          # A - B D^-1 B^T
    s10, s11 = c - (t10 * p + t11 * q), d - (t10 * r + t11 * s)
    return (s00 + s11) / (s00 * s11 - s01 * s10)


def _safe_inverse(m: Mat) -> Mat:
    """`inverse`, and when the matrix is singular (a covariance with no spread in some direction) the same with a
    tiny floor on the diagonal, so one bad estimate cannot stop a merge."""
    try:
        return inverse(m)
    except ZeroDivisionError:
        return inverse([[v + (SINGULAR_FLOOR if i == j else 0.0) for j, v in enumerate(row)] for i, row in enumerate(m)])


def intersect(x1: Vec, p1: Mat, x2: Vec, p2: Mat) -> Tuple[Vec, Mat]:
    """The covariance-intersection merge of two estimates, weighted to the smallest position uncertainty."""
    info1, info2 = _safe_inverse(p1), _safe_inverse(p2)

    def size_at(step: int) -> float:
        return _position_size(_mix(step / WEIGHT_STEPS, info1, info2))

    lo, hi = 1, WEIGHT_STEPS - 1      # the size is convex in the weight (the inverse is convex), so bisect on its slope
    while lo < hi:
        mid = (lo + hi) // 2
        if size_at(mid) <= size_at(mid + 1):
            hi = mid
        else:
            lo = mid + 1
    w = lo / WEIGHT_STEPS
    p = inverse(_mix(w, info1, info2))
    mixed = [w * a + (1.0 - w) * b for a, b in zip(_times(info1, x1), _times(info2, x2))]
    return _times(p, mixed), p


def intersect_all(estimates: Sequence[Tuple[Vec, Mat]]) -> Tuple[Vec, Mat]:
    x, p = estimates[0]
    for x2, p2 in estimates[1:]:
        x, p = intersect(x, p, x2, p2)
    return x, p
