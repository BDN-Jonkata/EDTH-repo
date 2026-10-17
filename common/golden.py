"""Shared test cases for the jamming zones, link caps and store-and-forward, so the viewer's JavaScript copy can be checked.

The reference for the rules is `ui/viewer/jamming.js`, `ui/viewer/linkcap.js` and `ui/viewer/storefwd.js` (the mock simulation); the Python
ports in `jamming.py`, `linkcap.py` and `storefwd.py` and the JavaScript both have to give the answers in
`testdata/channel_cases.json`. The file is generated from the Python ports, so the test that compares it with the
JavaScript is what proves the two agree. Do not edit it by hand:

    python -m common.golden              # rewrite the file
    python -m pytest common/test_golden.py   # fails if the file no longer matches the code

Compare floats with a tolerance (relative 1e-9); the cases are plain data.
"""

import json
from pathlib import Path
from typing import List

from common.jamming import loss_at, rf_noise_mult
from common.linkcap import LinkCap, size_of
from common.storefwd import Node, Receiver, ack_entry, on_ack, receive, remember, skip_below, status

PATH = Path(__file__).parent / "testdata" / "channel_cases.json"

ZONES = [
    {"x": 700, "y": 700, "radius_m": 280, "loss": 0.9, "t_start": 30, "t_end": 100, "rf_noise_mult": 3},
    {"x": 200, "y": 300, "radius_m": 150, "loss": 0.6},
    {"x": 250, "y": 300, "radius_m": 100, "loss": 0.8, "t_start": 10, "t_end": 20, "rf_noise_mult": 2},
]
POSITIONS = [(700, 700), (500, 500), (980, 700), (200, 300), (260, 330), (351, 300), (0, 0)]
TIMES = [0, 9.99, 10, 19.99, 20, 29.99, 30, 99.99, 100, 500]


def jamming_cases() -> List[dict]:
    cases = []
    for pos in POSITIONS:
        for t in TIMES:
            cases.append({"zones": ZONES, "base": 0.1, "pos": list(pos), "t": t,
                          "loss": loss_at(ZONES, 0.1, pos, t), "rf_noise_mult": rf_noise_mult(ZONES, pos, t)})
    return cases


def message(kind: str, seq: int, pad: int) -> dict:
    return {"type": kind, "header": {"seq": seq, "source_id": "F1"}, "pad": "x" * pad, "z": {"mock": "only"}, "arr": 1}


def run_link(kbps: float, offers: List[dict], drain_times: List[float]) -> dict:
    """Offer messages `{node, t, type, pad}` to the links, drain at each time; what left, when, and the totals."""
    cap, sent = LinkCap(kbps), []
    for i, o in enumerate(offers):
        cap.enqueue(o["node"], message(o["type"], i, o["pad"]), o["t"])
    for t in drain_times:
        cap.drain(t, lambda m, finish: sent.append({"seq": m.payload["header"]["seq"], "finish": finish}))
    return {"sent": sent, "stats": cap.summary()}


def linkcap_cases() -> List[dict]:
    steady = [{"node": "F1", "t": 0.1 * i, "type": "observation", "pad": 250} for i in range(40)]
    two_nodes = [{"node": n, "t": 0.0, "type": ty, "pad": p} for n, ty, p in
                 (("F1", "observation", 800), ("F2", "friendly_beacon", 100), ("F1", "observation", 100), ("F2", "observation", 300))]
    burst = [{"node": "F1", "t": 0.0, "type": "observation", "pad": 100} for _ in range(40)]
    drain = [round(0.1 * k, 1) for k in range(0, 601)]
    cases = []
    for name, kbps, offers in (("steady under the cap", 64, steady), ("steady over the cap", 8, steady),
                               ("two nodes", 8, two_nodes), ("burst drops the oldest", 8, burst)):
        cases.append({"name": name, "kbps": kbps, "offers": offers, "drain_times": drain, **run_link(kbps, offers, drain)})
    return cases


RECEIVER_RUNS = (
    ("in order", [("receive", 1), ("receive", 2), ("receive", 3)]),
    ("a gap and a duplicate", [("receive", 1), ("receive", 2), ("receive", 4), ("receive", 5), ("receive", 8), ("receive", 4)]),
    ("the node gave up on its oldest", [("receive", 1), ("receive", 5), ("receive", 6), ("skip", 4), ("receive", 3)]),
    ("a skip past everything seen", [("receive", 2), ("receive", 9), ("skip", 20)]),
    ("more gaps than one ack lists", [("receive", s) for s in range(2, 200, 2)]),
)


def receiver_cases() -> List[dict]:
    cases = []
    for name, steps in RECEIVER_RUNS:
        r, accepted = Receiver(), []
        for op, value in steps:
            if op == "receive":
                accepted.append(receive(r, value))
            else:
                skip_below(r, value)
        cases.append({"name": name, "steps": [list(x) for x in steps], "accepted": accepted, "ack": ack_entry(r)})
    return cases


def node_cases() -> List[dict]:
    sends = [{"seq": i + 1, "t": 0.5 * i, "pad": 100 + 20 * (i % 3)} for i in range(12)]
    acks = [{"t": 6.0, "entry": {"upto": 3, "max": 9, "missing": [[4, 5], [8, 8]]}, "budget": None},
            {"t": 6.5, "entry": {"upto": 3, "max": 9, "missing": [[4, 5], [8, 8]]}, "budget": None},
            {"t": 8.5, "entry": {"upto": 3, "max": 9, "missing": [[4, 5], [8, 8]]}, "budget": 330},
            {"t": 9.0, "entry": {"upto": 12, "max": 12, "missing": []}, "budget": None}]
    cases = []
    for name, buffer_s in (("unbounded buffer", 60.0), ("a short buffer expires the oldest", 3.0)):
        node = Node(buffer_s=buffer_s)
        for m in sends:
            remember(node, {"type": "observation", "header": {"seq": m["seq"]}, "pad": "x" * m["pad"], "arr": 1}, m["t"])
        results = []
        for a in acks:
            out = on_ack(node, a["entry"], a["t"], float("inf") if a["budget"] is None else a["budget"], size_of)
            results.append([m["header"]["seq"] for m in out])
        cases.append({"name": name, "buffer_s": buffer_s, "sends": sends, "acks": acks, "resent": results,
                      "left": [h.seq for h in node.store], "stats": node.stats, "status_at_10": status(node, 10.0)})
    return cases


def build() -> dict:
    sizes = [message("observation", 1, n) for n in (0, 10, 250)] + [{"type": "x", "header": {"seq": 1}, "name": "ž"}]
    return {"jamming": jamming_cases(), "linkcap": linkcap_cases(),
            "sizes": [{"payload": m, "bytes": size_of(m)} for m in sizes],
            "receiver": receiver_cases(), "node": node_cases()}


def main() -> None:
    PATH.write_text(json.dumps(build(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", PATH)


if __name__ == "__main__":
    main()
