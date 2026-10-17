# health module

Per-node link health and per-message trust (seeder task 10, phase 2). See [seeder-plan.md](../docs/seeder-plan.md) section 10 for the plan and the viewer's version of the states in [storefwd.js](../ui/viewer/storefwd.js).

Status: the **Python reference is done and tested**, wired into the pipeline (`--trust`, off by default). Not done: the JavaScript port (the shared cases are ready for it, see below) and a calibration of `p_bad` against this channel.

## What exists

| File | Contents |
|------|----------|
| [link.py](link.py) | `LinkHealth`: one node's link from the sequence numbers and arrival times of its messages. Bayesian layer (two-state good or bursty link, filtered message by message: `p_bad`), frequentist layer (loss rate over the last 40 outcomes with a Wilson interval, and a CUSUM change test), and the state `ok`, `degraded`, `offline`, `presumed_dead`. Plain Python with no repository imports, for a line-by-line JS port |
| [monitor.py](monitor.py) | `HealthMonitor`: `observe(message, t)` for every delivered message, then `state`, `trust(node, t, age)`, `explains_silence(node, t)`, `is_late(age)`, `snapshot(t)` |
| [trust.py](trust.py) | `weighted(reading, trust)`: a reading's sigmas divided by the square root of the trust; trust 0 drops it |
| [golden.py](golden.py), [testdata/health_cases.json](testdata/health_cases.json) | Shared cases for the JS port: message streams (clean, bursty, steady loss, outage then resume, one node dies) with the expected state, `p_bad`, loss rate, CUSUM, trust and explained silence at set times, plus Wilson intervals. Generated: `python -m health.golden`; `test_golden.py` fails if the file and the code disagree |
| `test_health.py`, `test_golden.py` | Tests |

## How it works

- **Evidence.** Every message a node sends has `seq`, counting all its messages from 1, so a jump in the numbers is messages lost and a long silence is a link that is down. A duplicate or resent number says nothing new.
- **States.** `degraded` at 30 % of the recent numbers missing (or the Bayesian layer above 0.5, or the CUSUM alarm), `ok` again below 20 %; `offline` after 4 s of silence; `presumed_dead` after 15 s (a dead node and a jammed one look the same from C2). Same thresholds as the viewer.
- **CUSUM.** Tests a jump of the loss rate from 10 % to 50 %. With the alarm threshold `ln(200)` a false alarm is expected no more often than once in about 200 messages (Lorden's bound).
- **Trust** of a message = the health factor of its node's state (ok 1, degraded 0.5, offline 0.2, presumed dead 0) times `0.5 ** (age / 10 s)`.
- **Used in two places.** (1) The tracker is unchanged, but each reading's noise is scaled by `1 / trust`, and a reading more than 3 s old is left out of the live picture. (2) The friend/foe estimator ([estimator.py](../friend_foe/estimator.py), `silence_explained`): when a track was matched to a friendly's beacon, that drone's own link decides how much a missing beacon counts. Offline: not at all; presumed dead: half; before this, silence only depended on the average delivery rate of all friendlies.
- Assumptions, all in `HealthConfig`: loss 5 % in the good state and 60 % in the bursty one, staying chances 0.98 and 0.90, a 40-outcome window, the thresholds above. None is verified.

## Result (`outage` preset, 8 seeds with the preset's own faults, 10 s warmup, tuning seeds; `python -m pipeline.sweep --trust`)

F2's link cut 30 to 60 s, GS2 delayed 4 s from 70 to 85 s, F4 dead from 100 s. Trust off: hostile tracked 0.56, friendlies flagged 1.62 of 5, false tracks 0.88, count error 1.34, OSPA 68.3 m, ID swaps 3.5. Change with trust on, and the ablation (paired differences with standard errors):

| Variant | Hostile tracked | Friendlies flagged | False tracks | Count error | OSPA | ID swaps |
|---------|-----------------|--------------------|--------------|-------------|------|----------|
| Both parts, both layers | -0.05±0.03 | **-1.38±0.18** | **-0.72±0.11** | -0.11±0.19 | -7.0±4.3 m | **-1.5±0.7** |
| Silence part only | 0.00±0.00 | -1.25±0.16 | -0.08±0.02 | 0.00 | -1.5±0.8 m | 0 |
| Reading weight and late rule only | -0.05±0.03 | 0.00±0.19 | -0.63±0.10 | -0.12±0.18 | -4.8±3.9 m | -1.5±0.7 |
| Bayesian layer only | -0.06±0.03 | -1.38±0.18 | -0.64±0.10 | -0.18±0.20 | -6.6±4.3 m | -1.4±0.4 |
| Frequentist layer only | -0.05±0.03 | -1.38±0.18 | -0.72±0.10 | -0.11±0.19 | -7.0±4.3 m | -1.5±0.7 |

Reading it: the **silence part** is what removes the flagged friendlies (1.62 to 0.24 of 5) and costs no hostiles; the **reading weight and late rule** is what removes the ghost tracks and ID swaps, but costs 5 points of hostiles, because a delayed reading is dropped instead of being used at its own time (the tracker uses readings at their arrival time, so it cannot use a late one). The **two layers give the same result** here: during these faults the states come from silence, which both share, so the ablation cannot tell them apart; it would take a scenario with steady partial loss. Not measured: other presets and loss levels with trust on, the test seeds.

## Honest gaps

- **Calibration.** `p_bad` is not calibrated against this channel. The channel's bursty state loses every message, while the model assumes 60 %; a quick check with the channel's true state is not meaningful for arrived messages (all of them are in the good state). Setting `loss_bad` near 0.95 is the obvious next step.
- **The identity is held only while the node is offline.** After 15 s (presumed dead) half the silence counts again, so a drone that stays unheard for a long time fades to `unknown`. A hostile could also inherit a friendly's identity if its track jumps; only the tracker's association keeps that apart, and this was not tested against a deliberate case.
- **Late readings are dropped, not used** (see above).
- **JS port** not written: the file of shared cases is its test.
