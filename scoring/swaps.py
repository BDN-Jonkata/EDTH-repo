"""What the ID swaps of a run are: a cause for each event of `scoring.metrics.swap_log`.

A swap is counted when a hostile object, matched to track A at its last matched step, is now matched to track B.
The log records, at that step, whether A is still alive, what A is on now, whether B was seen before, and how
far the nearest other hostile is. Causes:

    restart    A is gone and B is new: the track was dropped (or never recovered) and a new one began later
    pickup     A is gone and B already existed: a track that was on something else (a ghost) took the hostile
    crossing   A is alive and on another hostile: two hostiles traded tracks
    other      A is alive and on a friendly, a bird or a car: the hostile took a track away from it
    ghost      A is alive but on nothing: the hostile jumped to another track and left a ghost behind
"""

from collections import Counter
from typing import Dict, Iterable, List

CAUSES = ("restart", "pickup", "crossing", "other", "ghost")
CLOSE_M = 60.0      # another hostile this close at the swap makes it a close-crossing swap


def cause(event: dict) -> str:
    if not event["old_alive"]:
        return "pickup" if event["new_seen_before"] else "restart"
    if event["old_on"] == "hostile":
        return "crossing"
    return "ghost" if event["old_on"] is None else "other"


def near_crossing(event: dict) -> bool:
    distance = event["nearest_other_hostile_m"]
    return distance is not None and distance <= CLOSE_M


def summarise(events: Iterable[dict]) -> Dict[str, int]:
    """Counts per cause, plus `near_other_hostile` (swaps with another hostile within `CLOSE_M`) and `total`."""
    events = list(events)
    counts = Counter(cause(e) for e in events)
    out = {c: counts.get(c, 0) for c in CAUSES}
    out["near_other_hostile"] = sum(near_crossing(e) for e in events)
    out["total"] = len(events)
    return out


def describe(events: List[dict]) -> str:
    s = summarise(events)
    return ", ".join(f"{c} {s[c]}" for c in CAUSES) + f" (total {s['total']}, {s['near_other_hostile']} with another hostile within {CLOSE_M:.0f} m)"
