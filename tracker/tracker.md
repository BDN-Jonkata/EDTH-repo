# tracker module

Multi-target tracker: Kalman filter on native sensor readings, gated association, track management.

Status: a **central baseline** is done and tested (one tracker on all delivered readings, constant-velocity motion). Optional per-node trackers and covariance-intersection fusion are implemented in [pipeline/nodes.py](../pipeline/nodes.py) and [fusion/](../fusion/fusion.md); central late-reading replay is also optional. Distributed replay, time synchronization and stable association through the required close crossing remain open. Component implementation does not establish operational success; see the [03-Rai challenge audit](../docs/challenge-audit.md) and [system design](../docs/system-design.md).

## What exists

| File | Contents |
|------|----------|
| [tracker.py](tracker.py) | `Tracker(config).step(t, readings, beacons)` returns the confirmed `Track`s; `TrackerConfig` |
| [ekf.py](ekf.py) | Kalman filter for `[x, y, vx, vy]` in plain lists: `predict`, `scalar_update` (no matrix is inverted) |
| [measurement.py](measurement.py) | `from_observation(obs, pose, module)`: an `observation` message plus where the sensor was becomes a `Measurement` (bearing, range, or range and bearing with Doppler); compass degrees become maths radians here only |
| [oosm.py](oosm.py) | Out-of-sequence readings: a checkpoint and a log of applied readings per track (each with the state it left), `insert` puts a late reading in by its own time and redoes only the entries after it, `fold_old` to keep the log short. Off unless `TrackerConfig.oosm` |
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
- **Confirmation and support.** A track is confirmed after 5 readings within 4 s, only while its position is pinned down (1-sigma under 30 m) **and supported**: a range reading (radar, microphone level) within 3 s, or readings from at least 2 different nodes. A confirmed track that loses support for 4 s goes back to tentative; one unseen for 10 s (2 s if tentative) is dropped by default. Without the support rule, bearings of other objects along the same line kept wandering ghost tracks alive.

## Radial speed in the association (the crossing fix)

At the planned crossing the two hostiles pass within about 10 m of each other, so the range and the bearing of a radar return fit both tracks. Which return belongs to which track was settled by the position alone, the two tracks then took each other's readings, their velocities got mixed up, the duplicate merge dropped one of them as a clone and the other one followed the wrong hostile: all but one of the swaps on the `challenge` preset happened within 4 s of the crossing, in pairs (a restart or pickup on one hostile and a crossing swap on the other). The gate now also counts a radar reading's radial speed (Doppler), the one thing that differs between two targets going in different directions at the same place (`tracker/models.py`, `GATE_PARTS`, a 3-degree gate; the radial update is no longer applied twice).

Measured on the same 10 tuning seeds before and after (central tracker, clear weather):

| Preset, loss | ID swaps before | after | False tracks before | after | Hostile tracked before | after | Position RMSE before | after |
|--------------|-----------------|-------|---------------------|-------|------------------------|-------|----------------------|-------|
| `challenge`, 0 % | 1.80±0.47 | **0.30±0.15** | 0.39 | 0.23 | 0.65 | 0.66 | 9.96 m | 9.55 m |
| `challenge`, 30 % | 1.30±0.47 | **0.50±0.31** | 0.15 | 0.11 | 0.64 | 0.65 | 10.13 m | 9.82 m |
| `challenge`, 70 % | 2.00±0.47 | **0.30±0.15** | 0.07 | 0.03 | 0.59 | 0.60 | 11.88 m | 10.70 m |
| `medium`, 0 % | 2.60±0.40 | **1.10±0.38** | 0.45 | 0.35 | 0.61 | 0.61 | 12.37 m | 11.99 m |
| `medium`, 70 % | 2.50±0.65 | **1.00±0.26** | 0.10 | 0.08 | 0.51 | 0.52 | 14.43 m | 13.19 m |

The swap log on `challenge` (10 seeds, 0 % loss) went from 13 swaps (4 crossing, 3 pickup, 2 ghost, 4 restart) to 3 (all restarts). What is left: a restart, the track of a hostile that was lost and started again. The count error is about the same (0.65 to 0.61 at 0 %); the sensors still do not see the hostiles 35 % of the time.

