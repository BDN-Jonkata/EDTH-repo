"""Read the compact run format back: { "cols": [...], "rows": [[...]] } tables become lists of dicts.

    from tables import unpack
    result = unpack(run["result"])
"""
from __future__ import annotations


def pack_rows(rows):
    """The compact form of a list of same-shaped dicts: { "cols": [...], "rows": [[...]] }, so the keys are written once.
    A list of fewer than two dicts, or with differing keys, stays as it is; `unpack` reads both."""
    if len(rows) > 1 and all(isinstance(r, dict) for r in rows):
        cols = list(rows[0])
        if all(list(r) == cols for r in rows):
            return {"cols": cols, "rows": [[r[c] for c in cols] for r in rows]}
    return rows


def unpack(v):
    if isinstance(v, dict):
        if set(v) == {"cols", "rows"}:
            return [dict(zip(v["cols"], unpack(row))) for row in v["rows"]]
        return {k: unpack(x) for k, x in v.items()}
    if isinstance(v, list):
        return [unpack(x) for x in v]
    return v
