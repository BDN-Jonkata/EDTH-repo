"""Patrol sectors for the friendly drones, and a neighbour that covers a sector while its drone is busy.

The scenario gives each drone a circular patrol loop with a random centre, so the loops overlap in places and leave
others unwatched (about 55 % of the area is watched at any moment, and an intruder is outside every sensor's reach
about a fifth of the time; see `pipeline/coverage.py`). `plan_sectors` moves the centres and radii of the loops, keeping
each drone's speed and direction, so that the area is watched as much as possible, with the border counting double,
given the sensors the drone carries and where the ground sensors already look. It knows nothing about where the
hostiles go: only the scenario's nodes and the catalog.

`Backfill` handles a sector going dark: when a drone leaves its loop for an investigation, the closest drone still on
patrol flies a wider loop between the two sectors, and goes back to its own when the first drone is home.
"""

import copy
import math
import random
from typing import Dict, List, Optional

from pipeline.coverage import Grid, drone_mask, ground_mask, ground_masks
from pipeline.fleet import Fleet, PATROL

MIN_RADIUS_M, MAX_RADIUS_M = 60.0, 220.0
ROUNDS, TRIES = 3, 10
BACKFILL_MAX_RADIUS_M = 260.0
_cache: Dict[tuple, dict] = {}


def plan_sectors(scenario: dict, place_ground: bool = False, overlap: float = 1.0) -> dict:
    """A copy of the scenario whose drones fly better loops. Deterministic: the scenario's seed drives the search.
    `place_ground` also moves the ground sensors (a deployment choice made before the mission); `overlap` is how much
    a cell seen from two viewpoints counts against one (1 = twice as much; larger pulls the drones together)."""
    key = (scenario["id"], scenario["seed"], scenario["preset"], place_ground, overlap)
    if key not in _cache:
        _cache[key] = _plan(scenario, place_ground, overlap)
    return copy.deepcopy(_cache[key])


def _plan(scenario: dict, place_ground: bool, overlap: float) -> dict:
    out = copy.deepcopy(scenario)
    grid, rng, size = Grid(scenario, overlap=overlap), random.Random(scenario["seed"]), scenario["area"]["size_m"]
    movable = out["friendlies"] + (out["ground"] if place_ground else [])
    fixed = [] if place_ground else ground_masks(grid, scenario)
    masks = [_masks(grid, n) for n in movable]              # per node: its two mask series
    best = grid.score(fixed + [s for m in masks for s in m])
    for _ in range(ROUNDS):
        for i, node in enumerate(movable):
            for _ in range(TRIES):
                trial = _moved(node, rng, size)
                m = _masks(grid, trial)
                others = [s for j, mj in enumerate(masks) if j != i for s in mj]
                score = grid.score(fixed + others + m)
                if score > best:
                    best, masks[i] = score, m
                    node.clear()
                    node.update(trial)
    return out


def _masks(grid: Grid, node: dict) -> List[List[int]]:
    return drone_mask(grid, node) if "loop" in node else ground_mask(grid, node)


def _moved(node: dict, rng: random.Random, size: float) -> dict:
    """A drone with its loop shifted by up to 150 m and its radius changed by up to 40 m; a ground sensor moved by up
    to 150 m and turned by up to 60 degrees."""
    trial = copy.deepcopy(node)
    if "loop" not in node:
        x, y = node["position"]
        trial["position"] = [min(size, max(0.0, x + rng.uniform(-150, 150))), min(size, max(0.0, y + rng.uniform(-150, 150)))]
        trial["heading_deg"] = (node["heading_deg"] + rng.uniform(-60, 60)) % 360.0
        return trial
    loop = trial["loop"]
    loop["cx"] = min(size, max(0.0, loop["cx"] + rng.uniform(-150, 150)))
    loop["cy"] = min(size, max(0.0, loop["cy"] + rng.uniform(-150, 150)))
    loop["R"] = min(MAX_RADIUS_M, max(MIN_RADIUS_M, loop["R"] + rng.uniform(-40, 40)))
    return trial


class Backfill:
    """While a drone is away on an investigation, the nearest free drone on patrol covers between the two sectors."""

    def __init__(self, fleet: Fleet):
        self.fleet = fleet
        self.cover: Dict[str, str] = {}          # covering drone -> the drone whose sector it watches
        self.settling: set = set()               # helpers flying home: not away on a task, just returning

    def step(self, t: float) -> None:
        self._release(t)
        self.settling = {i for i in self.settling if self.fleet.drones[i].mode != PATROL}
        away = [i for i, d in self.fleet.drones.items() if d.mode != PATROL and d.active_plan is d.plan
                and i not in self.cover.values() and i not in self.settling]
        for vacated in away:
            helper = self._nearest_helper(vacated)
            if helper is not None:
                self.cover[helper] = vacated
                self.fleet.cover(helper, self._between(helper, vacated, t))

    def _release(self, t: float) -> None:
        for helper, vacated in list(self.cover.items()):
            if self.fleet.drones[vacated].mode == PATROL or self.fleet.drones[helper].active_plan is self.fleet.drones[helper].plan:
                self.fleet.uncover(helper)
                self.settling.add(helper)
                del self.cover[helper]

    def _nearest_helper(self, vacated: str) -> Optional[str]:
        home = self.fleet.drones[vacated].plan["loop"]
        candidates = [(math.hypot(d.plan["loop"]["cx"] - home["cx"], d.plan["loop"]["cy"] - home["cy"]), i)
                      for i, d in self.fleet.drones.items()
                      if d.mode == PATROL and d.active_plan is d.plan and i not in self.cover]
        return min(candidates)[1] if candidates else None

    def _between(self, helper: str, vacated: str, t: float) -> dict:
        """A loop centred between the two sectors and wide enough to reach both."""
        own, other = self.fleet.drones[helper], self.fleet.drones[vacated]
        a, b = own.plan["loop"], other.plan["loop"]
        cx, cy = (a["cx"] + b["cx"]) / 2, (a["cy"] + b["cy"]) / 2
        radius = min(BACKFILL_MAX_RADIUS_M, max(a["R"], b["R"]) + math.hypot(a["cx"] - b["cx"], a["cy"] - b["cy"]) / 2)
        th0 = math.atan2(own.y - cy, own.x - cx) - a["dir"] * (a["v"] / radius) * t
        return {**own.plan, "loop": {"cx": cx, "cy": cy, "R": radius, "v": a["v"], "dir": a["dir"], "th0": th0}}
