# Held-out evaluation of the `challenge` preset

Run once on the reserved test seeds, central Python pipeline, clear weather, no optional flags, 10 s warmup. **These numbers are lower than the tuning-seed numbers elsewhere in the repo**, and they say the challenge is not met. The thresholds at the end are a **proposal that nobody has approved**.

## What was run

`python -m scoring.challenge --preset challenge --set test --seeds 20 --losses 0,0.3,0.5,0.7,0.9` on test seeds 1000 to 1019 (100 runs). Nothing was tuned on them. The tracker changes made afterwards (friend-aware spawn rule, single-receiver RF identification) were measured on tuning seeds and then once each on fresh test seeds, 1020 to 1039 for the identification and 1040 to 1059 for the cueing rule. Test seeds 1000 to 1059 are therefore used up for `challenge`; any new held-out number needs seeds from 1060.

## Results (mean ± standard error over 20 seeds)

| Loss | Hostile tracked | Count exact | Position error (m) | ID swaps per run | False tracks per step | Friendlies flagged (of 5) |
|---|---|---|---|---|---|---|
| 0 % | 0.66±0.01 | 0.51±0.03 | 13.0±0.7 | 1.00±0.41 | 0.28 | 0.05 |
| 30 % | 0.66±0.01 | 0.57±0.02 | 12.7±0.8 | 1.15±0.39 | 0.18 | 0.10 |
| 50 % | 0.63±0.01 | 0.59±0.02 | 12.7±0.5 | 0.55±0.35 | 0.10 | 0.10 |
| 70 % | 0.60±0.02 | 0.54±0.02 | 12.7±0.9 | 0.85±0.36 | 0.11 | 0.05 |
| 90 % | 0.35±0.03 | 0.31±0.02 | 15.5±1.0 | 1.85±0.46 | 0.07 | 0.20 |

In the window of 3 s either side of the closest approach, a hostile is tracked 0.99 of the time at 0 % loss and 0.55 at 90 %, the position error is 3.5 m and 13.9 m, and between 2 and 6 of 20 runs have at least one ID swap at every loss level (3 of 20 at 0 %). Strict hostile detection, meaning tracks actually labelled `hostile`, is 0.17 at 0 % loss and 0.00 at 90 % (0.20 and 0.00 on seeds 1020 to 1039 after the identification change).

## What the numbers do not show

- The scorer counts a track as false when it is far from every true object. About 40 % of that time (6 tuning seeds) is the track of a hostile that has just left the scored square and lives on for 8 to 23 s ([tracker.md](../tracker/tracker.md#where-hostile-time-and-false-tracks-go-coverage-diagnosis-challenge-tuning-seeds-0--loss)); the rest is not explained. False tracks and count error are therefore pessimistic by an amount that has not been separated out.
- 27 % of hostile time is untracked: about 19 points are hostiles never yet acquired (12.6 only an RF receiver hears, 6.0 one camera or microphone bearing) and about 8 points are tracks lost within 15 s. A bearing alone cannot start a track.
- Every track that is not a confirmed friendly still counts as hostile; strict hostile labels come from evidence only for the RF-emitting hostiles.

## Proposed acceptance thresholds (not agreed)

Per seed, 0 to 50 % message loss, after a 10 s warmup, on seeds not used for tuning. Written from the challenge statement and the numbers above; they are a starting point for the team to change.

| Criterion | Proposed threshold | Held-out result at 0 % loss |
|---|---|---|
| Hostile count | exact in at least 90 % of samples | 0.51 |
| Hostile tracked | at least 85 % of the time | 0.66 |
| Identity through the crossing | no swap in the 6 s window in at least 95 % of seeds | 17 of 20 seeds |
| Position error | at most 10 m over the run and 5 m in the crossing window | 13.0 m and 3.5 m |
| Friendlies flagged | none, in every run | 0.05 of 5 on average |
| Degradation | at 90 % loss no friendly flagged and no more than a 50 % relative drop in tracked share | 0.20 flagged, tracked 0.35 |

By these thresholds only the crossing-window position error is met.
