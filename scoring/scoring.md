# scoring module

Metrics harness: count error, position/velocity error, ID swaps, friendly false alarms, degradation vs message loss.

Status: scoring of one run is done and tested (hand-made cases and one seeder run through the friend/foe test adapter). Not done: sweeps over message loss for the whole pipeline (needs the real tracker), and a reader for the viewer's `result` JSON. See [system design](../docs/system-design.md).

## What exists

| File | Contents |
|------|----------|
| [metrics.py](metrics.py) | `score(truth, frames, config)` returns a `RunScore`; `Estimate` is one track at one time step |
| [truth.py](truth.py) | Reads `truth.json` (`edth.truth/2`); only the scoring module may. Interpolates between samples; an object outside the area has no state |
| [common/assignment.py](../common/assignment.py) | Optimal one-to-one assignment (Hungarian) with a distance gate, pure Python; shared with the tracker |
| [tracks.py](tracks.py) | `frames_from_local_tracks` (the `local_track` messages in [data-formats.md](../docs/data-formats.md)) and `frames_from_estimator` (the friend/foe test adapter) |
| [run.py](run.py) | `python -m scoring.run truth.json tracks.jsonl [--gate 50] [--warmup 10]` |
| [sweep.py](sweep.py) | `python -m scoring.sweep --set test --seeds 20 [--birds N --vehicles N] [--csv file]`: the friend/foe estimator on generated scenarios over beacon loss, scored with these metrics |
| [identification.py](identification.py) | `identification(truth, ranges, warmup_s)`: how well the friendly drones are placed to identify the hostiles. `ident_covered_frac` is the share of hostile-present steps with a friendly drone within its best module's identification range (the catalog's `sim.ident_range_m`, assumed, clear weather); `ident_delay_s` is, per hostile, the time from first present to the first step a drone is in range (never covered counts as the whole time present), averaged. The pipeline's observations carry no class cues, so identification itself is not simulated; this measures what a hand-off to the closest drone is for. Only drones count; the fixed ground sensors are not included |
| `test_scoring.py`, `test_identification.py` | Tests |

## How a step is scored

1. Estimated tracks are matched to the true objects present (hostile, friendly, non-allied benign **and** clutter) by optimal assignment inside a gate (`gate_m`, default 50 m). Matching all kinds means a track on a friendly, benign drone or bird is never taken for a true hostile.
2. A track **counts as hostile** unless its class is `friendly` or `peaceful`. A track with no class, or `unknown`, counts: a hostile presumption (change `NOT_HOSTILE_CLASSES` in [metrics.py](metrics.py) to treat `unknown` differently).
3. Metrics are averaged over the steps scored (`warmup_s` skips the start).

| Metric | Definition |
|--------|-----------|
| `count_error_mean_abs`, `count_error_bias` | counted tracks minus true hostiles present, as mean absolute value and as signed mean (positive = too many). Tracks on friendlies and clutter count here, because the operator sees them as hostiles |
| `pos_rmse_m`, `vel_rmse_mps`, `heading_rmse_deg` | matched hostile tracks only; heading only when both speeds are above 1 m/s |
| `ospa_m` | OSPA between true hostiles and counted tracks, cutoff 100 m, order 2. A missed or extra track costs the cutoff |
| `id_swaps` | times a hostile object's matched track id differs from the one it had at its last matched step (the standard ID switch; a gap with no match does not count unless the id changed) |
| `hostile_detected_frac` | share of hostile object-steps matched to a counted track |
| `friendlies_flagged`, `friendly_flag_frac` | friendlies matched to a counted track at least once, and the share of friendly object-steps |
| `clutter_flagged_frac` | share of clutter object-steps matched to a counted track: a bird or vehicle called hostile is a false alarm, not a missed hostile |
| `benign_flag_frac` | share of non-allied benign drone object-steps matched to a counted track; separate from friendly identity and clutter |
| `false_tracks_mean` | counted tracks matching no object, per step |

## Results (friend/foe test adapter, `medium` preset, 20 test seeds, clear weather, 10 s warmup)

`python -m scoring.sweep --set test --seeds 20`. The tracks are the adapter's clean ones with the right ids, so position error (5 m) and ID swaps (0) only show the scoring works; the classification effects are the point.

| Beacon loss | Count error (abs) | OSPA | Friendlies flagged (of 5) | Friendly time flagged |
|-------------|-------------------|------|---------------------------|-----------------------|
| 0 to 50 % | 0.01 | 5.1 m | 0 | 0 % |
| 70 % | 0.02 | 5.7 m | 0.45 | 0 % |
| 90 % | 0.83 | 24 m | 4.25 | 17 % |

With 2 birds and 2 vehicles and no behaviour module the count error is 3.0 at every loss and OSPA is 71 m: all four clutter objects are counted as hostiles. The behaviour module is what removes that, as [friend_foe.md](../friend_foe/friend_foe.md) shows for drone dispatches. The 90 % row is worse than `friend_foe` reports (1.9 flagged) for one reason, checked by rerunning with `unknown` excluded (it then gives 1.85): scoring counts the class `unknown` as hostile (a friendly whose beacons fade drops to `unknown`), while `friend_foe` flags only `suspicious` and `hostile`.

## Assumptions

The gate, the continuity bonus, the OSPA cutoff and the 1 m/s heading threshold are my choices, not from a requirements document. The matching is per step, as in [system-design.md](../docs/system-design.md) section 5.9, with one addition: keeping the pair an object had at the last step is worth `continuity_m` (10 m). Without it two objects passing within the position noise trade tracks, and the clean adapter tracks showed 1.1 false ID swaps per run. The price: a real swap between two tracks closer than about 10 m is not seen. `frames_from_estimator` uses the friend/foe test adapter, whose tracks are cleaner than a real tracker's, so numbers from it only show that the scoring works.
