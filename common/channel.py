"""The network between nodes: packet loss (independent or bursty), delay, and each node's local clock.

Driven by a scenario's `degradations` (`network`, `clock`), each only when its `enabled` is true. Used by
the test adapter in `friend_foe/` and by the pipeline in `tracker/`. Assumptions, since the scenario only
gives ranges: bursty loss is a two-state chain with a mean burst of `MEAN_BURST` messages and the
configured average loss; a node's clock offset is a random sign times a value in `offset_ms`, and its
drift a random sign times `drift_ppm`.

Also modelled, as in the viewer's mock simulation (`ui/viewer/sim.js` is the reference), each only when the
scenario asks for it, so a scenario without them behaves exactly as before:
  - jamming zones (`network.jamming_zones`, `common/jamming.py`): a message from a node inside an active zone is
    lost with the zone's rate when that is above the base loss. Inside a zone the loss is independent, also when the
    base loss is bursty. Needs `position_of(source, t)`, the sender's true position (None: not a node).
  - a link cap (`network.bandwidth_kbps`, `common/linkcap.py`): messages wait for their node's link, in order.
  - node dropout (`degradations.dropout[]` = `{node, t}`): the node sends nothing from then on.
  - sensor faults (`degradations.sensor_faults[]`, class `Faults`): `dropout` (same as the list above), `link_outage`
    (a node's messages are lost in a window) and `delay_burst` (they arrive `extra_ms` later). Applied whenever listed.
Not modelled here: topology. Store-and-forward is in `pipeline/storefwd.py` (it needs `send_to`, a message from C2 to a node).
"""

import heapq
import itertools
import random
from typing import Callable, Dict, List, Optional, Tuple

from common.jamming import loss_at
from common.linkcap import LinkCap

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


def node_clocks(scenario: dict, seed: int, friendly_clocks: Dict[str, "Clock"]) -> Dict[str, "Clock"]:
    """A clock for every node: the friendlies' (the ones their beacons use) and a new one per ground sensor."""
    rng = random.Random(seed)
    clocks = dict(friendly_clocks)
    for g in scenario["ground"]:
        clocks[g["id"]] = Clock(rng, scenario["degradations"]["clock"])
    return clocks


def network_settings(scenario: dict) -> Tuple[float, bool, Tuple[float, float]]:
    """(loss, bursty, (min, max) delay in ms) of the scenario's network, zero when it is switched off."""
    net = scenario["degradations"]["network"]
    if not net.get("enabled"):
        return 0.0, False, (0.0, 0.0)
    lo, hi = net.get("latency_ms", [0, 0])
    return net.get("loss", 0.0), bool(net.get("burst")), (lo, hi)


class Faults:
    """Injected data loss, `degradations.sensor_faults[]` = `{node, kind, t_start, t_end?, extra_ms?}`.

    A fault is for the messages a node *sends* (the pipeline sends nothing to nodes): `link_outage` drops them
    between `t_start` and `t_end`, `delay_burst` delays them by `extra_ms` in that window, `dropout` stops them for
    good from `t_start` (the channel treats it like the older `dropout[]`, see `dropouts`).
    """

    def __init__(self, scenario: dict):
        self.faults: Dict[str, List[dict]] = {}
        for f in scenario["degradations"].get("sensor_faults", []):
            self.faults.setdefault(f["node"], []).append(f)

    def dropouts(self) -> Dict[str, float]:
        """{node: time it stops sending} for the `dropout` faults."""
        return {n: min(f["t_start"] for f in fs if f["kind"] == "dropout")
                for n, fs in self.faults.items() if any(f["kind"] == "dropout" for f in fs)}

    def _active(self, node: str, t: float):
        for f in self.faults.get(node, []):
            if f["t_start"] <= t and ("t_end" not in f or t < f["t_end"]):
                yield f

    def cuts(self, node: str, t: float) -> bool:
        return any(f["kind"] == "link_outage" for f in self._active(node, t))

    def extra_delay_s(self, node: str, t: float) -> float:
        return sum(f["extra_ms"] for f in self._active(node, t) if f["kind"] == "delay_burst") / 1000.0


