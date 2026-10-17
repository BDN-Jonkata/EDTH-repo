# tracker module

Multi-target tracker: Kalman filter on native sensor readings, gated association, track management.

Status: a **central baseline** is done and tested (one tracker on all delivered readings, constant-velocity motion). Not done: per-node trackers sharing compact tracks, covariance intersection, out-of-order handling in the distributed mode, the close-crossing hold from a predictor. See [system design](../docs/system-design.md).

## What exists

| File | Contents |
|------|----------|
| [tracker.py](tracker.py) | `Tracker(config).step(t, readings, beacons)` returns the confirmed `Track`s; `TrackerConfig` |
| [ekf.py](ekf.py) | Kalman filter for `[x, y, vx, vy]` in plain lists: `predict`, `scalar_update` (no matrix is inverted) |
| [measurement.py](measurement.py) | `from_observation(obs, pose, module)`: an `observation` message plus where the sensor was becomes a `Measurement` (bearing, range, or range and bearing with Doppler); compass degrees become maths radians here only |
| [oosm.py](oosm.py) | Out-of-sequence readings: a checkpoint and a log of applied readings per track, `replay` with a late reading inserted by its own time, `fold_old` to keep the log short. Off unless `TrackerConfig.oosm` |
| [models.py](models.py) | Measurement models, the gate, a fix from one radar reading, triangulation of two bearings |
| [poses.py](poses.py) | `PoseBook`: where each node is **and how well**: ground sensors from the scenario; each drone from a small Kalman filter over its beacons (a beacon is noisy and arrives at 2 Hz), extrapolated to the time of a reading; else the planned patrol loop with a wide uncertainty. `Pose2D.sigma` is added to the noise of every reading from a sensor on that drone |
| `test_tracker.py` | Tests |

Run the chain end to end with [pipeline/](../pipeline/pipeline.md).

## How it works

- **Native readings only.** A camera or RF receiver gives a bearing, a single microphone a (poor) range from its loudness, a radar range, azimuth and Doppler. Nothing reads true positions; where a drone-mounted sensor was comes from the drone's beacons.
- **Association.** Per sensor scan, optimal assignment of readings to tracks inside a chi-square gate, so two readings of one scan never feed one track. Readings of different sensors do feed the same track.
- **Friendly beacons are cooperative readings.** Each friendly drone gets a track from its beacon, so a sensor's reading of that drone is absorbed by it instead of starting an "intruder" track. **While the drone's last beacon is under 2 s old, such a reading is only absorbed, not applied**: sensor readings of a drone carry Doppler and bearing errors, and applying them dragged an over-confident friend track 10 m off the real drone, where a duplicate "intruder" track then started on it. The beacon knows better. Without recent beacons the readings do update it.
- **The sensor's own position is uncertain.** A drone's position comes from its noisy beacons; a 4 m error moves a bearing at 100 m range by 2.3 degrees, more than a camera's own noise. So the pose book smooths the beacons and gives the tracker the pose's 1-sigma, which widens each reading's noise. Using beacon positions as if exact was the largest source of ghost tracks and ID swaps.
- **Starting a track.** From one radar reading (a fix), or from two bearings from different nodes that cross at 15 degrees or more. A bearing alone never starts one. No new track within 25 m of a living one.
- **Confirmation and support.** A track is confirmed after 5 readings within 4 s, only while its position is pinned down (1-sigma under 30 m) **and supported**: a range reading (radar, microphone level) within 3 s, or readings from at least 2 different nodes. A confirmed track that loses support for 4 s goes back to tentative; one unseen for 6 s (2 s if tentative) is dropped. Without the support rule, bearings of other objects along the same line kept wandering ghost tracks alive.

## Late readings (`TrackerConfig.oosm`, off by default)

By default a reading is used at its arrival time, so a reading delayed by seconds (a delay burst) either pulls a track back by what the target has moved since, or, when it no longer fits, starts a ghost track. With `oosm` on:

- A reading at least `oosm_min_age_s` (1 s, assumed) old on arrival is out of sequence; younger ones take the normal path.
- Each track keeps a checkpoint (its state some time ago) and a log of the readings applied since, for `oosm_window_s` (15 s, assumed). A late scan is matched to the tracks **as they were when it was taken**, and each matched track is replayed from the checkpoint with the reading inserted by its own time, so the track ends as if the reading had come on time. Replay is exact for this filter; a one-step-lag method is cheaper but only good for short delays.
- A late reading starts no track (what it saw has moved on), is only absorbed by a friendly's track, and does not keep a track alive beyond the time it was taken (`last_update` becomes the reading's time).
- A reading older than the window is dropped. Beacon tracks are not replayed.
- In the pipeline, `--oosm` turns it on for the central tracker; with `--trust` a late reading is weighted by link health and age (half-life 10 s) instead of being left out.

Measured on the `outage` preset (its own faults: F2 cut, GS2 delayed 4 s from 70 to 85 s, F4 dead from 100 s), 4 tuning seeds, 10 % loss, 10 s warmup, `python -m pipeline.sweep --preset outage --seeds 4 --losses 0.1 --paired oosm` (on minus off, ± standard error). Baseline without trust: hostile tracked 0.59, false tracks 1.00, ID swaps 2.5, position RMSE 14.2 m, OSPA 67.1 m, count error 1.33.

| Variant | Hostile tracked | False tracks | ID swaps | Position RMSE | OSPA | Count error |
|---------|-----------------|--------------|----------|---------------|------|-------------|
| `--oosm` against nothing | 0.00 | -0.62±0.05 | -1.25±0.48 | -2.0±0.8 m | -4.8±3.7 m | -0.23±0.23 |
| `--oosm` on top of `--trust` | +0.01±0.01 | -0.03±0.02 | 0.00 | -0.7±1.3 m | +0.0±0.5 m | 0.00 |

Reading it: **without trust, replaying late readings removes the ghost tracks a stale reading starts** (false tracks 1.00 to 0.38, ID swaps 2.5 to 1.25). `--trust` already gets the same cleaning by leaving late readings out, so on top of it `oosm` changes almost nothing: **it did not win back the 5 points of hostiles tracked** that dropping late readings costs. Why not: a delay burst delays every reading of a node by the same time, so the backlog arrives 4 s late and the tracks it would update are still alive but already held by other sensors; the information is real but adds little to a track that other nodes feed. Only 4 seeds and one preset; the test seeds are not used.

