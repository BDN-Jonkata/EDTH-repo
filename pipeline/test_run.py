"""End-to-end tests: sensors -> channel -> tracker -> friend/foe -> scoring, on seeder scenarios."""

import unittest

from friend_foe.sweep import Setup, load_preset, make_scenario_and_truth
from pipeline.run import Pipeline, run, scored_frames
from scoring.metrics import ScoreConfig, score


def scenario_and_truth(preset="medium", loss=0.0, index=0):
    return make_scenario_and_truth(Setup(load_preset(preset), "tuning", 1), index, "clear", loss, False)


class TestPipeline(unittest.TestCase):
    def test_clean_run_tracks_hostiles_and_flags_no_friendly(self):
        sc, truth = scenario_and_truth("medium")
        s = score(truth, scored_frames(sc, sc["seed"]), ScoreConfig(warmup_s=10.0))
        self.assertEqual(s.friendlies_flagged, 0)
        self.assertGreater(s.hostile_detected_frac, 0.3)
        self.assertLess(s.pos_rmse_m, 25.0)

    def test_same_seed_gives_the_same_score(self):
        sc, truth = scenario_and_truth("medium")
        a = score(truth, scored_frames(sc, sc["seed"]))
        b = score(truth, scored_frames(sc, sc["seed"]))
        self.assertEqual(a, b)

    def test_losing_every_message_leaves_the_tracker_blind(self):
        sc, truth = scenario_and_truth("medium", loss=1.0)
        frames = list(run(sc, sc["seed"]))
        self.assertTrue(all(not f.tracks and f.readings_used == 0 and not f.beacons for f in frames))

    def test_heavy_loss_hurts_detection_but_not_by_flagging_friendlies_the_way_it_hurts_hostiles(self):
        sc0, truth0 = scenario_and_truth("medium", loss=0.0)
        sc9, truth9 = scenario_and_truth("medium", loss=0.9)
        clean = score(truth0, scored_frames(sc0, sc0["seed"]), ScoreConfig(warmup_s=10.0))
        lossy = score(truth9, scored_frames(sc9, sc9["seed"]), ScoreConfig(warmup_s=10.0))
        self.assertLess(lossy.hostile_detected_frac, clean.hostile_detected_frac)


class TestChannelFeatures(unittest.TestCase):
    """Jamming zones, a link cap and node dropout from the scenario reach the pipeline (they are in `common/channel.py`)."""

    def delivered(self, change):
        sc, _ = scenario_and_truth("medium")
        sc["degradations"]["network"]["enabled"] = True
        change(sc["degradations"])
        sc["duration_s"] = 40
        return sum(f.readings_used + len(f.beacons) for f in run(sc, sc["seed"]))

    def test_a_jamming_zone_over_the_whole_area_lowers_what_arrives(self):
        zone = {"x": 500, "y": 500, "radius_m": 2000, "loss": 0.9}
        clean = self.delivered(lambda d: None)
        jammed = self.delivered(lambda d: d["network"].update(jamming_zones=[zone]))
        self.assertLess(jammed, 0.4 * clean)

    def test_a_low_link_cap_lowers_what_arrives(self):
        self.assertLess(self.delivered(lambda d: d["network"].update(bandwidth_kbps=2)), self.delivered(lambda d: None))

    def test_a_dropped_node_stops_sending(self):
        every_node = lambda d: d.update(dropout=[{"node": n, "t": 10.0} for n in ("F1", "F2", "F3", "F4", "F5", "GS1", "GS2")])
        self.assertLess(self.delivered(every_node), 0.5 * self.delivered(lambda d: None))


class TestOutOfSequence(unittest.TestCase):
    """`oosm`: readings that a delay burst makes late are used at the time they were taken, not left out (with `trust`)."""

    def readings_used(self, **options):
        sc, _ = scenario_and_truth("medium")
        sc["duration_s"] = 40
        sc["degradations"]["sensor_faults"] = [{"node": n, "kind": "delay_burst", "t_start": 10.0, "t_end": 30.0, "extra_ms": 4000}
                                               for n in ("GS1", "GS2")]
        pipeline = Pipeline(sc, sc["seed"], **options)
        return sum(pipeline.step(round(k * 0.1, 6)).readings_used for k in range(401))

    def test_late_readings_are_kept_with_the_option_and_left_out_without(self):
        left_out = self.readings_used(trust=True)
        kept = self.readings_used(trust=True, oosm=True)
        self.assertGreater(kept, left_out)

    def test_it_changes_nothing_when_nothing_is_late(self):
        sc, truth = scenario_and_truth("medium")
        sc["duration_s"] = 30
        a = [(t, [(e.track_id, e.x, e.y) for e in ests]) for t, ests in scored_frames(sc, sc["seed"], trust=True)]
        b = [(t, [(e.track_id, e.x, e.y) for e in ests]) for t, ests in scored_frames(sc, sc["seed"], trust=True, oosm=True)]
        self.assertEqual(a, b)


