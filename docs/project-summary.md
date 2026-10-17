# Project summary

For a teammate or judge who has not seen the code. Details live in the module docs linked below.

Current requirement evidence and priorities: [03-Rai challenge audit](challenge-audit.md). “Done” below means a component is implemented and tested; it does not certify correct hostile counts, stable crossing identities or zero friendly threats. Those operational criteria remain open.

## 1. The idea

Five friendly drones and two ground sensors watch about 1 km2 under electronic warfare (lost, delayed, jammed messages, drifting clocks, uncertain positions). Two hostile drones cross at close range. The required Common Operational Picture (COP) must:

- give the right number of hostiles, each with a stable ID, position and velocity;
- never flag a friendly as a threat;
- degrade gracefully when messages are lost.

Approach: a classical tracker (Kalman filter) is the core. Verified roster identity and trusted position beacons identify friendlies; motion supplies separate risk evidence and cannot establish friendly identity. A suspicious track can send the closest drone for a second look. A scoring module checks estimates against ground truth.

Sensors report only their native fields (a camera gives bearing and elevation, never range). All sensor numbers in the catalog are assumptions unless the catalog says `verified`.

## 2. What is done, per module, and who owns it

| Module | Owner | State |
|--------|-------|-------|
| `seeder/`, `scenarios/`, `common/` (codec, channel), viewer mock simulation | Orlin | Done. Catalog of 5 UAS and 2 ground sensors (PostgreSQL, shared as `db-dump.json.gz`). Scenario generator: one config plus seed gives `scenario.json` and a separate `truth.json`. Eight presets including `outage`, clutter (birds, vehicles), weather combinations and events, jamming zones, bandwidth caps, seed sweeps. Python channel: loss (independent or bursty), delay, jamming loss, link caps and injected node faults; clock helpers affect beacons, while native sensor timestamps remain ideal. Viewer (`ui/viewer`) runs a JavaScript mock simulation with commanded drone motion. |
| `drone_behavior/` and the viewer's `investigations.js` | Emkata | Done. Judges observed motion and gives hostile-like or peaceful-like evidence to the estimator (`threat_llr`), separately from verified identity. No protected zone: risk uses responsive pursuit and intercept behavior, with uncertainty gates and decaying encounter memory. Viewer shows identity/risk percentages and thresholds; another available drone investigates an approached ally's contact. Ack, retry, release and cooldown remain. Python and JS parity tests. |
| `sensors/` | Kristian | Done. Weather (several anomalies at once, events that start/stop/cover a zone, season-based night), sensor quality, required standoff, observation models (range window, field of view, falling detection probability, signatures, honest native noise), beacon source. |
| `friend_foe/` | Kristian | Done. Estimator with five classes (friendly, peaceful, unknown, suspicious, hostile), two evidence axes (beacon, behaviour), silence weighted by the measured beacon delivery rate, investigation trigger with weather-based standoff, drone-status mapping. |
| `scoring/` | Kristian | Done. Optimal matching to scoring truth; count error, position/velocity/heading error, OSPA, ID swaps, friendly and clutter false alarms. `scoring/viewer_run.py` reads exported viewer JSON and its recorded truth. The historical Python baseline counted unknown/suspicious tracks as hostile; see the audit for current count definitions and comparisons. |
| `pipeline/` | Kristian | Done. Runs the whole chain on one scenario, loss sweeps (`python -m pipeline.sweep`), and a stand-in drone fleet plus dispatcher to close the investigation loop. |
| `ui/` | Kristian | Partial. The JavaScript simulation has map, track list, headings, uncertainty, assessments, alerts, playback, metrics and impairment controls. Exported runs can be scored in Python. Displaying the Python tracker/fusion COP in this viewer remains open. |
| `tracker/` | no owner | A central baseline was built by Kristian: Kalman tracker on native readings, gated optimal association, track start from radar or two crossing bearings, support rules, friendly beacon tracks, smoothed drone poses. |
| `fusion/`, `predictor/` | no owner | Implemented as optional Python features. Per-node trackers share compact tracks and bearings with a covariance-intersection merger (`--distributed`); one merger, no failover. Constant-velocity and learned identity keepers exist but have not demonstrated a crossing-swap improvement. |
| Simulation | Orlin (viewer); Python pipeline integration by Kristian | `pipeline/`, `sensors/` and `common/channel.py` run the Python simulation chain. The `simulation/` folder remains a placeholder. The viewer uses its own JavaScript simulation; its responsive traffic actors and store-and-forward are not in the Python chain. |

## 3. How the whole workflow works

