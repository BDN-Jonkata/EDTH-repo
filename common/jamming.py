"""Jamming zones: circles on the map where, while active, messages sent by or to a node inside are lost more often
and RF receivers are noisier. A zone is `{x, y, radius_m, loss, t_start?, t_end?, rf_noise_mult?}` (docs/data-formats.md).

A port of `ui/viewer/jamming.js`, which is the reference; `common/testdata/channel_cases.json` holds cases both
implementations must answer the same. The sender's true position and the true time decide, not its drifted clock.
"""

import math
from typing import Iterable, List, Optional, Tuple

Position = Tuple[float, float]


def is_active(zone: dict, t: float) -> bool:
    return zone.get("t_start", 0) <= t < zone.get("t_end", math.inf)


def contains(zone: dict, pos: Position) -> bool:
    return math.hypot(pos[0] - zone["x"], pos[1] - zone["y"]) <= zone["radius_m"]


def active_zones(zones: Iterable[dict], t: float, pos: Optional[Position] = None) -> List[dict]:
    """The zones in force at time `t`, and holding `pos` when a position is given."""
    return [z for z in zones if is_active(z, t) and (pos is None or contains(z, pos))]


def loss_at(zones: Iterable[dict], base: float, pos: Position, t: float) -> float:
    """The higher of the base loss and the loss of every active zone that holds the node."""
    return max([base] + [z["loss"] for z in active_zones(zones, t, pos)])


def rf_noise_mult(zones: Iterable[dict], pos: Position, t: float) -> float:
    """How much noisier an RF receiver at `pos` is (1 = not at all). Not applied by `sensors/` yet."""
    return max([1.0] + [z.get("rf_noise_mult", 1.0) for z in active_zones(zones, t, pos)])
