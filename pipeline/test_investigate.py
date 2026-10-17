"""Tests for the commanded drone fleet, the dispatcher and the investigation loop in the pipeline."""

import math
import unittest

from friend_foe.sweep import Setup, load_preset, make_scenario_and_truth
from pipeline.dispatch import Dispatcher, SAFE_STANDOFF_M
from pipeline.fleet import Fleet
from pipeline.run import scored_frames
from scoring.truth import with_recorded_samples

LOOP = {"cx": 200.0, "cy": 200.0, "R": 100.0, "v": 10.0, "dir": 1, "th0": 0.0}
EYE = {"module": "eo_visible_mini4", "kind": "eo_camera"}


def scenario(*ids_and_centres):
    friendlies = [{"id": i, "platform": "mini4pro", "altitude_m": 60, "sensors": [EYE],
                   "loop": dict(LOOP, cx=cx, cy=cy)} for i, cx, cy in ids_and_centres]
    return {"friendlies": friendlies}


def request(track_id, x, y, feasible=True, recommended=80.0):
    return {"track_id": track_id, "position": [x, y, 0.0],
            "standoff_by_module": {"eo_visible_mini4": {"feasible": feasible, "recommended_m": recommended}}}


def run_fleet(fleet, seconds, start=0.0, dt=0.1):
    t = start
    for _ in range(int(seconds / dt)):
        t += dt
        fleet.step(t)
    return t


class TestFleet(unittest.TestCase):
    def test_a_drone_flies_its_patrol_loop_until_commanded(self):
        fleet = Fleet(scenario(("F1", 200, 200)))
        run_fleet(fleet, 5.0)
        d = fleet.drones["F1"]
        self.assertAlmostEqual(math.hypot(d.x - 200, d.y - 200), 100.0, places=3)

    def test_a_commanded_drone_reaches_its_point_within_its_speed_limit(self):
        fleet = Fleet(scenario(("F1", 200, 200)))
        fleet.command("F1", (600.0, 600.0), face=(700.0, 700.0))
        fastest, t = 0.0, 0.0
        for _ in range(900):
            t += 0.1
            fleet.step(t)
            fastest = max(fastest, math.hypot(fleet.drones["F1"].vx, fleet.drones["F1"].vy))
        d = fleet.drones["F1"]
        self.assertLess(math.hypot(d.x - 600, d.y - 600), 3.0)
        self.assertLessEqual(fastest, d.max_speed + 1e-6)
        self.assertAlmostEqual(d.heading, math.atan2(700 - d.y, 700 - d.x), places=3)   # facing the point

    def test_a_released_drone_flies_back_and_rejoins_the_patrol(self):
        fleet = Fleet(scenario(("F1", 200, 200)))
        fleet.command("F1", (500.0, 500.0))
        t = run_fleet(fleet, 40.0)
        self.assertFalse(fleet.is_free("F1"))
        fleet.release("F1")
        run_fleet(fleet, 60.0, start=t)
        self.assertTrue(fleet.is_free("F1"))


