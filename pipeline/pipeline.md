# pipeline

The whole chain on one scenario: sensors, lossy network, tracker, friend/foe, scoring.

Status: done and tested for the central baseline. See [tracker](../tracker/tracker.md), [sensors](../sensors/sensors.md), [scoring](../scoring/scoring.md).

| File | Contents |
|------|----------|
| [run.py](run.py) | `Pipeline(scenario, seed).step(t)`, `run(scenario, seed)` (frames of confirmed tracks), `scored_frames(scenario, seed)` (the tracks with the estimator's classes, ready for `scoring.metrics.score`) |
| [sweep.py](sweep.py) | `python -m pipeline.sweep --set test --seeds 20 [--weather fog+wind] [--birds 2 --vehicles 2] [--csv file]`: the metrics over message loss |
| [nodes.py](nodes.py) | `NodeTrackers`: the distributed mode, a tracker per node on its own readings that shares `local_track` messages; the merger is in [fusion/](../fusion/fusion.md). Switch it on with `--distributed` |
| `test_run.py` | End-to-end tests |

## Cueing: hand what a node sees to the drone best placed to identify it

[cueing.py](cueing.py): the moment a node sees something that is not a friend, the data it recorded goes to the closest free drone, **the one that saw it included**, which flies to 80 m from it. Two kinds of sighting: (1) a new confirmed non-friend track at least 2 s old with a position error under 40 m (its position is known, so the drone follows the track like in any investigation), and (2) repeated bearings (3 within 2 s, within 8 degrees) that no confirmed track or friend lies along: a target seen by one node with a bearing, which never gets a track. For (2) a point 150 m out along the bearing stands in for the position, a guess. This does not wait for the estimator to call a track suspicious, which takes several seconds of beacon silence. The ground sensors are fixed and the simulation has no pointing command for them, so they help only through their own readings, which cross the cue anyway. Switch on with `--cue`; compare with `--paired cueing --investigate`.

**The tracking metrics cannot show the benefit**, because nothing in the pipeline identifies: observations carry no class cues. So [scoring/identification.py](../scoring/identification.py) measures what a hand-off is for: the share of hostile-present time with a friendly drone within its best module's identification range (`ident_range_m`, assumed, clear weather) of the hostile, and the time from a hostile first being present to the first drone in range.

**Result** (15 tuning seeds, `medium`, clear, mean difference with standard error):

| Comparison | Loss | Drone in ident range, share of time | Time to first drone in range |
|------------|------|--------------------------------------|------------------------------|
| cueing on minus off (both investigating) | 0 % | 0.00±0.02 | -4.4±2.0 s |
| | 30 % | -0.01±0.03 | -5.7±2.5 s |
| investigation on minus off (no cueing) | 0 % | +0.07±0.02 | -4.5±2.4 s |
| | 30 % | +0.07±0.02 | -4.1±2.3 s |

The time to the first drone in range is about 28 s with investigation and no cueing, so cueing takes roughly 4 to 6 s off it (about 2 standard errors) but does not raise the share of time a drone is in range (stays near 23 %). Tracking metrics are unchanged within noise: hostile tracked +0.03±0.01, ID swaps +0.2±0.7, false tracks -0.05±0.15 at 0 % loss. Not measured: ground sensors being pointed, identification itself (a drone in range is taken to identify), weather on the identification range. Tuning seeds, 15 runs; the test seeds have not been used.
## The behaviour module on the pipeline's tracks, and merging it with the hand-off

[behaviour.py](behaviour.py) runs `drone_behavior/` (Emkata) the way the pipeline needs. **Raw**, the module hurts here: on 10 tuning seeds, `medium`, 15 % loss, 2 birds and 2 vehicles, switching it on cost 28 points of hostiles counted (0.60 to 0.32) for 7 points fewer clutter flagged, and 34 to 47 % of the real hostile tracks became `peaceful` (none `hostile`). A hostile that flies a steady straight path looks like safe transit, and pursuit evidence cannot appear because the Python scenarios' hostiles do not react (only the viewer's JavaScript simulation has actors that do). **Safe mode** (the default, `--behaviour` or `--behaviour safe`) sets the estimator's `peaceful_min_updates` out of reach, so motion alone never makes a track `peaceful`; `--behaviour raw` is the module's own behaviour. Nothing in `drone_behavior/` was changed for this, so the viewer's JavaScript port stays in step.

The cueing of this module's classes: tracks classed `friendly` or `peaceful` get no drone, and when there are more cues than free drones the likeliest hostile (highest `p_hostile`) goes first (`Investigator._by_risk`).

**Result** (10 tuning seeds, `medium`, 15 % loss, 2 birds, 2 vehicles, mean difference from the baseline with standard error; baseline: hostile tracked 0.60, clutter flagged 0.34, false tracks 0.94, count error 1.86, OSPA 77.8 m, time to first drone in range 34 s):

| Variant | Hostile tracked | Clutter flagged | False tracks | Count error | OSPA | Drone in range | Time to drone |
|---------|-----------------|-----------------|--------------|-------------|------|----------------|---------------|
| Emkata raw | -0.28±0.02 | -0.07±0.02 | -0.13±0.03 | -0.55±0.13 | +6.3±1.2 m | 0 | 0 |
| Emkata safe | 0.00±0.00 | 0.00±0.00 | 0.00±0.00 | 0.00±0.00 | 0.0 | 0 | 0 |
| Hand-off only (`--investigate --cue`) | +0.03±0.02 | +0.02±0.02 | +0.05±0.14 | +0.34±0.11 | -0.2±1.5 m | +0.09±0.02 | -9.6±3.1 s |
| Merged (safe + hand-off) | +0.03±0.02 | +0.04±0.02 | +0.14±0.16 | +0.50±0.14 | +0.3±1.6 m | +0.08±0.02 | -9.6±3.1 s |

Reading it: in safe mode the behaviour module changes nothing on these tracks (identical to the baseline), because with real tracks and non-reacting hostiles it finds neither pursuit nor, once peaceful is off, anything else to say; its friendly identity from beacons was already right. The merge therefore adds nothing over the hand-off alone (the identification gain is the same; the count error is a little worse, within noise). The behaviour module's value is in the viewer's simulation with pursuing actors, which this Python pipeline cannot test.

Speed: the module is about 4 times slower than the plain estimator (36 s against 9 s for 8 runs). `encounters.assess` is most of it. Two exact optimisations were made (a C binary search in `at`, and the ally's manoeuvres computed once per ally, not once per track and ally) and a 3-run snapshot of every class is identical before and after, but they save only about 15 %; a bigger saving would have to skip far-away allies, which changes results.
Sweep options: `--investigate`, `--keep-identity` (the [predictor](../predictor/predictor.md)'s identity keeper), `--distributed`, `--cue`, and `--paired investigate|identity|distributed|cueing` to compare with and without one on the same seeds. All are off by default.

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
