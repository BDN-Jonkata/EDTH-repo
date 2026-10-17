"""Merge the `local_track` messages of several nodes into one set of tracks with global IDs.

A merger (C2 or any reachable node) keeps the latest estimate of every local track it has heard, moves
each to now with constant velocity, groups estimates that are the same object, and merges each group with
covariance intersection (`fusion/ci.py`). Two tracks of one node are never the same object.
Delayed updates cannot replace a newer local state. Association requires compatible velocity uncertainty
and no conflicting verified identity, including across every member of a proposed group.

Global IDs: a global ID is tied to the local tracks that make it up, so it survives when a node joins the
group, leaves it, or a local track gets a new ID, as long as one member remains. If a group holds members
of different global IDs the oldest one wins. An estimate unheard for `ttl_s` is forgotten; a global ID
with no members left is freed.
"""

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

from fusion.ci import inverse, intersect_all
from fusion.messages import friend_id_of, state_and_cov
from tracker.ekf import predict
from tracker.tracker import Track

GATE_CHI2 = 9.21        # 2 degrees of freedom, 99 %


@dataclass
class FusionConfig:
    ttl_s: float = 4.0                  # a local track not heard from this long is forgotten
    accel_noise_mps2: float = 3.0       # how much the estimate is let to grow while it waits
    min_gate_m: float = 10.0            # tracks closer than this are one object whatever their covariances say


@dataclass
class Estimate:
    node: str
    key: str
    t: float
    state: List[float]
    cov: List[List[float]]
    friend_id: Optional[str]


class Merger:
    def __init__(self, config: Optional[FusionConfig] = None):
        self.config = config or FusionConfig()
        self._heard: Dict[str, Estimate] = {}
        self._latest: Dict[str, Tuple[float, int]] = {}   # state time and sequence, including expired tracks
        self._gid: Dict[str, str] = {}              # local track key -> global id
        self._born: Dict[str, float] = {}
        self._next = 1

    def ingest(self, messages: Sequence[dict]) -> None:
        for m in messages:
            if m["type"] != "local_track":
                continue
            key = m["local_track_id"]
            order = (m["t_state"], m["header"]["seq"])
            if order <= self._latest.get(key, (-math.inf, -1)):
                continue
            state, cov = state_and_cov(m)
            self._latest[key] = order
            self._heard[key] = Estimate(m["header"]["source_id"], key, m["t_state"], state, cov, friend_id_of(m))

    def step(self, t: float) -> List[Track]:
        self._heard = {k: e for k, e in self._heard.items() if t - e.t <= self.config.ttl_s}
        self._gid = {k: g for k, g in self._gid.items() if k in self._heard}
        now = [self._at(e, t) for e in self._heard.values()]
        out, used = [], set()
        for group in self._groups(now):
            gid = self._global_id(group, used)
            state, cov = intersect_all([(e.state, e.cov) for e in group])
            born = self._born.setdefault(gid, t)
            friend = next((e.friend_id for e in group if e.friend_id), None)
            out.append(Track(gid, state, cov, born, max(self._heard[e.key].t for e in group), confirmed=True,
                             origin="fused", friend_id=friend))
        self._born = {g: b for g, b in self._born.items() if g in used}
        return out

    def _at(self, e: Estimate, t: float) -> Estimate:
        state, cov = predict(e.state, e.cov, max(0.0, t - e.t), self.config.accel_noise_mps2)
        return Estimate(e.node, e.key, e.t, state, cov, e.friend_id)

    def _distance2(self, a: Estimate, b: Estimate, axes: Tuple[int, int] = (0, 1)) -> float:
        """Squared Mahalanobis distance of a position or velocity pair, including both uncertainties."""
        dx, dy = (a.state[i] - b.state[i] for i in axes)
        s = [[a.cov[i][j] + b.cov[i][j] for j in axes] for i in axes]
        si = inverse(s)
        return dx * (si[0][0] * dx + si[0][1] * dy) + dy * (si[1][0] * dx + si[1][1] * dy)

    def _compatible(self, a: Estimate, b: Estimate) -> bool:
        if a.friend_id and b.friend_id and a.friend_id != b.friend_id:
            return False
        return self._distance2(a, b, (2, 3)) <= GATE_CHI2

    def _groups(self, estimates: List[Estimate]) -> List[List[Estimate]]:
        """Group compatible estimates of different nodes, closest position pairs first."""
        pairs = []
        for i, a in enumerate(estimates):
            for b in estimates[i + 1:]:
                if a.node == b.node or not self._compatible(a, b):
                    continue
                d = math.hypot(a.state[0] - b.state[0], a.state[1] - b.state[1])
                if d <= self.config.min_gate_m or self._distance2(a, b) <= GATE_CHI2:
                    pairs.append((self._distance2(a, b), a.key, b.key))
        groups = {e.key: [e] for e in estimates}
        for _, ka, kb in sorted(pairs):
            ga, gb = groups[ka], groups[kb]
            if ga is gb or {e.node for e in ga} & {e.node for e in gb}:
                continue
            if not all(self._compatible(a, b) for a in ga for b in gb):
                continue
            merged = ga + gb
            for e in merged:
                groups[e.key] = merged
        seen, out = set(), []
        for g in groups.values():
            if id(g) not in seen:
                seen.add(id(g))
                out.append(g)
        return out

    def _global_id(self, group: List[Estimate], used: Set[str]) -> str:
        known = sorted({self._gid[e.key] for e in group if e.key in self._gid}, key=lambda g: int(g[1:]))
        gid = next((g for g in known if g not in used), None)
        if gid is None:
            gid, self._next = f"G{self._next}", self._next + 1
        used.add(gid)
        for e in group:
            self._gid[e.key] = gid
        return gid
