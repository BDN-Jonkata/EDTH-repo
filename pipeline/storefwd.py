"""Store-and-forward on the Python channel, as the mock simulation does it (`ui/viewer/sim.js`, rules in
`common/storefwd.py`): when the scenario turns `degradations.store_forward` on,

- every message a node sends is kept until C2 acknowledges it;
- C2 sends one `c2_ack` a second to every live node, over that node's own link (so an outage or a jam cuts the ack
  too), and a node that hears it resends what C2 is missing, oldest first, within its share of a capped link;
- a drone puts its `status` (oldest `seq` it still holds) in each beacon and a ground sensor sends `node_status`
  once a second, so C2 stops asking for what expired;
- C2 drops a message whose `seq` already arrived, and a message older than `LATE_S` on arrival goes to history, not
  to the live picture. A late observation is kept only when the tracker can replay it (`keep_late_observations`,
  `--oosm`); a late beacon never is, because the pose filter would be pulled back to where the drone was.

Not modelled: the nodes' own link-health states (`health/` judges the links in Python).
"""

from typing import Dict, List

from common.channel import Channel
from common.codec import Sequencer
from common.linkcap import size_of
from common.storefwd import (ACK_EVERY_S, BUFFER_S, LATE_S, RESEND_SHARE, Node, Receiver, ack_entry, on_ack, receive, remember,
                             skip_below, status)

STATUS_EVERY_S = 1.0     # a ground sensor reports its status this often


def store_forward_on(scenario: dict) -> bool:
    return bool((scenario["degradations"].get("store_forward") or {}).get("enabled"))


class StoreForward:
    def __init__(self, scenario: dict, channel: Channel, sequencers: Dict[str, Sequencer], keep_late_observations: bool):
        cfg = scenario["degradations"]["store_forward"]
        self.channel, self.sequencers, self.keep_late = channel, sequencers, keep_late_observations
        self.share = cfg.get("resend_share") or RESEND_SHARE
        self.ground = [g["id"] for g in scenario["ground"]]
        self.nodes = {n: Node(buffer_s=cfg.get("buffer_s") or BUFFER_S)
                      for n in self.ground + [f["id"] for f in scenario["friendlies"]]}
        self.rx = {n: Receiver() for n in self.nodes}
        self.stats = {"duplicates": 0, "late": 0}
        self._next_ack = self._next_status = ACK_EVERY_S

    # ------------------------------------------------------------------ node side
    def sent(self, message: dict, t: float) -> None:
        """A node sent `message`: keep it until C2 has it."""
        node = self.nodes.get(message["header"]["source_id"])
        if node is not None:
            remember(node, message, t)

    def stamp_status(self, beacon: dict, t: float) -> None:
        """A drone reports what it still holds in its beacon (call before `sent`)."""
        beacon["status"] = status(self.nodes[beacon["header"]["source_id"]], t)

    def node_status(self, t: float) -> List[dict]:
        """The ground sensors' `node_status` messages due at `t`, to be sent (and kept) like any other."""
        if t < self._next_status - 1e-9:
            return []
        self._next_status += STATUS_EVERY_S
        return [{"type": "node_status", "header": self.sequencers.setdefault(n, Sequencer(n)).header(t),
                 "node_id": n, "status": status(self.nodes[n], t)} for n in self.ground if self.channel.alive(n, t)]

    # --------------------------------------------------------------------- C2 side
    def send_acks(self, t: float) -> None:
        """C2's ack, once a second, to every node that is alive."""
        if t < self._next_ack - 1e-9:
            return
        self._next_ack += ACK_EVERY_S
        message = {"type": "c2_ack", "header": self.sequencers.setdefault("C2", Sequencer("C2")).header(t),
                   "acks": {n: ack_entry(r) for n, r in self.rx.items()}}
        for node in self.nodes:
            self.channel.send_to(node, dict(message, to=node), t)

    def _resend(self, ack: dict, t: float) -> None:
        node = ack["to"]
        cap = self.channel.cap
        budget = self.share * cap.bytes_per_s * ACK_EVERY_S if cap is not None else float("inf")
        for payload in on_ack(self.nodes[node], ack["acks"][node], t, budget, size_of):
            self.channel.send(payload, t)

    def receive(self, delivered: List[dict], t: float) -> List[dict]:
        """What C2 does with what arrived: acks go to their node, duplicates and status messages are consumed, late
        messages go to history. The rest is the live picture."""
        live = []
        for m in delivered:
            if m["type"] == "c2_ack":
                self._resend(m, t)
            elif self._counts(m) and self._live(m, t):
                live.append(m)
        return live

    def _counts(self, m: dict) -> bool:
        """False for a duplicate; folds a status into what C2 waits for. A node_status is consumed here too."""
        source = m["header"]["source_id"]
        r = self.rx.get(source)
        if r is None:
            return True
        if not receive(r, m["header"]["seq"]):
            self.stats["duplicates"] += 1
            return False
        if "status" in m:
            skip_below(r, m["status"]["oldest_seq"])
        return m["type"] != "node_status"

    def _live(self, m: dict, t: float) -> bool:
        if t - m["header"]["t_sent"] <= LATE_S:
            return True
        self.stats["late"] += 1
        return self.keep_late and m["type"] == "observation"
