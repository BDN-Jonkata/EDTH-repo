"""How well the friendly drones are placed to identify the hostiles (reads `truth.json` through `truth.py`).

The pipeline does not identify anything itself: the observations carry no class cues, so a faster or better
identification cannot show in the tracking metrics. This measures the thing a hand-off is for instead: at each
step, is some friendly drone within the identification range of its best module of a hostile (the catalog's
`sim.ident_range_m`, assumed, clear weather)?

    covered   share of hostile-present steps with at least one drone in identification range
    delay     per hostile, the time from first present (after the warmup) to the first step it is covered,
              averaged over the hostiles; a hostile never covered counts as its whole time present
"""

from typing import Dict, Tuple

from scoring.truth import load_truth, present_at

STEP_S = 0.5


def identification(truth: dict, ranges: Dict[str, float], warmup_s: float = 0.0) -> Tuple[float, float]:
    """(covered share, mean delay in seconds). `ranges` maps a friendly drone's id to its identification range."""
    objects = load_truth(truth)
    drones = {i: o for i, o in objects.items() if i in ranges}
    hostiles = [o for o in objects.values() if o.kind == "hostile"]
    steps = covered = 0
    delays = []
    for hostile in hostiles:
        first = first_covered = last = None
        for k in range(int((hostile.times[-1] - hostile.times[0]) / STEP_S) + 1):
            t = hostile.times[0] + k * STEP_S
            state = hostile.state_at(t)
            if t < warmup_s or state is None:
                continue
            first = t if first is None else first
            last = t
            steps += 1
            if _drone_within_range(drones, ranges, t, state):
                covered += 1
                first_covered = t if first_covered is None else first_covered
        if first is not None:
            delays.append((first_covered if first_covered is not None else last) - first)
    return (covered / steps if steps else 0.0), (sum(delays) / len(delays) if delays else 0.0)


def _drone_within_range(drones, ranges, t, state) -> bool:
    for drone_id, drone in drones.items():
        s = drone.state_at(t)
        if s is not None and (s[0] - state[0]) ** 2 + (s[1] - state[1]) ** 2 <= ranges[drone_id] ** 2:
            return True
    return False
