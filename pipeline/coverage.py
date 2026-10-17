"""How much of the area the sensors watch, by range and field of view, and where the blind spots are.

A cell is watched at a moment when some sensor, from where its node is then, reaches it: inside its range, outside
its minimum range, and inside its field of view when it is a forward-pointing one. Clear weather and the catalog's
range numbers, which are assumptions unless `verified`. It uses the scenario only (never `truth.json`), so it is the
same picture a planner would have. Cells are bit masks (one per time step), so a union over nodes is a few ORs.

    python -m pipeline.coverage --seeds 4 [--sectors]
"""

import argparse
import math
from typing import Callable, Dict, List, Sequence, Tuple

from sensors.quality import load_modules

CELL_M = 50.0
TIME_STEPS = 12
EDGE_BAND_M = 100.0     # an intruder has to cross the border band, so a blind spot there is worse
EDGE_WEIGHT = 2
RANGE_KINDS = ("radar", "microphone")   # sensors whose readings give a range (tracker/measurement.py)

Pose = Tuple[float, float, float]      # x, y, heading (maths radians)


class Grid:
    def __init__(self, scenario: dict, cell_m: float = CELL_M, steps: int = TIME_STEPS, overlap: float = 1.0):
        self.overlap = overlap          # how much a cell seen from two viewpoints counts against one
        size = scenario["area"]["size_m"]
        n = max(2, int(size / cell_m))
        self.cells = [((i + 0.5) * size / n, (j + 0.5) * size / n) for j in range(n) for i in range(n)]
        self.times = [scenario["duration_s"] * (k + 0.5) / steps for k in range(steps)]
        self.n = n
        band = [min(x, y, size - x, size - y) < EDGE_BAND_M for x, y in self.cells]
        self.edge_mask = sum(1 << i for i, e in enumerate(band) if e)
        self.all_mask = (1 << len(self.cells)) - 1
        self.modules = load_modules()

    def mask(self, sensors: Sequence[dict], pose_at: Callable[[float], Pose]) -> List[List[int]]:
        """Two series of one int per time step: the cells the node's sensors watch then, and the cells its range-capable
        sensors (radar, microphone) watch. The tracker confirms a track only from a range reading or from two nodes, so a
        range-capable sensor counts as a second viewpoint on its own."""
        everything, ranged = [], []
        for t in self.times:
            px, py, heading = pose_at(t)
            m = r = 0
            for s in sensors:
                seen = self._cells_seen(self.modules[s["module"]]["sim"], px, py, heading)
                m |= seen
                if self.modules[s["module"]]["kind"] in RANGE_KINDS:
                    r |= seen
            everything.append(m)
            ranged.append(r)
        return [everything, ranged]

    def _cells_seen(self, sim: dict, px: float, py: float, heading: float) -> int:
        reach, near = sim["range_m"], sim.get("min_range_m", 0.0)
        half = math.radians(sim.get("fov_deg", 360.0)) / 2
        omni = half >= math.pi or sim.get("pointing", "forward") != "forward"
        m = 0
        for i, (x, y) in enumerate(self.cells):
            d = math.hypot(x - px, y - py)
            if d > reach or d < near:
                continue
            if omni or abs(_wrap(math.atan2(y - py, x - px) - heading)) <= half:
                m |= 1 << i
        return m

    def score(self, masks: Sequence[List[int]]) -> float:
        """Weighted share of (cell, moment) pairs watched, border cells counting double, a cell watched from two
        viewpoints counting twice as much as from one (it is what lets a track be confirmed); 0 to 1."""
        total = len(self.cells) + (EDGE_WEIGHT - 1) * bin(self.edge_mask).count("1")
        got = 0.0
        for k in range(len(self.times)):
            once = twice = 0
            for m in masks:
                twice |= once & m[k]
                once |= m[k]
            got += (self._weighted(once) + self.overlap * self._weighted(twice)) / (1 + self.overlap)
        return got / (total * len(self.times))

    def _weighted(self, cells: int) -> int:
        return bin(cells).count("1") + (EDGE_WEIGHT - 1) * bin(cells & self.edge_mask).count("1")


def _wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


def loop_pose(loop: Dict[str, float]) -> Callable[[float], Pose]:
    def at(t: float) -> Pose:
        a = loop["th0"] + loop["dir"] * (loop["v"] / loop["R"]) * t
        vx, vy = -loop["dir"] * math.sin(a), loop["dir"] * math.cos(a)
        return loop["cx"] + loop["R"] * math.cos(a), loop["cy"] + loop["R"] * math.sin(a), math.atan2(vy, vx)
    return at


def ground_mask(grid: Grid, g: dict) -> List[List[int]]:
    pose = (g["position"][0], g["position"][1], math.radians(90.0 - g["heading_deg"]))
    return grid.mask(g["sensors"], lambda t: pose)


def ground_masks(grid: Grid, scenario: dict) -> List[List[int]]:
    return [series for g in scenario["ground"] for series in ground_mask(grid, g)]


def drone_mask(grid: Grid, drone: dict) -> List[List[int]]:
    return grid.mask(drone["sensors"], loop_pose(drone["loop"]))


def report(scenario: dict) -> Dict[str, float]:
    """The watched score of the whole scenario (`Grid.score`)."""
    grid = Grid(scenario)
    masks = ground_masks(grid, scenario)
    for f in scenario["friendlies"]:
        masks += drone_mask(grid, f)
    return {"watched": grid.score(masks)}


def main() -> None:
    from friend_foe.sweep import Setup, load_preset, make_scenario_and_truth
    from pipeline.sectors import plan_sectors
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", default="medium")
    ap.add_argument("--seeds", type=int, default=4)
    args = ap.parse_args()
    setup = Setup(load_preset(args.preset), "tuning", args.seeds, None, 0, 0)
    for i in range(args.seeds):
        scenario, _ = make_scenario_and_truth(setup, i, "clear", 0.0, False)
        before, after = report(scenario)["watched"], report(plan_sectors(scenario))["watched"]
        print(f"seed {i}: watched {before:.1%} on the scenario's loops, {after:.1%} with planned sectors")


if __name__ == "__main__":
    main()