```
 scenario seeding (seeder/generate.py, config + seed)
        |-- scenario.json  (what the system may read)
        '-- truth.json     (scoring only)
        v
 sensors/observe.py + sensors/beacons.py   [simulation side, may use true positions]
   - each drone/ground sensor makes native readings (bearing, level, range, Doppler)
   - friendlies send position beacons (2 Hz, noisy, own clock)
        v
 common/channel.py   lossy channel: loss (bursty), delay, node clocks
        v   [from here on, only what was delivered is visible]
 tracker/poses.py  PoseBook: where each sensor was, and how well
   (ground sensors from scenario, drones smoothed from their beacons)
        v
 tracker/  central Kalman tracker -> confirmed tracks (x, y, vx, vy)
        v
 friend_foe/  estimator, every 0.5 s: tracks + delivered beacons (+ behaviour hook)
        |   -> class per track
        v
 pipeline/dispatch.py  investigation: trigger -> closest free drone -> back to tracker
        v
 scoring/  tracks + classes vs truth.json -> metrics
```

Step by step (`pipeline/run.py`, clock step 0.1 s):

1. **Seeding.** A preset config plus a seed gives a scenario: friendly patrol loops, ground sensors, hostile and benign paths with a planned close crossing, clutter, weather, degradations.
2. **Sensing.** `ObservationSource` produces `observation` messages from each sensor, subject to range, field of view, detection probability and weather at that moment and place. `BeaconSource` produces friendly beacons. All messages carry the standard header (`source_id`, `seq`, `t_sent`, ...).
3. **Channel.** Every message is sent through `Channel`, which drops it (independent or bursty loss, per sender) or delays it. The channel module's `Clock` helper is used by `BeaconSource` to stamp beacons with local offset/drift; native `ObservationSource` readings still carry ideal simulation `t_obs` and `t_sent`. The channel does not convert their timestamps. Time synchronization remains open.
4. **Pose book.** Delivered beacons update each drone's pose (a small Kalman filter). Its uncertainty is added to the noise of every reading from that drone's sensors, because a few metres of pose error is a large bearing error.
5. **Tracker.** Readings become measurements and are assigned to tracks inside a chi-square gate. A track starts from one radar fix or two crossing bearings, is confirmed after 5 readings in 4 s with support (a range reading or two nodes), and a confirmed track is dropped after 10 s unseen by default (2 s when tentative). Each friendly gets a beacon track so sensor readings of it are absorbed instead of starting an "intruder".
6. **Friend/foe.** Every 0.5 s the estimator gets the tracks and the beacons delivered since. A matching beacon pushes a track toward friendly. Silence lowers confidence slowly and counts for less when the measured delivery rate is low. Hostile or peaceful need positive behaviour evidence from `drone_behavior` (`threat_llr`); silence alone gives only suspicious (raw estimator) or unknown (automatic).
7. **Investigation (optional, `--investigate`).** The trigger raises a request for a track that stays suspicious, with a standoff per sensor module computed from the weather. The dispatcher only considers tracks that are old, recently updated, well localised and moving. It sends the closest free drone to the standoff distance (never under 40 m), faces the track, stays 6 s, returns. At most 2 at a time. Status goes back to the trigger. This is a stand-in for Emkata's full version in the viewer.
8. **Scoring.** Tracks plus classes are matched to `truth.json` object by object. The historical baseline below counted every class except `friendly` and `peaceful`; it must not be compared directly with a strict-hostile GUI count. Current definitions and acceptance checks are in the challenge audit. Drones sent off their patrol are scored against their recorded real trajectories (`scoring.truth.with_recorded_samples`), because `truth.json` only holds the scripted patrol.

**Seed discipline.** Tune on seeds 1-99; test seeds 1000-1099 are reserved for the final numbers and must not be tuned on (`generate.py --sweep tuning` or `--sweep test`). Reported numbers below come from test seeds, run once.

**Who may read what.** Only `scoring/` reads `truth.json`. Tracker, friend/foe, behaviour and dispatch read `scenario.json` and the delivered messages. The sensor models and the beacon source are on the simulation side and need true positions, so the tracker never imports them.

## 4. Historical measured results

Source: `tracker/tracker.md` and `pipeline/pipeline.md`. These published historical values predate later changes and are preserved for comparison; they are not a current challenge-preset acceptance run. Test seeds, `medium` preset, clear weather, 20 seeds, 10 s warmup, no behaviour module (every track not confirmed friendly counts as hostile). Loss applies to every message, observations and beacons. See the [challenge audit](challenge-audit.md) for current checks.

| Message loss | Hostile tracked | Position RMSE | ID swaps/run | Count error | False tracks/step | Friendlies flagged (of 5) |
|--------------|-----------------|---------------|--------------|-------------|-------------------|---------------------------|
| 0 % | 58 % | 13.4 m | 3.9 | 1.31 | 0.75 | 0.05 |
| 30 % | 56 % | 14.4 m | 3.4 | 1.15 | 0.44 | 0.05 |
| 50 % | 52 % | 12.9 m | 3.5 | 1.24 | 0.33 | 0.0 |
| 70 % | 48 % | 14.2 m | 2.8 | 1.30 | 0.19 | 0.35 |
| 90 % | 23 % | 13.6 m | 2.3 | 1.37 | 0.09 | 4.65 |

