# health module

Per-node link health and per-message trust (seeder task 10, phase 2). See [seeder-plan.md](../docs/seeder-plan.md) section 10 for the plan and the viewer's version of the states in [storefwd.js](../ui/viewer/storefwd.js).

Status: **done**: the Python reference, tested and wired into the pipeline (`--trust`, off by default), the JavaScript port [ui/viewer/health.js](../ui/viewer/health.js) (not wired into the viewer's simulation, which keeps its own health table), and a calibration of the link model against the Python channel. The JS port is checked against the shared cases by [test-health.js](../ui/viewer/test-health.js): all 7 pass (`node ui/viewer/test-health.js`).

## What exists

| File | Contents |
|------|----------|
| [link.py](link.py) | `LinkHealth`: one node's link from the sequence numbers and arrival times of its messages. Bayesian layer (two-state good or bursty link, filtered message by message: `p_bad`), frequentist layer (loss rate over the last 40 outcomes with a Wilson interval, and a CUSUM change test), and the state `ok`, `degraded`, `offline`, `presumed_dead`. Plain Python with no repository imports, for a line-by-line JS port |
| [monitor.py](monitor.py) | `HealthMonitor`: `observe(message, t)` for every delivered message, then `state`, `trust(node, t, age)`, `explains_silence(node, t)`, `is_late(age)`, `snapshot(t)` |
| [trust.py](trust.py) | `weighted(reading, trust)`: a reading's sigmas divided by the square root of the trust; trust 0 drops it |
| [../ui/viewer/health.js](../ui/viewer/health.js), [test-health.js](../ui/viewer/test-health.js) | The JavaScript port, and the test that runs every shared case through it |
| [golden.py](golden.py), [testdata/health_cases.json](testdata/health_cases.json) | Shared cases for the JS port: message streams (clean, bursty, steady loss, outage then resume, one node dies) with the expected state, `p_bad`, loss rate, CUSUM, trust and explained silence at set times, plus Wilson intervals. Generated: `python -m health.golden`; `test_golden.py` fails if the file and the code disagree |
| `test_health.py`, `test_golden.py` | Tests |

## How it works

- **Evidence.** Every message a node sends has `seq`, counting all its messages from 1, so a jump in the numbers is messages lost and a long silence is a link that is down. A duplicate or resent number says nothing new.
- **States.** `degraded` at 30 % of the recent numbers missing (or the Bayesian layer above 0.5, or the CUSUM alarm), `ok` again below 20 %; `offline` after 4 s of silence; `presumed_dead` after 15 s (a dead node and a jammed one look the same from C2). Same thresholds as the viewer.
- **CUSUM.** Tests a jump of the loss rate from 10 % to 50 %. With the alarm threshold `ln(200)` a false alarm is expected no more often than once in about 200 messages (Lorden's bound).
- **Trust** of a message = the health factor of its node's state (ok 1, degraded 0.5, offline 0.2, presumed dead 0) times `0.5 ** (age / 10 s)`.
- **Used in two places.** (1) The tracker is unchanged, but each reading's noise is scaled by `1 / trust`, and a reading more than 3 s old is left out of the live picture. (2) The friend/foe estimator ([estimator.py](../friend_foe/estimator.py), `silence_explained`): when a track was matched to a friendly's beacon, that drone's own link decides how much a missing beacon counts. Offline: not at all; presumed dead: half; before this, silence only depended on the average delivery rate of all friendlies.
- Assumptions, all in `HealthConfig`: a 40-outcome window and the thresholds above are assumed; the link model's four numbers are fitted to the Python channel (next section). None is verified against a real link.

## Calibration against the Python channel

The first numbers (loss 5 % and 60 %, staying chances 0.98 and 0.90) were guesses, and as a predictor of the next message's loss they scored worse than a constant at 60 % loss (Brier 0.243 against 0.240). The channel's bursty state loses every message and its mean burst is 5 messages (`common/channel.py`), so the model was refitted by the Brier score of the predicted next-message loss on that chain (loss 10 %, 30 %, 60 %): good-state loss 0.02, bursty loss 0.95, staying chances 0.97 and 0.80 give 0.041, 0.110 and 0.209 (constant guess: 0.090, 0.210, 0.240; the old numbers: 0.057, 0.147, 0.243). These are the defaults now. **This is a fit to our own simulated channel, so it says the model matches that channel, not a real link.** The results below were re-measured with the fitted numbers and did not change.

## Result (`outage` preset, 8 seeds with the preset's own faults, 10 s warmup, tuning seeds; `python -m pipeline.sweep --trust`)

F2's link cut 30 to 60 s, GS2 delayed 4 s from 70 to 85 s, F4 dead from 100 s. Trust off: hostile tracked 0.56, friendlies flagged 1.62 of 5, false tracks 0.88, count error 1.34, OSPA 68.3 m, ID swaps 3.5. Change with trust on, and the ablation (paired differences with standard errors):

| Variant | Hostile tracked | Friendlies flagged | False tracks | Count error | OSPA | ID swaps |
|---------|-----------------|--------------------|--------------|-------------|------|----------|
| Both parts, both layers | -0.05±0.03 | **-1.38±0.18** | **-0.72±0.11** | -0.11±0.19 | -7.0±4.3 m | **-1.5±0.7** |
| Silence part only | 0.00±0.00 | -1.25±0.16 | -0.08±0.02 | 0.00 | -1.5±0.8 m | 0 |
| Reading weight and late rule only | -0.05±0.03 | 0.00±0.19 | -0.63±0.10 | -0.12±0.18 | -4.8±3.9 m | -1.5±0.7 |
| Bayesian layer only | -0.06±0.03 | -1.38±0.18 | -0.64±0.10 | -0.18±0.20 | -6.6±4.3 m | -1.4±0.4 |
| Frequentist layer only | -0.05±0.03 | -1.38±0.18 | -0.72±0.10 | -0.11±0.19 | -7.0±4.3 m | -1.5±0.7 |

Reading it: the **silence part** is what removes the flagged friendlies (1.62 to 0.24 of 5) and costs no hostiles; the **reading weight and late rule** is what removes the ghost tracks and ID swaps, but costs 5 points of hostiles, because a delayed reading is dropped instead of being used at its own time (the tracker uses readings at their arrival time, so it cannot use a late one). The **two layers give the same result** here: during these faults the states come from silence, which both share, so the ablation cannot tell them apart; it would take a scenario with steady partial loss. **With no faults** (`medium` preset, 10 tuning seeds, trust on minus off): hostile tracked -0.01±0.00 at 0 % and 30 % loss, -0.00±0.00 at 50 %, -0.02±0.01 at 70 %; false tracks -0.07±0.05, -0.07±0.04, -0.09±0.03, -0.03±0.01; ID swaps -0.6, -0.6, -1.0, -0.3; friendlies flagged 0 (-0.10±0.10 at 70 %). So switching it on costs almost nothing when nothing is wrong and helps a little. Not measured: the test seeds, other presets.

## Honest gaps

- **`--trust` does not help at very high loss.** At 90 and 95 % loss (`challenge` preset, 6 tuning seeds) friendlies flagged are 4.0 and 5.0 of 5 with or without trust (difference 0.00±0.00): the links are degraded, not silent, so the silence rule does not apply, and a friendly's beacon track is lost between the rare beacons. Not solved.

- **The layers are not separated by any of these runs.** The Bayesian and frequentist layers give the same results: in the outage faults the state comes from silence, which they share. A scenario with steady partial loss, where `degraded` matters, would show a difference; not built.
- **Calibration is to our own channel** (see above), not to a real link.
- **The identity is held only while the node is offline.** After 15 s (presumed dead) half the silence counts again, so a drone that stays unheard for a long time fades to `unknown`. A hostile could also inherit a friendly's identity if its track jumps; only the tracker's association keeps that apart, and this was not tested against a deliberate case.
- **The 5 points of hostiles are not from dropping late readings.** Orlin's idea was to apply a late reading to the track as it was when the reading was taken (retrodict, update, carry forward). Built and measured once on the `outage` preset (6 seeds, change from the baseline): applying late readings at their own time, without trust, gave hostile tracked -0.07±0.02, so it does not recover the points (it is a little worse), though false tracks -0.36±0.09 and count error -0.35±0.11 improved; with trust on top, hostile -0.06±0.01, friendlies flagged -1.17±0.31, false tracks -0.61±0.16. The code was removed again because it did not do what it was for. The cause of the 5 points is unknown; the cut-off nodes' own readings are lost either way, so part of it may simply be missing data.
- **Held identity is guarded.** A friendly's identity is held through an explained silence only while its track stays within 30 m plus 6 m/s of where its last beacon put the drone (at most 120 m): a track that jumps away holds nothing (`friend_foe/estimator.py`, `HOLD_*`; the safety test is `test_a_track_that_jumps_away_from_where_its_beacon_put_it_holds_no_identity`). Adding a velocity test as well cost a third of the benefit, because a patrolling drone turns during a long outage. Measured on `outage`: friendlies flagged -1.38±0.18, the same as without the guard.
- **The JS port is not used by the viewer yet.** `sim.js` and `storefwd.js` keep their own health states; switching them to `health.js` is Orlin's call, and its states and thresholds are the same.