class TestDispatcher(unittest.TestCase):
    def make(self, *ids_and_centres, **options):
        sc = scenario(*ids_and_centres)
        fleet = Fleet(sc)
        return fleet, Dispatcher(fleet, sc, {}, **options)

    def test_the_closest_free_drone_with_a_feasible_module_is_sent(self):
        fleet, dispatcher = self.make(("F1", 100, 100), ("F2", 800, 800))
        statuses = dispatcher.handle(0.0, [request("T1", 150, 150)])
        self.assertEqual([(s["drone_id"], s["state"]) for s in statuses], [("F1", "assigned")])

    def test_no_feasible_module_means_no_drone(self):
        fleet, dispatcher = self.make(("F1", 100, 100))
        self.assertEqual(dispatcher.handle(0.0, [request("T1", 150, 150, feasible=False)]), [])
        self.assertEqual(dispatcher.stats["no_drone"], 1)

    def test_one_drone_per_track_and_a_limit_on_how_many_investigations_run(self):
        fleet, dispatcher = self.make(("F1", 100, 100), ("F2", 300, 300), ("F3", 500, 500), max_active=2)
        dispatcher.handle(0.0, [request("T1", 150, 150), request("T1", 150, 150), request("T2", 350, 350), request("T3", 550, 550)])
        self.assertEqual(sorted(dispatcher.tasks), ["T1", "T2"])

    def test_a_drone_flies_out_keeps_its_distance_stays_then_goes_home(self):
        fleet, dispatcher = self.make(("F1", 100, 100))
        dispatcher.handle(0.0, [request("T1", 400, 400, recommended=80.0)])
        states, t = [], 0.0
        for _ in range(1500):
            t += 0.1
            fleet.step(t)
            states += [s["state"] for s in dispatcher.step(t, {"T1": (400.0, 400.0)})]
            if "done" in states:
                break
        self.assertEqual(states, ["en_route", "on_station", "done"])
        self.assertTrue(dispatcher.log[-1]["t_station"] is not None)
        self.assertEqual(fleet.drones["F1"].mode, "return")

    def test_the_standoff_never_goes_below_the_safe_distance(self):
        fleet, dispatcher = self.make(("F1", 100, 100))
        dispatcher.handle(0.0, [request("T1", 400, 400, recommended=10.0)])
        self.assertEqual(dispatcher.tasks["T1"].standoff_m, SAFE_STANDOFF_M)

    def test_a_track_that_disappears_aborts_the_investigation(self):
        fleet, dispatcher = self.make(("F1", 100, 100), lost_s=3.0)
        dispatcher.handle(0.0, [request("T1", 400, 400)])
        states, t = [], 0.0
        for _ in range(80):
            t += 0.1
            fleet.step(t)
            states += [s["state"] for s in dispatcher.step(t, {})]
        self.assertIn("aborted", states)
        self.assertEqual(dispatcher.tasks, {})


class TestRecordedTruth(unittest.TestCase):
    def test_recorded_rows_replace_only_the_named_objects(self):
        truth = {"objects": [{"id": "F1", "samples": [[0, 0, 0, 0, 0]]}, {"id": "H1", "samples": [[0, 5, 5, 0, 0]]}]}
        out = with_recorded_samples(truth, {"F1": [[0, 9, 9, 1, 1]]})
        self.assertEqual(out["objects"][0]["samples"], [[0, 9, 9, 1, 1]])
        self.assertEqual(out["objects"][1]["samples"], [[0, 5, 5, 0, 0]])
        self.assertEqual(truth["objects"][0]["samples"], [[0, 0, 0, 0, 0]])     # the input is not changed


class TestInvestigationInThePipeline(unittest.TestCase):
    def test_suspicious_tracks_send_drones_and_the_run_records_where_they_flew(self):
        sc, truth = make_scenario_and_truth(Setup(load_preset("medium"), "tuning", 1), 0, "clear", 0.0, False)
        stats, recorded = {}, {}
        frames = list(scored_frames(sc, sc["seed"], investigate=True, stats=stats, recorded=recorded))
        self.assertGreater(stats["requests"], 0)
        self.assertGreater(stats["dispatched"], 0)
        self.assertEqual(set(recorded), {f["id"] for f in sc["friendlies"]})
        self.assertEqual(len(recorded["F1"]), len(frames))
        scripted = truth["objects"][0]["samples"]
        self.assertTrue(with_recorded_samples(truth, recorded)["objects"][0]["samples"] != scripted)

    def test_without_investigation_nothing_is_dispatched_and_nothing_is_recorded(self):
        sc, _ = make_scenario_and_truth(Setup(load_preset("medium"), "tuning", 1), 0, "clear", 0.0, False)
        stats, recorded = {}, {}
        list(scored_frames(sc, sc["seed"], stats=stats, recorded=recorded))
        self.assertEqual((stats, recorded), ({}, {}))


if __name__ == "__main__":
    unittest.main()
