"""Tests for the planned patrol sectors and the neighbour that covers a busy drone's sector."""

import unittest

from friend_foe.sweep import Setup, load_preset, make_scenario_and_truth
from pipeline.coverage import Grid, drone_mask, ground_masks, report
from pipeline.fleet import Fleet, PATROL, RETURN
from pipeline.sectors import Backfill, plan_sectors


def scenario():
    return make_scenario_and_truth(Setup(load_preset("medium"), "tuning", 1, None, 0, 0), 0, "clear", 0.0, False)[0]


class TestPlan(unittest.TestCase):
    def test_the_plan_watches_no_less_and_keeps_each_drones_speed_direction_and_sensors(self):
        sc = scenario()
        planned = plan_sectors(sc)
        self.assertGreaterEqual(report(planned)["watched"], report(sc)["watched"])
        for before, after in zip(sc["friendlies"], planned["friendlies"]):
            self.assertEqual((before["id"], before["sensors"]), (after["id"], after["sensors"]))
            self.assertEqual((before["loop"]["v"], before["loop"]["dir"]), (after["loop"]["v"], after["loop"]["dir"]))
            self.assertTrue(0.0 <= after["loop"]["cx"] <= 1000.0 and 60.0 <= after["loop"]["R"] <= 220.0)

    def test_the_plan_is_the_same_every_time_and_leaves_the_input_alone(self):
        sc = scenario()
        loops = [f["loop"] for f in sc["friendlies"]]
        self.assertEqual(plan_sectors(sc)["friendlies"], plan_sectors(sc)["friendlies"])
        self.assertEqual(loops, [f["loop"] for f in sc["friendlies"]])

    def test_a_second_viewpoint_counts_for_more_than_a_first(self):
        sc = scenario()
        grid = Grid(sc)
        one = grid.score(drone_mask(grid, sc["friendlies"][0]))
        two = grid.score(drone_mask(grid, sc["friendlies"][0]) * 2)
        self.assertGreater(two, one)
        self.assertGreater(len(ground_masks(grid, sc)), 0)


class TestBackfill(unittest.TestCase):
    def test_a_neighbour_covers_the_sector_of_a_drone_sent_away_and_goes_home_when_it_returns(self):
        sc = scenario()
        fleet, backfill = Fleet(sc), Backfill(Fleet(sc))
        backfill.fleet = fleet
        fleet.command("F1", (900.0, 900.0))
        backfill.step(1.0)
        helpers = list(backfill.cover)
        self.assertEqual(len(helpers), 1)
        helper = fleet.drones[helpers[0]]
        self.assertIsNot(helper.active_plan, helper.plan)
        self.assertEqual(helper.mode, RETURN)
        fleet.drones["F1"].mode = PATROL                   # F1 is back on its own loop
        backfill.step(2.0)
        self.assertEqual(backfill.cover, {})
        self.assertIs(helper.active_plan, helper.plan)


if __name__ == "__main__":
    unittest.main()
