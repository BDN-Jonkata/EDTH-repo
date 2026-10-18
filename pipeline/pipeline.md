# pipeline

The whole chain on one scenario: sensors, lossy network, tracker, friend/foe, scoring.

Status: done and tested for the central baseline. See [tracker](../tracker/tracker.md), [sensors](../sensors/sensors.md), [scoring](../scoring/scoring.md).

| File | Contents |
|------|----------|
| [run.py](run.py) | `Pipeline(scenario, seed).step(t)`, `run(scenario, seed)` (frames of confirmed tracks), `scored_frames(scenario, seed)` (the tracks with the estimator's classes, ready for `scoring.metrics.score`) |
| [sweep.py](sweep.py) | `python -m pipeline.sweep --set test --seeds 20 [--weather fog+wind] [--birds 2 --vehicles 2] [--csv file]`: the metrics over message loss |
| [storefwd.py](storefwd.py) | `StoreForward`: nodes keep and resend what C2 has not acknowledged, C2 acks, drops duplicates and files late messages as history (`--storefwd`) |
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
## Injected faults (Orlin's `sensor_faults[]`)

The channel now applies `degradations.sensor_faults[]` and the older `dropout[]` ([common/channel.py](../common/channel.py), `Faults`): `dropout` stops a node's messages for good, `link_outage` drops them in a window, `delay_burst` delays them. They apply whenever the scenario lists them. Not modelled: store-and-forward (nodes resending what C2 missed): the pipeline has no history to put late messages in, and the tracker uses readings at their arrival time, so a resent reading could not be used live anyway.

**Result** (the `outage` preset: F2's link cut 30 to 60 s, GS2 delayed 4 s from 70 to 85 s, F4 dead from 100 s; 8 seeds with the faults removed against with them, 10 s warmup, tuning seeds):

| | Hostile tracked | False tracks | Count error | OSPA | Friendlies flagged (of 5) |
|-|-----------------|--------------|-------------|------|---------------------------|
| central, no faults | 0.60 | 0.59 | 1.12 | 62 m | 0 |
| central, change with faults | -0.02±0.01 | +0.54±0.21 | +0.43±0.16 | +8.3±3.2 m | **+1.75±0.25** |
| distributed, no faults | 0.58 | 0.77 | 1.21 | 65 m | 0 |
| distributed, change with faults | -0.10±0.02 | +0.01±0.03 | +0.18±0.08 | +7.6±1.9 m | **+1.75±0.16** |

The headline is the friendlies: of the two drones the faults hit (F2 while cut, F4 once dead) about 1.75 are flagged as threats. Their beacons stop, so the estimator's identity fades to `unknown`, which scoring counts as hostile, although the drone is still seen by the other nodes. This is the "silence is not proof of hostility" case of [friend_foe.md](../friend_foe/friend_foe.md), now measured with real faults. The distributed mode also loses 10 points of hostiles (a node's tracks stop reaching the merger while it is cut off). Not yet fixed.
## Why the hostiles' IDs swap, and what was tried after that

`python -m pipeline.sweep --swaps` sorts every ID swap into a cause ([scoring/swaps.py](../scoring/swaps.py); 20 tuning seeds, `medium`, 0 % loss, 65 swaps): **ghost 36** (the hostile's old track is still alive but on nothing: a duplicate track 20 to 40 m from the hostile), **crossing 20** (two hostiles trade tracks), restart 4, other 3, pickup 2. Only about 9 % are a dropped track starting again, so the predictor's identity keeper (re-acquisition) could not have helped, which is what its test showed.

- **Duplicate tracks merged** ([tracker.md](../tracker/tracker.md)): 30 tuning seeds, 0 % loss, change: false tracks -0.31±0.05, OSPA -4.4±1.0 m, count error -0.17±0.05, hostiles tracked unchanged; ID swaps unchanged. On by default (30 m, 6 m/s).
- **A moving node's own bearings crossed over time** (parallax, one sensor 1 to 4 s apart, baselines 25 to 80 m): no effect at all, because the crossing angle stays under the 15 degree limit. Removed.
- **Making the hand-off cheaper** (12 tuning seeds, 0 % loss, change from no drones): stricter track age, position error or a two-node condition changed nothing beyond noise. What changes the cost is how many drones leave the patrol: 2 active and 6 s on station (current): false tracks +0.39±0.08, time to a drone in range -11.5±2.4 s; **1 active and 3 s: false tracks +0.08±0.06, count error +0.08±0.04, time -7.9±2.2 s**; 3 active: false tracks +0.62±0.10. The 1 active, 3 s setting keeps most of the speed for almost no cost to the picture, but it is **not confirmed** on other seeds and the 3 s on station is an assumption, so the defaults of `Dispatcher` (`max_active=2`, `dwell_s=6`) were not changed.
Sweep options: `--no-friend-tracks` (a beacon-born track is friendly while the tracker keeps it, on by default; see [tracker.md](../tracker/tracker.md)),  `--investigate`, `--keep-identity` (the [predictor](../predictor/predictor.md)'s identity keeper), `--distributed`, `--cue`, `--behaviour [safe|raw]`, `--trust` (link health, [health.md](../health/health.md)), `--oosm` (a late reading is applied at the time it was taken, [tracker.md](../tracker/tracker.md)), `--oosm-age SECONDS` (with `--oosm`: how old a reading must be to be replayed at its own time, default 1), `--storefwd` (store-and-forward when the scenario asks for it, see below), `--clocks` (readings are stamped by their node's own clock), `--timesync` (the tracker estimates those clocks, [tracker.md](../tracker/tracker.md); implies `--clocks`; not for `--distributed`), `--swaps`, and `--paired investigate|identity|distributed|cueing|trust|oosm|clocks|timesync|storefwd` to compare with and without one on the same seeds. All are off by default.

```
sensors/observe.py + sensors/beacons.py    what the nodes sense and send (needs the true positions)
common/channel.py                          loss, burst, delay from the scenario's degradations
tracker/ (+ PoseBook)                      one central tracker on what the channel delivered
friend_foe/                                classification from tracks and delivered beacons, every 0.5 s
scoring/                                   metrics against truth.json
```

Everything before the channel is the simulation side and may use the truth; the tracker and the estimator see only delivered messages. The clock is 0.1 s. Jamming zones (from the sender's true position), the link cap and node dropout from the scenario are applied by [common/channel.py](../common/channel.py), as in the viewer's mock; not modelled: topology, RF receivers getting noisier inside a zone, link outages, delay bursts, store-and-forward. A preset with `dropout` (`hard`) now loses that node's messages from the dropout time on in this pipeline, which earlier Python results did not. Weather reaches the sensors per detection through the weather provider; it does not yet change the tracker.

Results: [tracker.md](../tracker/tracker.md#results).

## Identifying a hostile from what the sensors hear (`pipeline/identify.py`, `--no-identify`)

Steady flight looks the same for a hostile and a harmless object, so motion cannot say which it is (see the behaviour sections). An RF receiver can: it only hears a transmitter, and the birds and vehicles do not transmit. One receiver gives a bearing, and any track on that line takes it, so a first version that credited the track nearest the bearing called a bird hostile 44 % of its tracked time. Now the bearings of two receivers are crossed into a fix and the fix goes to the one track it agrees with best (Mahalanobis gate with the fix's own uncertainty), unless that is a friendly's; three fixes in 6 s make the track `hostile`. Measured on 8 tuning seeds, 0 % loss, `medium` with 2 birds and a vehicle: **real hostiles are called hostile 23 % of their tracked time and birds and vehicles 4 %** (the sensors give only two RF receivers with 12 degrees of bearing noise, so recall is low). `challenge`, 0 % loss: strict hostile detected 0.00 to 0.17, strict count error 1.73 to 1.41, nothing else changes (hostile tracked 0.72, false tracks 0.28, ID swaps 0.25); friendlies are never overridden. A silent hostile is not found this way, and a track the estimator calls friendly keeps that. It is on by default in the Python pipeline; `--no-identify` turns it off. The viewer's JavaScript has the same rule (`noteEmitters` in `sim.js`) but only when the run sets `emitterHostile` (the viewer does, the tests do not), because the behaviour module's own rule is that sensor evidence of a transmitter is not evidence of hostile intent: in the viewer's scenarios 68 % of the tracked hostile time on `medium` and 0 % of the birds and vehicles on `dusk` are called hostile (`ui/viewer/test-emitters.js`). The team has to agree that an unknown transmitter in the defended area is a hostile.

**Single-receiver credit (`IdentifyConfig.single_receiver`, on by default).** The scenario has two RF receivers (the ground sensor GS2 and the drone F3), and F3 hears the hostiles far less than GS2 (100 to 400 bearings against about 1000 per run), so a two-receiver fix within 0.3 s was the bottleneck. A bearing from one receiver now also counts for a track when it is on the hostile link (the RF reading's `center_freq_mhz`, kept in `Measurement.freq_mhz`; the friendlies' band is 5745 MHz, `sensors.native.in_friend_band`) and exactly one non-friend track can explain it; a second non-friend track on the line (a bird behind a hostile) makes it count for nothing, and a bearing on the friendlies' link or without a frequency counts for nothing. Ten such bearings in 6 s make the track `hostile`. **Assumed:** a hostile never uses the friendlies' band; the numbers 10 and 6 s are assumptions. Tuning seeds 1 to 8 (`challenge`, 0 % loss): strict hostile detected 0.17 to 0.24, strict count exact 0.12 to 0.14, no change in friendlies flagged, clutter flagged, false tracks or ID swaps; at 50 % loss 0.12 to 0.16, at 90 % loss 0.00 (the RF bearings are lost). With 2 birds and 2 vehicles the same (0.18 to 0.22). Fresh test seeds 1020 to 1039, run once: 0.16 to 0.20 at 0 % loss, 0.11 to 0.14 at 50 %, 0.00 at 90 %, with nothing else changed (friendlies flagged 0.10 at 0 % loss, same with the rule off). **Recall stays low:** a lower threshold of 4 bearings raised it to 0.31 on the tuning seeds but flagged 0.25 of 5 friendlies at 90 % loss, so it was rejected. The limits are the 12 degrees of bearing noise, only two RF receivers and a hostile being tracked 65 to 72 % of the time. This is not hostile intent from behaviour: the `threat_llr` hook cannot supply it on `challenge` (see [drone behaviour](../drone_behavior/drone_behavior.md)).

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

## Store-and-forward (`--storefwd`, [storefwd.py](storefwd.py))

Port of the mock simulation's rules (`ui/viewer/storefwd.js`; the pure parts are in [common/storefwd.py](../common/storefwd.py) and checked against the JavaScript with shared cases, `python -m common.golden` and `node ui/viewer/test-channel-port.js`). Needs the scenario to turn `degradations.store_forward` on (the `outage` preset does); central tracker only.

- Every message a node sends is kept until C2 acknowledges it (60 s at most). C2 sends a `c2_ack` once a second to each live node over **that node's own link** (`Channel.send_to`), so a link outage or a jam cuts the ack as well as the node's messages; a node that hears it resends what C2 is missing, oldest first, within half of a capped link.
- A drone puts `status` (oldest `seq` it still holds) in each beacon, a ground sensor sends `node_status` once a second, so C2 stops asking for what expired.
- C2 drops a message whose `seq` already arrived. A message more than 3 s old on arrival goes to history, not to the live picture; a late **observation** is kept only with `--oosm` (the tracker can replay it), a late **beacon** never is (the pose filter would be pulled back to where the drone was).
- Not ported: the viewer's per-node health states (`health/` judges the links here).

Measured on `outage`, 8 tuning seeds, 10 % loss, on minus off, ± standard error: the mechanism works (F2 holds about 80 messages by 65 s and is down to a handful by 80 s), but **it recovers little for tracking**. Hostile detected 0.00±0.01 with `--oosm`, -0.04±0.02 without it, -0.01±0.01 with `--trust --oosm`; false tracks +0.14±0.07 (`--oosm`), +0.07±0.02 (`--trust --oosm`); ID swaps within noise. Why: most of an outage's backlog is beacons (late, so history) and the cut-off drone saw little: on one seed only 32 readings arrived 10 s or more late, 12 of them were replayed (all under 20 s old) and none of the 12 older than 30 s matched a track, so a 60 s replay window instead of 15 s changes nothing. What store-and-forward gives is the record of what the node saw (the viewer shows it), not a better live picture.