These were measured after the pose-smoothing and beacon-absorption fixes. At 0 % loss the fixes took false tracks from 1.28 to 0.75, ID swaps from 5.6 to 3.9, count error from 1.59 to 1.31; tracked share did not change (57 to 58 %).

Reading them:

- About three quarters of the missing 42 % at 0 % loss is physical: 27 % of hostile time no sensor sees it, 18 % is seen but never tracked (mostly by one bearing-only node, which gives no position). The tracker cannot fix that; a second viewpoint can.
- A later swap log found duplicate/ghost tracks and two hostiles trading tracks were the main causes, rather than re-acquisitions (`pipeline/pipeline.md`: 36 ghost and 20 crossing swaps of 65).
- At 90 % loss friendlies are flagged because their beacons are lost; fewer false tracks there just means fewer readings.
- Beacon-only estimator on clean adapter tracks (`friend_foe.md`): no friendly flagged up to 70 % beacon loss, 1.9 of 5 at 90 %; a hostile is never called friendly; time to flag a hostile grows from 4 s (0 % loss) to about 10 s (70 %).

**Stale numbers.** The investigation table in `pipeline/pipeline.md` (off vs on, e.g. 0 % loss: tracked 57 % off, 59 % on; false tracks 1.28 off, 1.93 on) was measured before the latest tracker fixes. Its "off" rows match the old tracker, not the table above. Re-run `python -m pipeline.sweep --paired investigate` before quoting it. What it showed then: a small, mixed effect; hostile tracked 2 to 4 points more at 0 and 50 % loss, but more false tracks and flagged friendlies; about 7 dispatches per run, of which 17 of 37 went to a real hostile, 16 to ghost tracks, 4 to a friendly (small sample). The dispatch eligibility rules were added after that and are not re-measured.

The `--behaviour` run in `pipeline.md` (10 seeds, 15 % loss) predates the zone-free encounter policy: with that earlier behaviour module on or off the results were identical, because on real tracks it never called anything peaceful (clutter flagged 38 % either way). It does not measure the new policy. The scoring module's own sweep and `drone_behavior.evaluate` use the clean test adapter, so they show logic, not real accuracy.

The later zone-free integration measurement in `pipeline/pipeline.md` reports raw behavior reducing counted-hostile tracking from 0.60 to 0.32 on 10 tuning seeds with clutter; 34–47% of real hostile tracks became peaceful. Safe mode suppresses motion-only peaceful classification and leaves the baseline unchanged. Ordinary hostile crossing paths need not pursue allies, so the busy pursuit demo does not establish the challenge's hostile-count criterion.

## 5. Still to do and weak spots

To do:

- Demonstrate stable IDs and correct count through the required close crossing; tracker/fusion association remains a priority even though optional predictors are implemented.
- Validate the optional distributed mode under intermittent links; peer-link topology, merger failover and distributed late-reading handling remain open.
- Complete Python/viewer feature integration where required: Python store-and-forward and RF jamming noise, and a viewer for the Python COP.
- Re-measure investigation and behavior with the current tracker, consistent count definitions and crossing-window metrics.
- Run reproducible challenge acceptance and degradation sweeps, then the reserved final seed set after tuning is frozen; finish the demo and write-up.

Known weak spots:

- Hostile tracked only about 58 % of the time even with no loss; limited by sensor coverage and one-bearing-only sightings.
- ID swaps (about 4 per run) and ghost tracks (about 0.75 per step) remain; count error looks small partly because missed hostiles cancel ghosts.
- Clutter: without a useful behaviour signal, birds and vehicles are counted as hostiles (38 % of clutter time) and attract drones. The behaviour module claims no bird or vehicle recognition.
- Investigation does not identify anything yet (the estimator does not read camera class hints); the stand-in dispatcher wastes many flights on ghosts and leaves a patrol gap.
- Friendlies are flagged at 90 % loss when beacons disappear.
- Tracker is 2D and uses readings at arrival time by default. Optional central `--oosm` replays late readings; distributed replay, time sync, sensor bias and GNSS-denied pose estimation remain open. Clock offset/drift affects Python beacons, while native sensor observation timestamps remain ideal; full sensor-clock degradation is untested. All `TrackerConfig` values are assumptions.
- Weather affects sensors but does not change the tracker; catalog and weather numbers are assumptions, mostly unverified (only 3 of the catalog's datasheet entries are verified). Combined weather is a worst-case multiplication.
- Behaviour thresholds for pursuit and intercept risk are simulation assumptions, and scores are not calibrated probabilities. No protected zone or default corridor is configured.
- No CI and no formatter.

Tests: `python -m unittest discover -s seeder/tests`, `python seeder/seed_catalog.py --check`, `python -m pytest`, and the `node ui/viewer/test-*.js` files.