class TestClocks(unittest.TestCase):
    """`clocks` stamps readings by the node's own clock; `timesync` estimates those clocks back (tracker/timesync.py)."""

    def clock_error_ms(self, pipeline, t):
        return [abs(pipeline.sync.offset(n) - (c.offset_s + c.drift * t)) * 1000 for n, c in pipeline.observations.clocks.items()
                if n in pipeline.sync._low]

    def test_readings_carry_the_node_clock_only_when_asked(self):
        sc, _ = scenario_and_truth("hard")
        plain, stamped = Pipeline(sc, sc["seed"]), Pipeline(sc, sc["seed"], clocks=True)
        self.assertEqual(plain.observations.clocks, {})
        a = [o["t_obs"] for k in range(20) for o in plain.observations.at(round(k * 0.1, 6))]
        b = [o["t_obs"] for k in range(20) for o in stamped.observations.at(round(k * 0.1, 6))]
        self.assertEqual(len(a), len(b))
        self.assertNotEqual(a, b)
        self.assertEqual(set(stamped.observations.clocks), {"F1", "F2", "F3", "F4", "F5", "GS1", "GS2"})

    def test_the_clocks_are_found_within_a_few_milliseconds(self):
        sc, _ = scenario_and_truth("hard")
        pipeline = Pipeline(sc, sc["seed"], timesync=True)
        for k in range(301):
            pipeline.step(round(k * 0.1, 6))
        errors = self.clock_error_ms(pipeline, 30.0)
        self.assertGreaterEqual(len(errors), 6)
        self.assertLess(max(errors), 12.0)
        self.assertGreater(max(abs(c.offset_s) for c in pipeline.observations.clocks.values()), 0.05)   # the error was real

    def test_the_distributed_mode_ignores_both(self):
        sc, _ = scenario_and_truth("medium")
        pipeline = Pipeline(sc, sc["seed"], distributed=True, clocks=True, timesync=True)
        self.assertIsNone(pipeline.sync)
        self.assertEqual(pipeline.observations.clocks, {})


class TestStoreForward(unittest.TestCase):
    """`storefwd`: nodes keep what they sent and resend it after an outage (pipeline/storefwd.py)."""

    def pipeline(self, **options):
        sc, _ = scenario_and_truth("outage", loss=0.1)
        sc["duration_s"] = 90
        return Pipeline(sc, sc["seed"], **options)

    def held(self, pipeline, node, until):
        sizes = {}
        for k in range(int(until * 10) + 1):
            t = round(k * 0.1, 6)
            pipeline.step(t)
            sizes[round(t)] = len(pipeline.storefwd.nodes[node].store)
        return sizes

    def test_it_is_off_unless_asked_and_unless_the_scenario_has_it(self):
        self.assertIsNone(self.pipeline().storefwd)
        sc, _ = scenario_and_truth("medium")
        self.assertIsNone(Pipeline(sc, sc["seed"], storefwd=True).storefwd)
        self.assertIsNone(self.pipeline(storefwd=True, distributed=True).storefwd)

    def test_a_node_cut_off_for_45_seconds_holds_its_messages_and_hands_them_over_afterwards(self):
        held = self.held(self.pipeline(storefwd=True, oosm=True), "F2", 85)
        self.assertGreater(held[64], 100)          # nothing was acknowledged since 20 s
        self.assertLess(held[80], 20)              # resent after the link came back, then acknowledged
        self.assertLess(held[10], 20)              # a healthy node keeps little

    def test_the_resent_readings_reach_the_tracker_only_when_it_can_replay_them(self):
        def used_after_outage(**options):
            p = self.pipeline(storefwd=True, **options)
            counts = [p.step(round(k * 0.1, 6)).readings_used for k in range(761)]
            return sum(counts[650:])             # the 11 s after the link came back
        self.assertGreater(used_after_outage(oosm=True), used_after_outage())


if __name__ == "__main__":
    unittest.main()
