"""Crossing diagnostics must expose misses, wrong labels and actual close identity changes."""

from scoring.challenge import diagnose
from scoring.metrics import Estimate
from scoring.test_scoring import moving, truth_of


def crossing_frames(label="hostile", swap=False, omit=False):
    frames = []
    for t in range(11):
        ids = ("B", "A") if swap and t >= 6 else ("A", "B")
        tracks = [Estimate(ids[0], t, t * 2, 0, 2, 0, label)]
        if not omit:
            tracks.append(Estimate(ids[1], t, 20 - t * 2, 2, -2, 0, label))
        frames.append((t, tracks))
    return frames


def crossing_truth():
    return truth_of(moving("H1", "hostile", 0, 0, 2, 0), moving("H2", "hostile", 20, 2, -2, 0))


def test_unclassified_crossing_can_track_well_but_fails_hostile_count():
    result = diagnose(crossing_truth(), crossing_frames("unknown"), warmup_s=0, sample_period_s=1)
    crossing = result["crossing"]
    assert crossing["closest_t_s"] == 5
    assert crossing["closest_distance_m"] == 2
    assert crossing["checks"]["identity_observed_without_swaps"]
    assert not crossing["checks"]["strict_hostile_count_correct_every_step"]
    assert result["whole_run"]["strict_hostile_detected_frac"] == 0


def test_zero_swaps_with_a_missed_target_is_not_identity_success():
    crossing = diagnose(crossing_truth(), crossing_frames(omit=True), warmup_s=0, sample_period_s=1)["crossing"]
    assert crossing["score"]["id_swaps"] == 0
    assert not crossing["checks"]["every_target_tracked_every_step"]
    assert not crossing["checks"]["identity_observed_without_swaps"]


def test_close_swap_is_exposed_without_continuity_discount():
    crossing = diagnose(crossing_truth(), crossing_frames(swap=True), warmup_s=0, sample_period_s=1)["crossing"]
    assert crossing["score"]["id_swaps"] == 2
    assert crossing["checks"]["strict_hostile_count_correct_every_step"]
    assert not crossing["checks"]["identity_observed_without_swaps"]


def test_hostile_ghosts_cannot_substitute_for_correctly_labelled_targets():
    frames = [(t, tracks + [Estimate("ghost1", t, 5000, 5000, cls="hostile"),
                            Estimate("ghost2", t, 6000, 6000, cls="hostile")])
              for t, tracks in crossing_frames("unknown")]
    crossing = diagnose(crossing_truth(), frames, warmup_s=0, sample_period_s=1)["crossing"]
    assert crossing["checks"]["strict_hostile_count_correct_every_step"]
    assert crossing["checks"]["every_target_tracked_every_step"]
    assert not crossing["checks"]["every_target_labelled_hostile_every_step"]


def test_single_snapshot_cannot_prove_identity_through_a_crossing():
    crossing = diagnose(crossing_truth(), [crossing_frames()[5]], warmup_s=0)["crossing"]
    assert not crossing["checks"]["complete_crossing_window"]
    assert not crossing["checks"]["identity_observed_without_swaps"]


def test_gapped_crossing_history_is_not_complete():
    frames = [(t, tracks) for t, tracks in crossing_frames() if t != 4]
    crossing = diagnose(crossing_truth(), frames, warmup_s=0, sample_period_s=1)["crossing"]
    assert not crossing["checks"]["complete_crossing_window"]
    assert not crossing["checks"]["identity_observed_without_swaps"]


def test_window_edges_need_not_coincide_with_sample_ticks():
    crossing = diagnose(crossing_truth(), crossing_frames(), warmup_s=0,
                        half_window_s=2.5, sample_period_s=1)["crossing"]
    assert crossing["expected_steps"] == 5
    assert crossing["checks"]["complete_crossing_window"]
    assert crossing["checks"]["identity_observed_without_swaps"]


def test_truth_snapshot_cannot_substitute_for_a_crossing_trajectory():
    truth = truth_of(moving("H1", "hostile", 0, 0, 2, 0, [5]),
                     moving("H2", "hostile", 20, 2, -2, 0, [5]))
    frames = [(t, tracks if t == 5 else []) for t, tracks in crossing_frames()]
    crossing = diagnose(truth, frames, warmup_s=0, sample_period_s=1)["crossing"]
    assert crossing["checks"]["complete_crossing_window"]
    assert crossing["score"]["strict_hostile_count_exact_frac"] == 1
    assert not crossing["checks"]["truth_targets_span_crossing"]
    assert not crossing["checks"]["identity_observed_without_swaps"]
