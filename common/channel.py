"""The network between nodes: packet loss (independent or bursty), delay, and each node's local clock.

Driven by a scenario's `degradations` (`network`, `clock`), each only when its `enabled` is true. Used by
the test adapter in `friend_foe/` and by the pipeline in `tracker/`. Assumptions, since the scenario only
gives ranges: bursty loss is a two-state chain with a mean burst of `MEAN_BURST` messages and the
configured average loss; a node's clock offset is a random sign times a value in `offset_ms`, and its
drift a random sign times `drift_ppm`. Not modelled: jamming zones, node dropout, topology.
"""

import heapq
import itertools
import random
from typing import Dict, List, Tuple

MEAN_BURST = 5.0   # assumed mean length of a loss burst, in messages


class Loss:
    """Packet loss with the configured average, independent or bursty (two-state chain)."""

    def __init__(self, rng: random.Random, loss: float, burst: bool):
        self.rng, self.loss, self.burst, self.bad = rng, loss, burst, False
        self.p_bad_to_good = 1.0 / MEAN_BURST
        self.p_good_to_bad = loss * self.p_bad_to_good / (1 - loss) if 0 < loss < 1 else 0.0
        if self.p_good_to_bad > 1.0:   # very high loss: lengthen the bursts instead
            self.p_good_to_bad, self.p_bad_to_good = 1.0, (1 - loss) / loss

    def drops(self) -> bool:
        if not self.burst:
            return self.rng.random() < self.loss
        flip = self.p_bad_to_good if self.bad else self.p_good_to_bad
        if self.rng.random() < flip:
            self.bad = not self.bad
        return self.bad


class Clock:
    """A node's local clock: random offset and drift, as the scenario's ranges allow."""

    def __init__(self, rng: random.Random, clock: dict):
        on = clock.get("enabled", False)
        lo, hi = clock.get("offset_ms", [0, 0]) if on else (0, 0)
        self.offset_s = rng.choice((-1, 1)) * rng.uniform(lo, hi) / 1000.0
        self.drift = rng.choice((-1, 1)) * clock.get("drift_ppm", 0) * 1e-6 if on else 0.0

    def local(self, t: float) -> float:
        return t * (1.0 + self.drift) + self.offset_s


def network_settings(scenario: dict) -> Tuple[float, bool, Tuple[float, float]]:
    """(loss, bursty, (min, max) delay in ms) of the scenario's network, zero when it is switched off."""
    net = scenario["degradations"]["network"]
    if not net.get("enabled"):
        return 0.0, False, (0.0, 0.0)
    lo, hi = net.get("latency_ms", [0, 0])
    return net.get("loss", 0.0), bool(net.get("burst")), (lo, hi)


class Channel:
    """Messages go in with `send`, come out of `deliver` after their delay, minus the lost ones.

    Each source has its own loss chain, so one node's burst does not drop another's messages.
    """

    def __init__(self, scenario: dict, seed: int = 0):
        self.rng = random.Random(seed)
        self.loss, self.burst, self.delay_ms = network_settings(scenario)
        self.links: Dict[str, Loss] = {}
        self._queue: List[Tuple[float, int, dict]] = []
        self._order = itertools.count()
        self.sent = self.lost = 0

    def send(self, message: dict, t: float, extra_delay_s: float = 0.0) -> None:
        source = message["header"]["source_id"]
        link = self.links.setdefault(source, Loss(self.rng, self.loss, self.burst))
        self.sent += 1
        if link.drops():
            self.lost += 1
            return
        arrival = t + extra_delay_s + self.rng.uniform(*self.delay_ms) / 1000.0
        heapq.heappush(self._queue, (arrival, next(self._order), message))

    def deliver(self, t: float) -> List[dict]:
        """The messages that have arrived by `t`, in arrival order."""
        out = []
        while self._queue and self._queue[0][0] <= t + 1e-9:
            out.append(heapq.heappop(self._queue)[2])
        return out
