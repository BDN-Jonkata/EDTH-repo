"""Optimal one-to-one assignment (Hungarian algorithm), pure Python for a handful of objects."""

from typing import List, Sequence, Tuple

INF = float("inf")
GATED = 1e9   # cost of a pair that is not allowed; such pairs are dropped from the result


def assign(cost: Sequence[Sequence[float]], gate: float = INF) -> List[Tuple[int, int]]:
    """Pairs (row, col) with the lowest total cost; a pair costing more than `gate` is never made."""
    n_rows, n_cols = len(cost), len(cost[0]) if cost else 0
    n = max(n_rows, n_cols)
    square = [[_cell(cost, i, j, gate) for j in range(n)] for i in range(n)]
    row_of_col = _solve(square)
    pairs = [(row_of_col[j], j) for j in range(n_cols) if row_of_col[j] < n_rows]
    return [(i, j) for i, j in pairs if cost[i][j] <= gate]


def _cell(cost, i: int, j: int, gate: float) -> float:
    if i >= len(cost) or j >= len(cost[0]):
        return 0.0                                  # padding makes the matrix square
    return cost[i][j] if cost[i][j] <= gate else GATED


def _solve(a: List[List[float]]) -> List[int]:
    """Row assigned to each column of a square cost matrix (shortest augmenting paths with potentials)."""
    n = len(a)
    u, v, p = [0.0] * (n + 1), [0.0] * (n + 1), [0] * (n + 1)   # 1-based; p[j] = row holding column j
    for i in range(1, n + 1):
        _augment(i, a, u, v, p)
    return [p[j] - 1 for j in range(1, n + 1)]


def _augment(i: int, a, u, v, p) -> None:
    n = len(a)
    p[0], j0 = i, 0
    minv, used, way = [INF] * (n + 1), [False] * (n + 1), [0] * (n + 1)
    while True:
        used[j0] = True
        i0, delta, j1 = p[j0], INF, 0
        for j in range(1, n + 1):
            if used[j]:
                continue
            cur = a[i0 - 1][j - 1] - u[i0] - v[j]
            if cur < minv[j]:
                minv[j], way[j] = cur, j0
            if minv[j] < delta:
                delta, j1 = minv[j], j
        for j in range(n + 1):
            if used[j]:
                u[p[j]] += delta
                v[j] -= delta
            else:
                minv[j] -= delta
        j0 = j1
        if p[j0] == 0:
            break
    while j0:
        j1 = way[j0]
        p[j0] = p[j1]
        j0 = j1
