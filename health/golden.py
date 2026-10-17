"""Shared test cases for the link-health module, so a JavaScript port can be checked against the Python reference.

The reference is `health/link.py` and `health/monitor.py`. The file `testdata/health_cases.json` is generated from
them, so a test that runs the same cases through the JavaScript is what proves the two agree. Do not edit it by hand:

    python -m health.golden                 # rewrite the file
    python -m pytest health/test_golden.py  # fails if the file no longer matches the code

Compare floats with a tolerance (relative 1e-9). Each case: a list of delivered messages `{source, seq, t}` and the
times to ask at; for each, every node's state, p_bad, loss rate, CUSUM value and alarm, and the monitor's trust and
explained-silence for it.
"""

import json
from pathlib import Path
from typing import Dict, List

from health.link import HealthConfig, wilson
from health.monitor import HealthMonitor

PATH = Path(__file__).parent / "testdata" / "health_cases.json"


def _run(messages: List[dict], ask_at: List[float]) -> List[dict]:
    monitor, out, i = HealthMonitor(HealthConfig()), [], 0
    messages = sorted(messages, key=lambda m: m["t"])
    for t in ask_at:
        while i < len(messages) and messages[i]["t"] <= t:
            m = messages[i]
            monitor.observe({"header": {"source_id": m["source"], "seq": m["seq"]}}, m["t"])
            i += 1
        snap = monitor.snapshot(t)
        out.append({"t": t, "nodes": {n: dict(s, trust=monitor.trust(n, t), trust_age_5=monitor.trust(n, t, 5.0),
                                              explains_silence=monitor.explains_silence(n, t)) for n, s in snap.items()}})
    return out


def _stream(source: str, start: float, end: float, rate: float, first_seq: int, lost=()) -> List[dict]:
    """Messages at `rate` Hz from `start` to `end`; the sequence numbers in `lost` are numbered but not delivered."""
    count = int(round((end - start) * rate))
    return [{"source": source, "seq": first_seq + k, "t": round(start + k / rate, 6)}
            for k in range(count) if first_seq + k not in set(lost)]


def link_cases() -> List[dict]:
    clean = _stream("F1", 0.0, 30.0, 2.0, 1)
    bursty = _stream("F1", 0.0, 60.0, 2.0, 1, lost=[s for s in range(20, 70) if s % 10 < 7])
    steady_loss = _stream("F1", 0.0, 60.0, 2.0, 1, lost=[s for s in range(1, 121) if s % 3 == 0])
    outage = _stream("F1", 0.0, 10.0, 2.0, 1) + _stream("F1", 30.0, 40.0, 2.0, 61)
    dead = _stream("F2", 0.0, 20.0, 2.0, 1) + _stream("F1", 0.0, 60.0, 2.0, 1)
    ask = [1, 5, 10, 14, 15, 20, 25, 29, 31, 35, 40, 59]
    return [{"name": name, "messages": msgs, "ask_at": [float(a) for a in ask], "expected": _run(msgs, [float(a) for a in ask])}
            for name, msgs in (("clean", clean), ("bursty", bursty), ("steady_loss", steady_loss),
                               ("outage_then_resume", outage), ("one_node_dies", dead))]


def wilson_cases() -> List[dict]:
    return [{"missed": m, "n": n, "z": 1.96, "interval": list(wilson(m, n, 1.96))}
            for m, n in ((0, 0), (0, 40), (4, 40), (12, 40), (20, 40), (40, 40), (1, 5))]


def build() -> Dict[str, object]:
    return {"config": HealthConfig().__dict__, "link_cases": link_cases(), "wilson_cases": wilson_cases()}


if __name__ == "__main__":
    PATH.parent.mkdir(exist_ok=True)
    PATH.write_text(json.dumps(build(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print("wrote", PATH)