## A friendly's track lives longer, and stays friendly (`friend_ttl_s`, `--no-friend-tracks`)

A friendly drone's beacon track used to be dropped after 10 s without a beacon or a reading, like any confirmed track. At 90 % loss beacons come about every 5 s, so the track was dropped regularly and the sensors then started a second, non-friend track on the same drone, which counted as a threat. Now a beacon track lives `friend_ttl_s` = 60 s, and the pipeline calls a track the tracker started from a beacon friendly for as long as the tracker keeps it, instead of waiting for the estimator to match a fresh beacon to it again. Measured on the `challenge` preset, 6 tuning seeds, on minus off: friendlies flagged at 90 % loss 4.0 to 0.2 of 5 (-3.83±0.31) and at 95 % 5.0 to 0.2 (-4.83±0.17), the time a friendly is flagged 0.12 to about 0.01 and 0.44 to about 0.01; hostile tracked unchanged (0.00±0.00); false tracks -0.19±0.05 at 95 %. At 0, 30 and 50 % loss on `medium` (8 seeds) nothing changes (0.00±0.00 in every column); on `outage` friendlies flagged -1.83±0.17 at 0 % loss and false tracks -0.13±0.03. The count error rises at very high loss (+0.33±0.06 at 90 %) because the flagged friendlies used to hide missing hostiles in the count. `--no-friend-tracks` gives the old behaviour.

## Late readings (`TrackerConfig.oosm`, off by default)

By default a reading is used at its arrival time, so a reading delayed by seconds (a delay burst) either pulls a track back by what the target has moved since, or, when it no longer fits, starts a ghost track. With `oosm` on:

- A reading at least `oosm_min_age_s` (1 s, assumed) old on arrival is out of sequence; younger ones take the normal path.
- Each track keeps a checkpoint (its state some time ago) and a log of the readings applied since, for `oosm_window_s` (15 s, assumed). A late scan is matched to the tracks **as they were when it was taken**, and each matched track goes back to just before the reading, takes it, and the later logged readings are applied again, so the track ends as if the reading had come on time. Replay is exact for this filter; a one-step-lag method is cheaper but only good for short delays.
- A late reading starts no track (what it saw has moved on) unless it is younger than `oosm_start_max_age_s` (1 s, assumed), which only matters when `oosm_min_age_s` is set lower than that, is only absorbed by a friendly's track, and does not keep a track alive beyond the time it was taken (`last_update` becomes the reading's time).
- A reading older than the window is dropped. Beacon tracks are not replayed.
- In the pipeline, `--oosm` turns it on for the central tracker; with `--trust` a late reading is weighted by link health and age (half-life 10 s) instead of being left out.

Measured on the `outage` preset (its own faults: F2 cut, GS2 delayed 4 s from 70 to 85 s, F4 dead from 100 s), 4 tuning seeds, 10 % loss, 10 s warmup, `python -m pipeline.sweep --preset outage --seeds 4 --losses 0.1 --paired oosm` (on minus off, ± standard error). Baseline without trust: hostile tracked 0.59, false tracks 1.00, ID swaps 2.5, position RMSE 14.2 m, OSPA 67.1 m, count error 1.33.

| Variant | Hostile tracked | False tracks | ID swaps | Position RMSE | OSPA | Count error |
|---------|-----------------|--------------|----------|---------------|------|-------------|
| `--oosm` against nothing | 0.00 | -0.62±0.05 | -1.25±0.48 | -2.0±0.8 m | -4.8±3.7 m | -0.23±0.23 |
| `--oosm` on top of `--trust` | +0.01±0.01 | -0.03±0.02 | 0.00 | -0.7±1.3 m | +0.0±0.5 m | 0.00 |

Reading it: **without trust, replaying late readings removes the ghost tracks a stale reading starts** (false tracks 1.00 to 0.38, ID swaps 2.5 to 1.25). `--trust` already gets the same cleaning by leaving late readings out, so on top of it `oosm` changes almost nothing: **it did not win back the 5 points of hostiles tracked** that dropping late readings costs. Why not: a delay burst delays every reading of a node by the same time, so the backlog arrives 4 s late and the tracks it would update are still alive but already held by other sensors; the information is real but adds little to a track that other nodes feed. Only 4 seeds and one preset; the test seeds are not used.

