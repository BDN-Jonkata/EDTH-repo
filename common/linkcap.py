"""Link capacity: each node has one link to C2 that carries `kbps`. A message occupies the link for bytes / rate
seconds, so what a link delivers in any window can never exceed the cap. Messages wait in order; when more than
`QUEUE_S` seconds of data are waiting, the oldest are dropped.

A port of `ui/viewer/linkcap.js`, which is the reference (rules and the assumed numbers are in
docs/data-formats.md, "Bandwidth limits"); `common/testdata/channel_cases.json` holds cases both must answer
the same. Sizes are the JSON length without the mock-only `z` and `arr`, unrounded, with compact separators like
JavaScript's `JSON.stringify`.
"""

import json
from dataclasses import dataclass, field
from typing import Callable, Dict, List

QUEUE_S = 2.0   # ASSUMED: seconds of backlog a node keeps before dropping its oldest messages


def size_of(payload: dict) -> int:
    sent = {k: v for k, v in payload.items() if k not in ("z", "arr")}
    return len(json.dumps(sent, separators=(",", ":"), ensure_ascii=False))


@dataclass
class Waiting:
    node: str
    payload: dict
    t: float
    extra_delay_s: float
    bytes: int
    type: str


@dataclass
class Link:
    busy_until: float = 0.0
    waiting: List[Waiting] = field(default_factory=list)
    waiting_bytes: int = 0


class LinkCap:
    def __init__(self, kbps: float):
        self.bytes_per_s = kbps * 125
        self.links: Dict[str, Link] = {}
        self.stats: Dict[str, dict] = {}

    def _stat(self, type_: str) -> dict:
        return self.stats.setdefault(type_, {"count": 0, "bytes": 0, "dropped": 0})

    def enqueue(self, node: str, payload: dict, t: float, extra_delay_s: float = 0.0) -> None:
        """Put a message on the sender's link; the oldest waiting messages are dropped when the backlog is too long."""
        link = self.links.setdefault(node, Link())
        msg = Waiting(node, payload, t, extra_delay_s, size_of(payload), payload["type"])
        stat = self._stat(msg.type)
        stat["count"] += 1
        stat["bytes"] += msg.bytes
        link.waiting.append(msg)
        link.waiting_bytes += msg.bytes
        while link.waiting_bytes > QUEUE_S * self.bytes_per_s and len(link.waiting) > 1:
            old = link.waiting.pop(0)
            link.waiting_bytes -= old.bytes
            self._stat(old.type)["dropped"] += 1

    def drain(self, t: float, send: Callable[[Waiting, float], None]) -> None:
        """Send every message the links can start by time `t`; `send(msg, finish)` gets the moment its last byte leaves."""
        for link in self.links.values():
            while link.waiting and link.busy_until <= t:
                msg = link.waiting.pop(0)
                link.waiting_bytes -= msg.bytes
                link.busy_until = max(link.busy_until, msg.t) + msg.bytes / self.bytes_per_s
                send(msg, link.busy_until)

    def summary(self) -> Dict[str, dict]:
        """Per message type: how many were offered, their bytes, the average size, how many were dropped."""
        return {k: {"count": s["count"], "bytes": s["bytes"], "avg_bytes": s["bytes"] / s["count"], "dropped": s["dropped"]}
                for k, s in self.stats.items()}
