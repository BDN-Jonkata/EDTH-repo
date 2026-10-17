"""Store-and-forward: a node keeps what it sent until C2 says it arrived, and resends what C2 is missing.

A port of the node and receiver sides of `ui/viewer/storefwd.js`, which is the reference (rules and the assumed
numbers are in docs/data-formats.md, "Sensor faults and store-and-forward"); `common/testdata/storefwd_cases.json`
holds cases both must answer the same (`common/golden.py`). Link health is not ported: `health/` judges the links
in Python.

Node side: every message a node sends is kept until C2 acknowledges it (at most `buffer_s` seconds). After each ack
the node resends what C2 says is missing, oldest first, within a byte budget. C2 side: per node, which `seq`
numbers arrived; from that comes the ack (everything up to `upto`, plus the ranges still missing). A node reports
the oldest `seq` it still holds, so C2 stops asking for anything older and lost messages that expired do not block
the ack.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

ACK_EVERY_S = 1.0       # ASSUMED: how often C2 broadcasts its ack
OFFLINE_ACKS = 3        # ASSUMED: acks a node may miss before it counts itself offline
BUFFER_S = 60.0         # ASSUMED: seconds of unacknowledged messages a node keeps
RESEND_SHARE = 0.5      # ASSUMED: share of a capped link that resends may use
RESEND_AGAIN_S = 2.0    # a message resent this recently is not resent again yet
RESEND_MIN_AGE_S = 1.0  # younger messages may still be on their way: not resent yet
LATE_S = 3.0            # older than this on arrival: history, not a live reading
MAX_RANGES = 32         # missing ranges one ack entry lists


@dataclass
class Held:
    seq: int
    t: float
    payload: dict
    resent_at: float = float("-inf")


@dataclass
class Node:
    buffer_s: float = BUFFER_S
    store: List[Held] = field(default_factory=list)
    last_ack: float = 0.0
    stats: Dict[str, int] = field(default_factory=lambda: {"stored": 0, "expired": 0, "resent": 0})


def remember(node: Node, payload: dict, t: float) -> None:
    """Keep a copy of what was sent, without the channel's arrival time."""
    copy = {k: v for k, v in payload.items() if k != "arr"}
    node.store.append(Held(payload["header"]["seq"], t, copy))
    node.stats["stored"] += 1
    while node.store and node.store[0].t < t - node.buffer_s:
        node.store.pop(0)
        node.stats["expired"] += 1


def _is_missing(entry: dict, seq: int) -> bool:
    return any(a <= seq <= b for a, b in entry["missing"])


def on_ack(node: Node, entry: dict, t: float, budget: float, size_of: Callable[[dict], int]) -> List[dict]:
    """Drop what C2 has; return what it is missing, oldest first, within `budget` bytes (infinity: no cap)."""
    node.last_ack = t
    node.store = [m for m in node.store if m.seq > entry["max"] or _is_missing(entry, m.seq)]
    out, left = [], budget
    for m in node.store:
        if m.seq > entry["max"] or t - m.t < RESEND_MIN_AGE_S or t - m.resent_at < RESEND_AGAIN_S:
            continue
        size = size_of(m.payload)
        if size > left:
            break
        left -= size
        m.resent_at = t
        node.stats["resent"] += 1
        out.append(dict(m.payload))
    return out


def is_offline(node: Node, t: float) -> bool:
    return t - node.last_ack > OFFLINE_ACKS * ACK_EVERY_S + 1e-9


def status(node: Node, t: float) -> dict:
    """What a node tells C2 about itself: whether it hears acks, how much it holds, and the oldest `seq` it holds."""
    buffered = t - node.store[0].t if node.store else 0.0
    return {"offline": is_offline(node, t), "buffered_s": round(buffered * 10) / 10,
            "oldest_seq": node.store[0].seq if node.store else None}


@dataclass
class Receiver:
    upto: int = 0
    max: int = 0
    got: Set[int] = field(default_factory=set)
    floor: int = 0


def receive(r: Receiver, seq: int) -> bool:
    """False when this `seq` already arrived (the original got through and so did a resend)."""
    if seq <= r.upto or seq in r.got:
        return False
    r.got.add(seq)
    r.max = max(r.max, seq)
    _advance(r)
    return True


def skip_below(r: Receiver, oldest: Optional[int]) -> None:
    """The node no longer holds anything older than `oldest`: stop waiting for it."""
    if oldest is None or oldest - 1 <= r.upto:
        return
    r.floor = max(r.floor, oldest - 1)
    _advance(r)


def _advance(r: Receiver) -> None:
    if r.floor > r.upto:
        r.got = {s for s in r.got if s > r.floor}
        r.upto = r.floor
    while r.upto + 1 in r.got:
        r.got.discard(r.upto + 1)
        r.upto += 1


def ack_entry(r: Receiver) -> dict:
    """`{upto, max, missing: [[from, to], ...]}` for one node."""
    missing: List[Tuple[int, int]] = []
    start = None
    s = r.upto + 1
    while s <= r.max and len(missing) < MAX_RANGES:
        if s not in r.got:
            start = s if start is None else start
        elif start is not None:
            missing.append((start, s - 1))
            start = None
        s += 1
    if start is not None and len(missing) < MAX_RANGES:
        missing.append((start, r.max))
    return {"upto": r.upto, "max": r.max, "missing": [list(m) for m in missing]}
