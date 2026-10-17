# pipeline

The whole chain on one scenario: sensors, lossy network, tracker, friend/foe, scoring.

Status: done and tested for the central baseline. See [tracker](../tracker/tracker.md), [sensors](../sensors/sensors.md), [scoring](../scoring/scoring.md).

| File | Contents |
|------|----------|
| [run.py](run.py) | `Pipeline(scenario, seed).step(t)`, `run(scenario, seed)` (frames of confirmed tracks), `scored_frames(scenario, seed)` (the tracks with the estimator's classes, ready for `scoring.metrics.score`) |
| [sweep.py](sweep.py) | `python -m pipeline.sweep --set test --seeds 20 [--weather fog+wind] [--birds 2 --vehicles 2] [--csv file]`: the metrics over message loss |
| `test_run.py` | End-to-end tests |

```
sensors/observe.py + sensors/beacons.py    what the nodes sense and send (needs the true positions)
common/channel.py                          loss, burst, delay from the scenario's degradations
tracker/ (+ PoseBook)                      one central tracker on what the channel delivered
friend_foe/                                classification from tracks and delivered beacons, every 0.5 s
scoring/                                   metrics against truth.json
```

Everything before the channel is the simulation side and may use the truth; the tracker and the estimator see only delivered messages. The clock is 0.1 s. Not modelled: jamming zones, node dropout, topology (see [common/channel.py](../common/channel.py)). Weather reaches the sensors per detection through the weather provider; it does not yet change the tracker.

Results: [tracker.md](../tracker/tracker.md#results).

## Investigation: sending a drone at a suspicious track

`python -m pipeline.sweep --investigate` closes the loop. Files: [fleet.py](fleet.py) (the friendly drones in motion: patrol loop, or a commanded flight within the catalog's assumed speed and acceleration limits, then back to the patrol), [dispatch.py](dispatch.py) (`Investigator` = the existing `InvestigationTrigger` plus a `Dispatcher`: the closest free drone with a module the request calls feasible flies to the request's standoff, never under 40 m, faces the track, stays 6 s, returns; at most 2 at a time; a track gone for 10 s aborts it; statuses go back to the trigger).

It is a **stand-in** for the drone-behaviour module's dispatch (the viewer has the full one in `ui/viewer/investigations.js`), and it does not identify anything: the estimator does not read camera class hints, so this measures only what the extra viewpoint does to tracking. Because a commanded drone leaves the scripted patrol in `truth.json`, the run records each drone's real trajectory and scoring uses it (`scoring.truth.with_recorded_samples`; before that fix the friendlies looked flagged only because they were scored against positions they were no longer at).

Test seeds, `medium` preset, clear weather, no behaviour module, 20 seeds:

| Message loss | Investigation | Hostile tracked | Count error | False tracks per step | Friendlies flagged (of 5) | ID swaps |
|--------------|---------------|-----------------|-------------|-----------------------|---------------------------|----------|
| 0 % | off | 57 % | 1.59 | 1.28 | 0.05 | 5.6 |
| 0 % | on | 59 % | 2.17 | 1.93 | 0.45 | 6.6 |
| 50 % | off | 52 % | 1.24 | 0.58 | 0.2 | 4.5 |
| 50 % | on | 56 % | 1.45 | 0.88 | 0.55 | 5.8 |
| 90 % | off | 23 % | 1.35 | 0.11 | 4.65 | 2.8 |
| 90 % | on | 22 % | 1.40 | 0.12 | 4.65 | 2.2 |

What it shows, honestly:
- **The effect is small and mixed.** Hostiles are tracked 2 to 4 points more at 0 and 50 % loss, and nothing at 90 %. Count error, false tracks and flagged friendlies get worse.
- **Where the drone does arrive it helps:** on 25 tuning seeds there were 11 on-station visits at a real hostile (74 seconds); that hostile was tracked 95 % of those seconds against 77 % in the same seconds of the run without the drone. A small sample.
- **Few visits happen and many are wasted.** About 7 dispatches per run, 4 reach their station; of 37 dispatches over 5 tuning runs, 17 went to a real hostile, 16 to a ghost track and 4 to a friendly. A drone that is not on patrol is also not covering the area, and a maneuvering drone's pose (taken from its beacons at 2 Hz) is less exact, which probably explains the extra false tracks and flagged friendlies (not checked).
- A hostile flies 7 to 13 m/s and the drones 14 to 18 m/s, so catching one takes time.

So the loop works end to end, but the stand-in dispatch does not yet pay for itself. What would help: fewer ghost tracks (the tracker), not sending drones at tracks that are probably friendlies or ghosts, and sending the drone where the hostile will be rather than where it is.

## With the automatic behaviour module

`python -m pipeline.sweep --behaviour` puts `drone_behavior/` (`AutomaticEstimator`) behind the estimator. Test seeds 1000 to 1009, `medium` preset, 15 % message loss, clear weather:

| Clutter | Behaviour module | Count error | Clutter flagged | Hostile tracked | Friendlies flagged |
|---------|------------------|-------------|-----------------|-----------------|--------------------|
| none | off | 1.49 | 0 | 56 % | 0.2 |
| none | on | 1.49 | 0 | 56 % | 0.2 |
| 2 birds + 2 vehicles | off | 2.60 | 38 % | 53 % | 0.2 |
| 2 birds + 2 vehicles | on | 2.60 | 38 % | 53 % | 0.2 |

Identical: the module calls some tracks hostile (hostile is counted like suspicious here) but never calls anything peaceful on these tracks, because its peaceful evidence needs a clear authorized-corridor transit and its motion cues stay below the thresholds ("consistent transit" and "ambiguous motion" in `explain`). This agrees with its own documentation, which claims no bird or vehicle recognition. The oracle test in [friend_foe.md](../friend_foe/friend_foe.md) shows the hook could remove the wasted dispatches given better evidence.