def extras(scenario: dict) -> Tuple[List[dict], Optional[float], Dict[str, float]]:
    """(jamming zones, link cap in kbit/s or None, {node: time it stops sending}) of the scenario's network."""
    degradations = scenario["degradations"]
    net = degradations["network"]
    on = bool(net.get("enabled"))
    dead = {d["node"]: d["t"] for d in degradations.get("dropout", [])}
    return (net.get("jamming_zones", []) if on else []), (net.get("bandwidth_kbps") if on else None), dead


class Channel:
    """Messages go in with `send`, come out of `deliver` after their delay, minus the lost ones.

    Each source has its own loss chain, so one node's burst does not drop another's messages.
    """

    def __init__(self, scenario: dict, seed: int = 0,
                 position_of: Optional[Callable[[str, float], Optional[Tuple[float, float]]]] = None):
        self.rng = random.Random(seed)
        self.loss, self.burst, self.delay_ms = network_settings(scenario)
        self.zones, kbps, self.dead_from = extras(scenario)
        self.faults = Faults(scenario)
        for node, t_dead in self.faults.dropouts().items():
            self.dead_from[node] = min(t_dead, self.dead_from.get(node, t_dead))
        self.position_of = position_of
        self.cap = LinkCap(kbps) if kbps else None
        self.links: Dict[str, Loss] = {}
        self._queue: List[Tuple[float, int, dict]] = []
        self._order = itertools.count()
        self.sent = self.lost = self.silent = 0

    def send(self, message: dict, t: float, extra_delay_s: float = 0.0) -> None:
        source = message["header"]["source_id"]
        if t >= self.dead_from.get(source, float("inf")):
            self.silent += 1   # a dead node sends nothing: not counted as sent or lost
            return
        if self.cap is not None:
            self.cap.enqueue(source, message, t, extra_delay_s)
        else:
            self._transmit(source, message, t, extra_delay_s)

    def alive(self, node: str, t: float) -> bool:
        return t < self.dead_from.get(node, float("inf"))

    def send_to(self, node: str, message: dict, t: float) -> None:
        """A message from C2 to `node` goes over that node's own link (its loss chain, jamming zone, outage and delay
        burst, as in the mock) and is not held back by the link cap. A dead node hears nothing."""
        if self.alive(node, t):
            self._transmit(node, message, t, 0.0)

    def _transmit(self, source: str, message: dict, t: float, extra_delay_s: float) -> None:
        link = self.links.setdefault(source, Loss(self.rng, self.loss, self.burst))
        self.sent += 1
        if self._drops(link, source, t) or self.faults.cuts(source, t):
            self.lost += 1
            return
        arrival = t + extra_delay_s + self.faults.extra_delay_s(source, t) + self.rng.uniform(*self.delay_ms) / 1000.0
        heapq.heappush(self._queue, (arrival, next(self._order), message))

    def _drops(self, link: Loss, source: str, t: float) -> bool:
        """The base loss chain, or the zone's rate when the sender is inside an active zone that jams harder."""
        pos = self.position_of(source, t) if self.zones and self.position_of else None
        zone_loss = loss_at(self.zones, self.loss, pos, t) if pos is not None else self.loss
        if zone_loss > self.loss:
            return self.rng.random() < zone_loss
        return link.drops()

    def deliver(self, t: float) -> List[dict]:
        """The messages that have arrived by `t`, in arrival order."""
        if self.cap is not None:   # a message leaves its link when its last byte does; lost ones used their airtime
            self.cap.drain(t, lambda m, finish: self._transmit(m.node, m.payload, finish, m.extra_delay_s))
        out = []
        while self._queue and self._queue[0][0] <= t + 1e-9:
            out.append(heapq.heappop(self._queue)[2])
        return out
