"""Per-node link health and per-message trust, for everything that reads delivered messages.

`HealthMonitor.observe(message, t)` is called for every delivered message (the header's `source_id` and `seq`);
then `state`, `trust` and `explains_silence` answer for any node. A node never heard is taken as `ok`.

    trust(node, t, age_s)        health factor of the node's state times 0.5 ** (age / half-life); 0 to 1
    explains_silence(node, t)    how much a missing message of this node is explained by its link, 0 to 1
    is_late(age_s)               a reading older than `late_s`: history only, not the live picture

The tracker scales a reading's noise by `1 / trust` (`health/trust.py`); the friend/foe estimator lets the
silence of a node whose link is down count for less (`friend_foe/estimator.py`, `silence_explained`).
"""

from typing import Dict, Iterable, Optional

from health.link import DEGRADED, OFFLINE, OK, PRESUMED_DEAD, HealthConfig, LinkHealth

HEALTH_FACTOR = {OK: 1.0, DEGRADED: 0.5, OFFLINE: 0.2, PRESUMED_DEAD: 0.0}
SILENCE_FLOOR = {OK: 0.0, DEGRADED: 0.7, OFFLINE: 1.0, PRESUMED_DEAD: 0.5}   # a dead node's silence is explained only in part


class HealthMonitor:
    def __init__(self, config: Optional[HealthConfig] = None):
        self.config = config or HealthConfig()
        self.nodes: Dict[str, LinkHealth] = {}

    def observe(self, message: dict, t: float) -> None:
        header = message["header"]
        node = self.nodes.setdefault(header["source_id"], LinkHealth(self.config, t))
        node.observe(header["seq"], t)

    def observe_all(self, messages: Iterable[dict], t: float) -> None:
        for m in messages:
            self.observe(m, t)

    def state(self, node: str, t: float) -> str:
        return self.nodes[node].state(t) if node in self.nodes else OK

    def trust(self, node: str, t: float, age_s: float = 0.0) -> float:
        return HEALTH_FACTOR[self.state(node, t)] * 0.5 ** (max(0.0, age_s) / self.config.half_life_s)

    def explains_silence(self, node: str, t: float) -> float:
        state = self.state(node, t)
        p_bad = self.nodes[node].p_bad if node in self.nodes else 0.0
        return max(SILENCE_FLOOR[state], min(p_bad, 0.5))

    def is_late(self, age_s: float) -> bool:
        return age_s > self.config.late_s

    def snapshot(self, t: float) -> Dict[str, dict]:
        return {n: {"state": h.state(t), "p_bad": h.p_bad, "loss_rate": h.loss_rate, "alarm": h.alarm,
                    "silent_s": t - h.last_heard} for n, h in self.nodes.items()}