### Readings applied at the time they were taken (`--oosm-age`), and time-sync

By default the tracker applies a reading at its **arrival** time, so a reading that took 50 to 400 ms to arrive (`hard` preset) is treated as fresh, 1 to 8 m behind a target at 20 m/s. `--oosm --oosm-age 0.2` lowers the age at which a reading is replayed at its own time from 1 s to 0.2 s. Each log entry keeps the state it left, so a reading only redoes the entries after it (a 30 s run went from 126 s to 5 s of CPU with this; the first version replayed the whole log from the checkpoint). `--oosm` on `outage` with `--trust` agrees with the version before this change in every column but OSPA (59.37 against 59.42 m, float order).

Readings can also carry their node's own clock (`--clocks`: offset and drift as the scenario's `degradations.clock` gives them, which beacons already did) and `tracker/timesync.py` (`--timesync`) estimates each node's clock from `arrival - t_sent`: the smallest value over the recent past is the shortest delay minus the offset, and the shortest delay is the network's lower bound (rounded up to the 0.1 s step the messages are handed over on) plus the sensor's catalog latency. The estimate follows a drifting clock by letting the envelope creep up 100 ppm per second, and a delay burst does not move it. Reference: the C2 clock. On `hard` it finds every node's offset within 3 ms after 30 s (a node can be 100 ms off in the first seconds when its fast messages were lost). It corrects the stamps of delivered observations and beacons before the pose book and the tracker see them.

Measured on `hard`, 8 tuning seeds, 0 % and 30 % loss, 10 s warmup (`--paired`, on minus off, ± standard error; test seeds not used):

| Comparison | Hostile detected | False tracks | ID swaps | Position RMSE | OSPA |
|------------|------------------|--------------|----------|---------------|------|
| `--paired clocks` (node clocks on readings, against true time) | 0.00 / -0.01 | +0.02±0.12 / -0.01±0.01 | 0.00 | -0.19±0.33 / 0.00±0.09 m | -0.1±0.8 / +0.5±0.4 m |
| `--paired timesync` (default tracker, clocks on both sides) | 0.00 | +0.02±0.01 / -0.04±0.03 | 0.00 | +0.08±0.08 / 0.00±0.12 m | 0.0±0.1 / -0.4±0.4 m |
| `--timesync --paired oosm --oosm-age 0.2` | -0.02±0.01 / -0.01±0.01 | -0.31±0.08 / -0.30±0.09 | -1.4±1.1 / -0.8±0.5 | -0.7±0.6 / +0.3±0.4 m | -1.3±1.5 / -1.2±0.9 m |
| `--timesync --paired oosm --oosm-age 0.05` | -0.01±0.01 | -0.41±0.06 / -0.32±0.10 | -2.0±1.2 / -2.6±1.2 | -0.4±0.6 / -0.2±0.4 m | -1.9±1.3 / -1.4±1.1 m |
| `--oosm --oosm-age 0.2 --paired timesync` (does sync help once readings use their times?) | 0.00 / -0.01 | -0.03±0.09 / -0.05±0.06 | -1.8±0.9 / +0.5±0.6 | -0.4±0.3 / +0.2±0.4 m | 0.0±0.7 / +0.5±0.7 m |

Reading it: with the default tracker **clock error on readings costs nothing measurable and time-sync gains nothing**, because the tracker never uses a reading's own time; with the clocks at 100 to 200 ms and 20 to 50 ppm the effect is below what 8 seeds can see. **Replaying fresh readings at the time they were taken does help a little**: false tracks fall by 0.3 to 0.4 per step (about 4 standard errors) and ID swaps by 1 to 2.6 per run (1.5 to 2 standard errors), while position error and OSPA stay within noise and the hostiles tracked are at most 2 points lower (about 1 to 2 standard errors). **Time-sync adds nothing on top of that either**: the clock offsets (up to 200 ms, 4 m at 20 m/s) are small next to the position noise of the sensors. The estimator works (a few ms), but on these presets there is no error for it to remove; it would matter with larger offsets or sensors with tighter noise. The Python pipeline's step is 0.1 s, so offsets under 100 ms are below the time resolution anyway.