Not done: store-and-forward in the Python channel, so a link outage still loses its messages for good here (the viewer's mock resends them). The distributed mode does not use it.

## Results (`python -m pipeline.sweep --set test --seeds 20`, `medium` preset, clear weather, 10 s warmup)

Loss hits every message, observations and beacons. Without a behaviour module every track that is not a confirmed friendly counts as hostile.

| Message loss | Hostile detected | Position RMSE | ID swaps per run | Count error (abs) | OSPA | Friendlies flagged (of 5) | False tracks per step |
|--------------|------------------|---------------|------------------|-------------------|------|---------------------------|-----------------------|
| 0 % | 58 % | 13.4 m | 3.9 | 1.31 | 66 m | 0.05 | 0.75 |
| 30 % | 56 % | 14.4 m | 3.4 | 1.15 | 63 m | 0.05 | 0.44 |
| 50 % | 52 % | 12.9 m | 3.5 | 1.24 | 64 m | 0.0 | 0.33 |
| 70 % | 48 % | 14.2 m | 2.8 | 1.30 | 67 m | 0.35 | 0.19 |
| 90 % | 23 % | 13.6 m | 2.3 | 1.37 | 84 m | 4.65 | 0.09 |

Standard errors over the 20 seeds: about ±0.01 to 0.02 on the tracked share, ±0.04 to 0.07 on false tracks and count error, ±0.4 to 0.6 on ID swaps and ±0.6 to 0.8 m on position error. The sweep now prints every cell as `mean±error`.

**Compared with the first version of this tracker** (same test seeds): false tracks 1.28 to 0.75, ID swaps 5.6 to 3.9 and count error 1.59 to 1.31 at 0 % loss, from smoothing the drones' own positions and giving the tracker their uncertainty (see "How it works"); the tracked share did not change (57 to 58 %), because that limit is what the sensors see.

How to read it: a hostile is tracked a bit more than half the time, and the ceiling is not the tracker alone. On one tuning seed a hostile was seen by any sensor 75 to 85 % of the time it was present and by a radar or microphone only about 50 to 60 % (the microphone array gives a bearing, not a range), because ranges are short, cameras and the radar look forward, and detection probability falls with distance. Once a track is confirmed it follows well (the timeline of one run is mostly unbroken); the losses are the late start and gaps. **ID swaps are mostly re-acquisitions**: a track dropped after 10 s and then started again has a new id, which scoring counts as a swap. The count error looks small because it nets missed hostiles against ghost tracks (its bias is negative: more hostiles missed than ghosts counted). At 90 % loss friendlies are flagged because their beacons are lost, as in [friend_foe.md](../friend_foe/friend_foe.md); fewer false tracks at high loss is just fewer readings.

- **Duplicate tracks.** Two non-friend tracks within 30 m of each other and within 6 m/s in velocity are one target: the older stays. Found with the swap log (most ID swaps were a hostile flipping between two tracks 20 to 40 m apart); 30 tuning seeds at 0 % loss: false tracks -0.31±0.05, OSPA -4.4 m, count error -0.17, hostiles tracked and ID swaps unchanged (`TrackerConfig.duplicate_distance_m`, 0 turns it off).

## Where the 43 % goes (tuning seeds, 0 % loss, hostile-present seconds after the warmup)

| Share | What |
|-------|------|
| 51 % | tracked (a confirmed track within 30 m) |
| 5 % | only a tentative track |
| 18 % | seen by a sensor but never tracked, of which most (13 of 18 points) by **one node only** with a bearing |
| 27 % | not seen by any sensor |

So about three quarters of the gap is physical: nothing sees the hostile, or only one bearing sensor does, and one bearing gives no position. The tracker cannot fix that. What would: a second viewpoint, which is what the investigation drone provides.

## What was tried and did not help (5 tuning seeds, then 20 test seeds)

- **Pairing every bearing, claimed or not**, so a loose gate cannot hide a pair: no gain in coverage, twice the false tracks. Reverted.
- **Dropping vague bearings (RF 12 degrees, microphone array 7.5) before the tracker**: position error falls from 15.7 to 8.7 m, but hostiles tracked fall from 59 to 42 %. The vague bearings are what gives a second viewpoint, so they stay; the 14 m position error is the honest price of tracks supported by RF and microphone bearings only.
- **Tighter gates for single angles** and **a larger acceleration noise**: nothing or worse.
- **Longer time to live (10 s instead of 6)** and **4 readings to confirm**: a small gain on the tuning seeds (tracked 56 to 59 %, ID swaps 4.0 to 3.8) that did not show on the test seeds (57 %, 5.6 swaps). The 10 s stays as the default; read it as no measurable change.
- **Where position error comes from** (first check): not the beacon poses, clock error or latency for the position error itself (ideal poses and no degradations gave 16.0 and 14.6 m instead of 15.7 m). But the same check later showed ideal poses cut false tracks from 1.35 to 0.84 and ID swaps from 5.4 to 3.2 on the tuning seeds, which is what led to the smoothed poses with uncertainty described above.
- **A higher process noise for friend tracks** and **lowering a coasting track's existence** (so the behaviour module ignores guesses): no gain; the second one even made friendlies look flagged at 70 % loss, because friend tracks whose beacons were lost fell below the estimator's existence cutoff. Removed.

- **Crossing a moving node's own bearings over time** (parallax from a drone that moved 25 to 80 m): no effect, the angle stays under the 15 degree limit.

## Tuning and honesty

`min_nodes=2` was chosen over 3 on the 5 tuning seeds: hostiles detected 47 % to 56 % and count error 1.16 to 1.02, at the price of a worse position error (12.1 to 15.2 m) and more false tracks (0.85 to 1.18). A larger `accel_noise`, a shorter time to live and a looser sigma limit were tried and did not help, so they stayed at their first values. The numbers above are from the test seeds, used once. Everything in `TrackerConfig` is a guess. Simplifications: readings are used at their arrival time, not their `t_obs` (a few metres of error at 200 ms latency); the beacon's `t_sent` is the drone's own clock, so a clock offset becomes a pose error; no altitude (the tracker is 2D); one central tracker, so no link between nodes is modelled beyond the loss of messages to it.
