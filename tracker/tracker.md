# tracker module

Multi-target tracker: Kalman filter on native sensor readings, gated association, track management.

Status: a **central baseline** is done and tested (one tracker on all delivered readings, constant-velocity motion). Not done: per-node trackers sharing compact tracks, covariance intersection, out-of-order and latency handling, the close-crossing hold from a predictor. See [system design](../docs/system-design.md).

## What exists

| File | Contents |
|------|----------|
| [tracker.py](tracker.py) | `Tracker(config).step(t, readings, beacons)` returns the confirmed `Track`s; `TrackerConfig` |
| [ekf.py](ekf.py) | Kalman filter for `[x, y, vx, vy]` in plain lists: `predict`, `scalar_update` (no matrix is inverted) |
| [measurement.py](measurement.py) | `from_observation(obs, pose, module)`: an `observation` message plus where the sensor was becomes a `Measurement` (bearing, range, or range and bearing with Doppler); compass degrees become maths radians here only |
| [models.py](models.py) | Measurement models, the gate, a fix from one radar reading, triangulation of two bearings |
| [poses.py](poses.py) | `PoseBook`: where each node is: ground sensors from the scenario, drones from their beacons, else the planned patrol loop |
| `test_tracker.py` | Tests |

Run the chain end to end with [pipeline/](../pipeline/pipeline.md).

## How it works

- **Native readings only.** A camera or RF receiver gives a bearing, a single microphone a (poor) range from its loudness, a radar range, azimuth and Doppler. Nothing reads true positions; where a drone-mounted sensor was comes from the drone's beacons.
- **Association.** Per sensor scan, optimal assignment of readings to tracks inside a chi-square gate, so two readings of one scan never feed one track. Readings of different sensors do feed the same track.
- **Friendly beacons are cooperative readings.** Each friendly drone gets a track from its beacon, so a sensor's reading of that drone is absorbed by it instead of starting an "intruder" track.
- **Starting a track.** From one radar reading (a fix), or from two bearings from different nodes that cross at 15 degrees or more. A bearing alone never starts one. No new track within 25 m of a living one.
- **Confirmation and support.** A track is confirmed after 5 readings within 4 s, only while its position is pinned down (1-sigma under 30 m) **and supported**: a range reading (radar, microphone level) within 3 s, or readings from at least 2 different nodes. A confirmed track that loses support for 4 s goes back to tentative; one unseen for 6 s (2 s if tentative) is dropped. Without the support rule, bearings of other objects along the same line kept wandering ghost tracks alive.

## Results (`python -m pipeline.sweep --set test --seeds 20`, `medium` preset, clear weather, 10 s warmup)

Loss hits every message, observations and beacons. Without a behaviour module every track that is not a confirmed friendly counts as hostile.

| Message loss | Hostile detected | Position RMSE | ID swaps per run | Count error (abs) | OSPA | Friendlies flagged (of 5) | False tracks per step |
|--------------|------------------|---------------|------------------|-------------------|------|---------------------------|-----------------------|
| 0 % | 57 % | 13.8 m | 5.6 | 1.59 | 72 m | 0.05 | 1.28 |
| 30 % | 55 % | 15.2 m | 5.4 | 1.31 | 68 m | 0.3 | 0.84 |
| 50 % | 52 % | 14.5 m | 4.5 | 1.24 | 68 m | 0.2 | 0.58 |
| 70 % | 47 % | 15.4 m | 3.7 | 1.29 | 67 m | 0.6 | 0.29 |
| 90 % | 23 % | 14.2 m | 2.8 | 1.35 | 84 m | 4.65 | 0.11 |

How to read it: a hostile is tracked a bit more than half the time, and the ceiling is not the tracker alone. On one tuning seed a hostile was seen by any sensor 75 to 85 % of the time it was present and by a radar or microphone only about 50 to 60 % (the microphone array gives a bearing, not a range), because ranges are short, cameras and the radar look forward, and detection probability falls with distance. Once a track is confirmed it follows well (the timeline of one run is mostly unbroken); the losses are the late start and gaps. **ID swaps are mostly re-acquisitions**: a track dropped after 6 s and then started again has a new id, which scoring counts as a swap. The count error looks small because it nets missed hostiles against ghost tracks. At 90 % loss friendlies are flagged because their beacons are lost, as in [friend_foe.md](../friend_foe/friend_foe.md); fewer false tracks at high loss is just fewer readings.

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
- **Where position error comes from**: not the beacon poses, clock error or latency (ideal poses and no degradations gave 16.0 and 14.6 m instead of 15.7 m).

## Tuning and honesty

`min_nodes=2` was chosen over 3 on the 5 tuning seeds: hostiles detected 47 % to 56 % and count error 1.16 to 1.02, at the price of a worse position error (12.1 to 15.2 m) and more false tracks (0.85 to 1.18). A larger `accel_noise`, a shorter time to live and a looser sigma limit were tried and did not help, so they stayed at their first values. The numbers above are from the test seeds, used once. Everything in `TrackerConfig` is a guess. Simplifications: readings are used at their arrival time, not their `t_obs` (a few metres of error at 200 ms latency); the beacon's `t_sent` is the drone's own clock, so a clock offset becomes a pose error; no altitude (the tracker is 2D); one central tracker, so no link between nodes is modelled beyond the loss of messages to it.