Store-and-forward is in the Python pipeline now (`--storefwd`, [pipeline.md](../pipeline/pipeline.md)), so an outage's backlog arrives late and `--oosm` replays it. The distributed mode does not use either.

## Results (`python -m pipeline.sweep --set test --seeds 20`, `medium` preset, clear weather, 10 s warmup)

These published measurements are preserved unchanged and predate later tracker changes. They describe the medium baseline, not current challenge-preset acceptance. See the [challenge audit](../docs/challenge-audit.md) for current validation.

Loss hit every message, observations and beacons. These historical baseline measurements counted every track that was not a confirmed friendly as hostile; they did not measure strict-hostile classification. Current scoring definitions are documented in the audit.

| Message loss | Hostile detected | Position RMSE | ID swaps per run | Count error (abs) | OSPA | Friendlies flagged (of 5) | False tracks per step |
|--------------|------------------|---------------|------------------|-------------------|------|---------------------------|-----------------------|
| 0 % | 58 % | 13.4 m | 3.9 | 1.31 | 66 m | 0.05 | 0.75 |
| 30 % | 56 % | 14.4 m | 3.4 | 1.15 | 63 m | 0.05 | 0.44 |
| 50 % | 52 % | 12.9 m | 3.5 | 1.24 | 64 m | 0.0 | 0.33 |
| 70 % | 48 % | 14.2 m | 2.8 | 1.30 | 67 m | 0.35 | 0.19 |
| 90 % | 23 % | 13.6 m | 2.3 | 1.37 | 84 m | 4.65 | 0.09 |

Standard errors over the 20 seeds: about ±0.01 to 0.02 on the tracked share, ±0.04 to 0.07 on false tracks and count error, ±0.4 to 0.6 on ID swaps and ±0.6 to 0.8 m on position error. The sweep now prints every cell as `mean±error`.

**Compared with the first version of this tracker** (same test seeds): false tracks 1.28 to 0.75, ID swaps 5.6 to 3.9 and count error 1.59 to 1.31 at 0 % loss, from smoothing the drones' own positions and giving the tracker their uncertainty (see "How it works"); the tracked share did not change (57 to 58 %), because that limit is what the sensors see.

How to read it: a hostile is tracked a bit more than half the time, and the ceiling is not the tracker alone. On one tuning seed a hostile was seen by any sensor 75 to 85 % of the time it was present and by a radar or microphone only about 50 to 60 % (the microphone array gives a bearing, not a range), because ranges are short, cameras and the radar look forward, and detection probability falls with distance. Once a track is confirmed it follows well (the timeline of one run is mostly unbroken); the losses are the late start and gaps. A re-acquisition with a new track ID counts as a swap, but a later event log found the main causes were **duplicate/ghost tracks and two hostiles trading tracks** (36 ghost and 20 crossing swaps of 65; see [pipeline.md](../pipeline/pipeline.md#why-the-hostiles-ids-swap-and-what-was-tried-after-that)). The count error looks small because it nets missed hostiles against ghost tracks (its bias is negative: more hostiles missed than ghosts counted). At 90 % loss friendlies are flagged because their beacons are lost, as in [friend_foe.md](../friend_foe/friend_foe.md); fewer false tracks at high loss is just fewer readings.

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

`min_nodes=2` was chosen over 3 on the 5 tuning seeds: hostiles detected 47 % to 56 % and count error 1.16 to 1.02, at the price of a worse position error (12.1 to 15.2 m) and more false tracks (0.85 to 1.18). A larger `accel_noise`, a shorter time to live and a looser sigma limit were tried and did not help, so they stayed at their first values. The numbers above are from the test seeds, used once. Everything in `TrackerConfig` is a guess. Simplifications of the default central baseline: readings are used at arrival time rather than `t_obs` unless `oosm` is enabled; the beacon's `t_sent` is the drone's own clock, so a clock offset becomes a pose error; no altitude (the tracker is 2D); peer-link topology and merger failover are not modeled. Optional distributed tracking is described in [fusion.md](../fusion/fusion.md).
