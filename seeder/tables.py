"""Read the compact run format back: { "cols": [...], "rows": [[...]] } tables become lists of dicts.

    from tables import unpack
    result = unpack(run["result"])
"""
from __future__ import annotations


def unpack(v):
    if isinstance(v, dict):
        if set(v) == {"cols", "rows"}:
            return [dict(zip(v["cols"], unpack(row))) for row in v["rows"]]
        return {k: unpack(x) for k, x in v.items()}
    if isinstance(v, list):
        return [unpack(x) for x in v]
    return v
