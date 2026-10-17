"""Reproducible 03-Rai diagnostics, including a close-crossing window.

    python -m scoring.challenge --official --losses 0,0.5,0.9 --json out/challenge.json
    python -m scoring.challenge --set tuning --seeds 3 --distributed

This is an evaluator, not an estimator: only this scoring side reads truth. No tracker or
classifier parameters are changed. Results distinguish geometric tracking from actual hostile
labels and the older presumed-threat count. Numeric accuracy tolerances are not specified by
the challenge, so these diagnostics do not certify overall acceptance.
"""

import argparse
import copy
import json
import math
from dataclasses import asdict
from itertools import combinations
from pathlib import Path

from friend_foe.sweep import Setup, load_preset, make_scenario_and_truth, seeder_scenario
from pipeline.behaviour import automatic_estimator
from pipeline.run import scored_frames
from scoring.metrics import ScoreConfig, score
from scoring.truth import load_truth, present_at


def _metrics(measured):
    # Identification-range opportunity is computed by a separate sweep helper,
    # not by score(); do not export its unmeasured dataclass defaults as evidence.
    return {key: value for key, value in asdict(measured).items()
            if key not in ("ident_covered_frac", "ident_delay_s")}


def diagnose(truth, frames, warmup_s=10.0, half_window_s=3.0, sample_period_s=0.1):
    """Whole-run and +/- window scores at the sampled closest hostile approach.

    Association uses distance with NO continuity discount: a prior ID cannot hide a close swap.
    No-data/partial-coverage runs cannot pass the crossing identity check just by having zero swaps.
    """
    if not math.isfinite(half_window_s) or half_window_s <= 0 or not math.isfinite(sample_period_s) or sample_period_s <= 0:
        raise ValueError("crossing half-window and sample period must be finite and positive")
    frames = list(frames)
    objects = load_truth(truth)
    closest = None
    for t, _ in frames:
        if t < warmup_s:
            continue
        hostiles = [(o, s) for o, s in present_at(objects, t) if o.kind == "hostile"]
        for (a, sa), (b, sb) in combinations(hostiles, 2):
            distance = math.hypot(sa[0] - sb[0], sa[1] - sb[1])
            if closest is None or distance < closest[0]:
                closest = (distance, t, [a.id, b.id])
    config = ScoreConfig(warmup_s=warmup_s, continuity_m=0.0)
    result = {"whole_run": _metrics(score(truth, frames, config)), "crossing": None}
    if closest is None:
        return result
    distance, t, pair = closest
    window = [max(warmup_s, t - half_window_s), t + half_window_s]
    tolerance = sample_period_s * 1e-5
    crossing_frames = [(at, ests) for at, ests in frames if window[0] - tolerance <= at <= window[1] + tolerance]
    measured = score(truth, crossing_frames, config)
    fully_tracked = measured.hostile_samples > 0 and measured.hostile_samples == measured.matched_hostile_samples
    times = [at for at, _ in crossing_frames]
    # A sparse snapshot or truncated/gapped history cannot prove stable identity
    # through a crossing, even if all tracks in the supplied frames match perfectly.
    origin = frames[0][0]
    first_tick = math.ceil((window[0] - origin - tolerance) / sample_period_s)
    last_tick = math.floor((window[1] - origin + tolerance) / sample_period_s)
    expected_steps = last_tick - first_tick + 1
    complete = (len(times) > 1 and len(times) == expected_steps and times[0] <= window[0] + sample_period_s + tolerance
                and times[-1] >= window[1] - sample_period_s - tolerance and times[0] < t < times[-1]
                and all(abs(b - a - sample_period_s) <= tolerance for a, b in zip(times, times[1:])))
    truth_spans = all(any(objects[target].state_at(at) is not None for at in times if at < t)
                      and any(objects[target].state_at(at) is not None for at in times if at > t)
                      for target in pair)
    evaluable = complete and truth_spans
    result["crossing"] = {
        "pair": pair, "closest_t_s": t, "closest_distance_m": distance,
        "window_s": window, "sample_period_s": sample_period_s, "expected_steps": expected_steps,
        "score": _metrics(measured),
        "checks": {
            "complete_crossing_window": complete,
            "truth_targets_span_crossing": truth_spans,
            "strict_hostile_count_correct_every_step": evaluable and measured.strict_hostile_count_exact_frac == 1.0,
            "every_target_tracked_every_step": evaluable and fully_tracked,
            "every_target_labelled_hostile_every_step": evaluable and fully_tracked and measured.strict_hostile_detected_frac == 1.0,
            "identity_observed_without_swaps": evaluable and fully_tracked and measured.id_swaps == 0,
            "no_friendly_labelled_hostile": measured.strict_friendlies_flagged == 0,
            "no_friendly_in_presumed_threat_count": measured.friendlies_flagged == 0,
        },
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--preset", default="challenge")
    parser.add_argument("--official", action="store_true", help="use the preset's saved seed instead of a sweep seed")
    parser.add_argument("--set", dest="seed_set", default="tuning", choices=sorted(seeder_scenario.SEED_SETS))
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--losses", default="0,0.5,0.9")
    parser.add_argument("--weather", default="clear")
    parser.add_argument("--behaviour", choices=["none", "safe", "raw"], default="none")
    parser.add_argument("--distributed", action="store_true")
    parser.add_argument("--trust", action="store_true")
    parser.add_argument("--oosm", action="store_true")
    parser.add_argument("--half-window", type=float, default=3.0)
    parser.add_argument("--json", dest="json_path")
    args = parser.parse_args()
    try:
        losses = [float(value) for value in args.losses.split(",")]
        if not losses or any(not 0 <= loss <= 1 for loss in losses):
            raise ValueError("losses must be between 0 and 1")
        if args.seeds < 1 or not math.isfinite(args.half_window) or args.half_window <= 0:
            raise ValueError("seeds and half-window must be positive")
        if args.distributed and (args.trust or args.oosm):
            raise ValueError("trust and OOSM are central-only; do not report them as active with distributed")
    except ValueError as error:
        parser.error(str(error))
    preset = load_preset(args.preset)
    setup = Setup(preset, args.seed_set, args.seeds)
    runs = []
    for loss in losses:
        for index in range(1 if args.official else args.seeds):
            if args.official:
                config = copy.deepcopy(preset)
                net = config.setdefault("degradations", {}).setdefault("network", {})
                net.update(enabled=True, loss=loss, burst=False)
                scenario, truth = seeder_scenario.generate(config)
                scenario["environment"]["weather"] = args.weather
            else:
                scenario, truth = make_scenario_and_truth(setup, index, args.weather, loss, False)
            estimator = automatic_estimator(scenario, motion_peaceful=args.behaviour == "raw") if args.behaviour != "none" else None
            frames = scored_frames(scenario, scenario["seed"], estimator=estimator, distributed=args.distributed,
                                   trust=args.trust, oosm=args.oosm)
            runs.append({"seed": scenario["seed"], "loss": loss,
                         **diagnose(truth, frames, half_window_s=args.half_window)})
    report = {
        "preset": args.preset, "seed_set": "preset" if args.official else args.seed_set,
        "options": {"distributed": args.distributed, "trust": args.trust, "oosm": args.oosm,
                    "behaviour": args.behaviour, "weather": args.weather},
        "scoring": {"warmup_s": 10, "gate_m": 50, "continuity_m": 0,
                    "strict_hostile_count": "class == hostile", "legacy_count": "class not in friendly, peaceful",
                    "accuracy_acceptance_tolerances": "not supplied by challenge"},
        "runs": runs,
    }
    output = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.json_path:
        path = Path(args.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output, encoding="utf-8")
        print(f"Wrote {len(runs)} diagnostic runs to {path}")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
