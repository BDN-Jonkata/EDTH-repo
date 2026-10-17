"""Node clock estimation: each node stamps its messages with its own clock, which is off by an offset and drifts.

The tracker only knows when a message arrived and what the sender's clock said when it sent it. The arrival
minus the stamp is `delay - offset`, so the *smallest* of them, over the recent past, is the shortest delay minus
the offset. The shortest delay is the network's lower bound (known from the scenario, rounded up to the step
the tracker is run at) plus the sensor's own latency (known from the catalog), so the offset follows. Only the lower envelope is used because delays only
add: a burst of delay or a queue pushes the sample up, never down.

The envelope may creep up by `CREEP_PER_S` per second so a clock that drifts the other way is followed (a clock
that gains time pulls the samples down by itself). The reference is the C2 clock, the one the tracker steps by.
Assumed, not verified: the 100 ppm creep (the scenarios use 20 to 50 ppm) and that the shortest delay of the
run is reached now and then, which a delay burst longer than the run would break.
"""

import math
from typing import Callable, Dict, Iterable, List, Tuple

from common.channel import network_settings

CREEP_PER_S = 1e-4
CORRECTED = ("observation", "friendly_beacon")


class TimeSync:
    def __init__(self, floor_s: float = 0.0, creep_per_s: float = CREEP_PER_S):
        """`floor_s`: the shortest time a message takes on the network, from the scenario."""
        self.floor_s, self.creep = floor_s, creep_per_s
        self._low: Dict[str, Tuple[float, float]] = {}      # node -> (smallest delay - offset seen, when)

    def observe(self, node: str, t_sent: float, t_arrival: float, known_delay_s: float = 0.0) -> None:
        """Fold in one message: `known_delay_s` is the delay the node itself adds (a sensor's latency)."""
        sample = t_arrival - t_sent - known_delay_s
        low, seen = self._low.get(node, (sample, t_arrival))
        self._low[node] = (min(sample, low + self.creep * max(0.0, t_arrival - seen)), t_arrival)

    def offset(self, node: str) -> float:
        """The node clock's estimated offset from C2 (seconds, positive: it runs ahead); 0 for an unknown node."""
        low = self._low.get(node)
        return 0.0 if low is None else -(low[0] - self.floor_s)

    def apply(self, messages: Iterable[dict], t: float, known_delay: Callable[[dict], float]) -> List[dict]:
        """The delivered messages with their stamps put on the C2 clock; the originals are not changed."""
        messages = list(messages)
        for m in messages:
            if m["type"] in CORRECTED:
                self.observe(m["header"]["source_id"], m["header"]["t_sent"], t, known_delay(m))
        return [self._corrected(m) for m in messages]

    def _corrected(self, m: dict) -> dict:
        if m["type"] not in CORRECTED:
            return m
        off = self.offset(m["header"]["source_id"])
        out = dict(m, header=dict(m["header"], t_sent=m["header"]["t_sent"] - off))
        if "t_obs" in m:
            out["t_obs"] = m["t_obs"] - off
        return out


def known_delay_of(modules: Dict[str, dict]) -> Callable[[dict], float]:
    """The delay a sensor adds to its own readings (catalog `sim.latency_ms`); a beacon adds none."""
    def delay(m: dict) -> float:
        return modules[m["sensor_id"]]["sim"]["latency_ms"] / 1000.0 if m["type"] == "observation" else 0.0
    return delay


def clock_floor_s(scenario: dict, step_s: float) -> float:
    """The shortest time a message takes from being stamped to being delivered, in seconds: the network's shortest
    delay (0 when it is switched off), rounded up to the tracker's step, because messages are sent and handed over
    on that grid."""
    shortest = network_settings(scenario)[2][0] / 1000.0
    return math.ceil(shortest / step_s - 1e-9) * step_s
