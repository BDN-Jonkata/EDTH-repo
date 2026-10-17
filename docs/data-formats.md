# Data formats

The JSON that the seeder produces and the other modules read. If you are an agent working on another module, start here. Each part says which file defines it, so check the file when in doubt.

## Conventions

- Area: a 1000 m x 1000 m square. `x` is east, `y` is north, in metres, origin at the south-west corner. `z`/altitude is metres above ground.
- Time is seconds from the start of the run (`t = 0`). Velocities are m/s.
- Angles: `bearing_deg`, `azimuth_deg` and `heading_deg` are compass degrees, 0 = north, clockwise. A friendly's `loop.th0` is a maths angle in radians (0 = east, counter-clockwise) because it is used in `cos`/`sin`.
- IDs: friendlies `F1..F5`, ground sensors `GS1..GS2`, hostiles `H1..Hn`, non-allied benign drones `N1..Nn`, the fusion node `C2`. These prefixes are seeder conventions, never estimator features.
- A scenario is fully determined by its config and `seed`. Same input, same output.

## Where the data comes from

| What | Made by | Read it from |
|------|---------|--------------|
| Sensor modules and platform models | hand-edited catalog | [seeder/catalog/](../seeder/catalog/) (JSON), or the PostgreSQL tables of the same names |
| Scenario configs (presets) | hand-edited | [scenarios/](../scenarios/) |
| `scenario.json` (what the system may read) | `python seeder/generate.py scenarios/hard.json --seed 3` | `out/<id>/scenario.json`, or `seeder/scenario.py` `generate(config)` |
| `truth.json` (scoring only) | same command | `out/<id>/truth.json` |
| Every seed of a set (a sweep) | `python seeder/generate.py scenarios/hard.json --sweep tuning` | `out/<preset>-sweep-tuning/`, see "Sweep folders" below |
| A saved simulation run | `node ui/viewer/export-run.js` | PostgreSQL table `simulations`, or `seeder/data/db-dump.json.gz` |
| Track, beacon and investigation messages | the tracker, the beacon source and `friend_foe/` (hand-made example in [friend_foe/data/local_tracks.jsonl](../friend_foe/data/local_tracks.jsonl)) | JSON Lines, see "Track and investigation messages" below |

Load everything from the dump into your own database with `python seeder/dump.py import` (see [seeder.md](../seeder/seeder.md)).

**Rule:** only the scoring module may read `truth.json`. The tracker, fusion, friend/foe and predictor read `scenario.json` and the sensor messages, never the truth.

## scenario.json (`edth.scenario/1`)

Top level: `schema`, `id` (for example `hard-s3`), `name`, `seed`, `preset`, `description`, `duration_s`, `area.size_m`, `c2` (`[x, y]`), then:

| Key | Content |
|-----|---------|
| `friendlies[]` | `id`, `platform` (catalog id), `altitude_m`, `loop` = circular patrol `{cx, cy, R, v, dir (+1/-1), th0}`, `sensors[]` = `{module, kind}` resolved from the catalog |
| `ground[]` | `id`, `platform`, `position` `[x, y]`, `heading_deg`, `sensors[]` |
| `commands[]` | tasking sent from C2 to friendly drones during the run, sorted by `t`: `{t, drone_id, command, target?, speed_mps?, heading_deg?, face_target?, track_id?}`. Empty by default. See "Drone commands" below |
| `targets[]` | non-allied drones: `id`, `role` (`hostile` or `benign`, default `hostile`), `motion`, `speed_mps`, `altitude_m`, `waypoints` = `[[t, x, y], ...]` (straight lines between them), `wobble_m`, `phase`, `signature` (how well each sensor type sees it: `eo`, `thermal`, `acoustic`, `rf`, `radar`), `emits` (false = silent, invisible to RF). Role and future paths are simulation/scoring inputs, excluded from behavioral inference |
| `clutter[]` | birds and vehicles: real objects the sensors see that are **not threats**. Same fields as `targets[]` plus `type` (`bird` or `vehicle`) and `role: "clutter"`; `emits` is always false. Empty by default |
| `beacon` | friendly position beacons: `enabled`, `rate_hz`, `pos_sigma_m` |
| `sensor_set.enabled_kinds` | which sensor kinds exist in this run |
| `environment` | `weather` (`clear`, `fog`, `rain`, `wind`, `night`, or a combination, see [Weather combinations](#weather-combinations-and-weather-events)), `time_of_day`, optional `weather_events[]` and `sky`, `clutter` = `{false_alarms_per_min, birds, vehicles}` (the last two are object counts, 0 to 10) |
| `degradations` | `clock`, `pose`, `network` (`loss`, `burst`, `latency_ms`, `out_of_order`, `topology`, `bandwidth_kbps`, see [Bandwidth limits](#bandwidth-limits), `jamming_zones[]`, see [Jamming zones](#jamming-zones)), `dropout[]` = `{node, t}` |
| `config` | the config that produced it |

A hostile's (or clutter object's) position at time `t`: walk the waypoints linearly, then add a sideways wobble of amplitude `wobble_m` that fades to zero near each waypoint. The exact formula is `target_state` in [seeder/scenario.py](../seeder/scenario.py); do not rewrite it, import it.

Viewer-only `config.traffic_behaviors[]` entries `{id, ally, mode, start_s}` override
the named target's path after its actor start (`mode`: `follow` or `intercept`).
They react to flown friendly trajectories; flags never control them. Use recorded
viewer truth for these actors, as for commanded friendlies, rather than the
seeder's scripted baseline. This metadata never crosses the inference boundary.
Viewer run exports include `behaviorConfig` and `estimatorConfig`; the latter
contains the actual identity/risk thresholds displayed in track details.

### Bandwidth limits

`degradations.network.bandwidth_kbps` = `null` (no cap, the default) or a number above 0: what each node's link to C2 can carry, in kilobits per second. A message occupies the link for its size divided by the rate, one after another, so a link never delivers more than the cap in any window. Messages wait in order; when more than 2 s of data are waiting (an assumed number), the **oldest** waiting messages are dropped. A message the channel later loses (base loss or a jamming zone) still used its airtime. Size is the length of the message as JSON without the mock-only `z` and `arr`, unrounded, so it is an upper bound: today about 410 bytes for an `observation` and 275 for a `friendly_beacon`; the codec's float rounding will lower that. In the `challenge` preset the nodes send about 4 to 15 kbit/s each, and the radar-and-RF ground sensor `GS2` about 45; with a 32 kbit/s cap about 13 % of the messages are dropped, with 8 kbit/s about 55 %. Commands from C2 to a drone share that drone's link. The mock applies the cap in Realistic mode only; a run with a cap has a `bandwidth` entry in its result, `{type: {count, bytes, avg_bytes, dropped}}`, and a run without one has none. The seeder only checks the value; the rule is built in [ui/viewer/linkcap.js](../ui/viewer/linkcap.js) as a spec for the channel emulator.

### Jamming zones

`degradations.network.jamming_zones[]` = `{x, y, radius_m, loss, t_start?, t_end?, rf_noise_mult?}`: a circle of the map (metres) where, while active, the messages **sent by or to a node inside** lose more often. `loss` is the share lost, 0 to 1, and a message uses the higher of the base `network.loss` and the loss of every active zone the node is in (overlapping zones: the highest). `t_start` defaults to 0 and `t_end` to the end of the run (`t_end` must be after `t_start`). `rf_noise_mult` (at least 1, default 1) multiplies the noise of RF receivers inside the zone. Membership uses the node's true position and the true time, not its drifted clock, so a drone that flies in and out is jammed only while inside; for a command from C2 the node is the receiving drone. Beacons are lost like every other message, which is what friend/foe must survive: silence alone is not proof of hostility. The seeder only checks and passes the zones on (they do not change any path); the mock simulation applies them in Realistic mode only, since they are a comms degradation. The numbers are assumptions.

### Weather combinations and weather events

Supported by the seeder validator (it passes `weather`, `weather_events` and `sky` through to `scenario.json` unchanged, and checks them with [sensors/weather.py](../sensors/weather.py)) and by the viewer ([ui/viewer/weather.js](../ui/viewer/weather.js), a port checked against the shared cases below). A single weather (`fog`) keeps working unchanged.

| Where | Form | Meaning |
|-------|------|---------|
| `environment.weather` | `fog+wind` | several anomalies at once |
| | `rain:0.6+wind` | `:s` = strength from above 0 to 1 (default 1); the catalog multiplier moves that share of the way towards 1 |
| `environment.time_of_day` | `night` | the simple form: adds the night effect at full strength, counted once even if `weather` also says night. Ignored when `environment.sky` is present |
| `environment.sky` | `{date, hour, lat, lon, utc_offset_h?, time_scale?}` | how dark it is, from the date, the clock time and the place, so it follows the season: `date` = `YYYY-MM-DD`; `hour` = local clock time at t = 0 (0 to under 24); `lat`, `lon` in degrees, all four required because the place and date decide how long the day is; `utc_offset_h` defaults to the offset that matches `lon`; `time_scale` = clock seconds per simulated second (default 1, so a 120 s run barely moves the sun; use 60 to cross sunset in a run) |
| `environment.weather_events[]` | `{weather, t_start?, t_end?, zone?: {x, y, radius_m}}` | an anomaly that comes and goes, and may cover only a circle of the map; on top of the base weather, overlapping events all apply with the strongest strength of each effect |

Lookup rule: weather is looked up **per detection** (time and position), not once per run. A detection sees the strongest strength of each effect at the sensor's position and at the target's (`conditions_between` in [sensors/weather.py](../sensors/weather.py)), so a fog bank over either end of the line of sight counts. The viewer agrees with the shared cases in [sensors/testdata/weather_cases.json](../sensors/testdata/weather_cases.json), which the Python code generates (`python -m sensors.golden`).

Why a sky and not a fixed night: the length of the day depends on the season and the latitude (at 45 N about 15.6 h of daylight in June and 8.8 h in December, at 60 N 18.9 h and 5.9 h), so the same 21:00 is night in December and still dusk in June, and near 60 N a June night never gets fully dark. The sun's height above the horizon comes from the standard NOAA approximation ([sensors/daylight.py](../sensors/daylight.py)). The night strength is 0 with the sun above the horizon and rises linearly through twilight to 1 at 12 degrees below it; that mapping is a placeholder, since the catalog has one `night` multiplier for full darkness. Moon and cloud cover are ignored.

Effect on sensors: each active effect scales a module's range, noise and detection probability by its catalog `weather_effects` entry, and the effects **multiply**. That is a worst-case assumption for range (real extinctions add, which is milder), so a combination is never better than its worst member. Catalog numbers are assumptions unless `verified`.

Why it matters: `seed_catalog.py --check` tests single weathers only. In combination some platforms lose every working detection module (a camera is hurt by fog, a microphone by wind, so `mini4pro` has nothing left in fog and wind together). Run `python -m sensors.report` for the table.

## truth.json (`edth.truth/2`)

```
{ "scenario_id", "seed", "duration_s", "dt_s": 0.1,
  "columns": ["t", "x", "y", "vx", "vy"],
  "objects": [ { "id": "H1", "kind": "hostile|friendly|benign|clutter", "altitude_m": 45.0,
                 "samples": [[t, x, y, vx, vy], ...] } ],   -- a clutter object also has "type": "bird|vehicle"
  "events":  [ {"type": "enter|exit", "id", "t"},
               {"type": "crossing", "a", "b", "t", "sep_m", "x", "y"} ] }
```

Positions are rounded to 0.1 m, velocities to 0.01 m/s. A hostile or clutter object has samples only while it is inside the area. Events are about hostiles only. Scoring: a hostile track on a clutter object is a false alarm, not a missed hostile.

## Sweep folders

`--sweep tuning` (seeds 1 to 99) or `--sweep test` (seeds 1000 to 1099) generates every seed of a set from one config. `--count N` limits it to the first N seeds for a quick check. It writes:

```
out/<preset>-sweep-<set>/
  index.json          { "seed_set": "tuning", "runs": [ <run.json of every seed> ] }
  <seed>/
    scenario.json     what the system may read (the same file a single run makes)
    truth.json        for scoring only
    run.json          { "scenario_id", "seed", "seed_set", "index", "hostiles", "benign", "crossings" }
```

A run is scored from its `truth.json` and the track messages the system produced for that scenario, for example `python -m scoring.run out/<preset>-sweep-tuning/1/truth.json tracks.jsonl`. `truth.json` holds the scripted patrol of the friendly drones: when a run commands them off it, score against the trajectories the run recorded (`scoring.truth.with_recorded_samples`). The simulation and scoring are not run by the sweep. About 0.3 s and 0.3 MB per seed at the default 0.1 s truth step, so a full set is about 30 MB (the `out/` folder is git-ignored). The test set is run once, at the end: never tune on it.

## Catalog

`sensor_modules.json` is a list of modules; each has:

- `id`, `kind` (`eo_camera`, `thermal_camera`, `microphone`, `rf_receiver`, `radar`, `gnss`, `imu`), `name`
- `sim`: `range_m`, `ident_range_m` (how close an object must be to be identified, assumed), `min_range_m`, `fov_deg`, `pointing` (`forward` or `omni`), `pd`, `pd_far`, `rate_hz`, `latency_ms`, `noise` per field
- `native`: what the module really reports, as `type` plus `fields[]` (`name`, `unit`, `desc`)
- `weather_effects`: `fog`, `rain`, `wind`, `night`, each with `range_mult`, `noise_mult`, `pd_mult`
- `verified`: true only when the numbers come from an official datasheet. Everything else is an assumption.

`native.type` says which message a module sends:

| `native.type` | Fields | Modules |
|---------------|--------|---------|
| `bearing_elevation` | `bearing_deg`, `elevation_deg`, plus `class_hint` (camera) or `intensity` (thermal) | cameras |
| `level` | `level_db`, `presence` | single microphone |
| `bearing_level` | `bearing_deg`, `level_db`, `presence` | microphone array |
| `bearing_rssi` | `bearing_deg`, `rssi_dbm`, `center_freq_mhz` | RF receiver |
| `range_azimuth_doppler` | `range_m`, `azimuth_deg`, `radial_mps`, `snr_db` | radar |

A camera never gives range, a single microphone never gives a bearing. The tracker must work from these native fields, not from positions.

`platform_models.json`: each platform has `id`, `name`, `platform` (`uas` or `ground`), `cost_tier`, `spec`, and `modules[]` = `{module_id, mount, count}`.

Every UAS has `spec.flight` = `{max_speed_mps, max_accel_mps2, max_turn_dps, assumed: true}`: the limits for commanded motion. `max_accel_mps2` limits the change of speed, `max_turn_dps` the change of course. These numbers are **assumed**, not from datasheets.

## Messages

Everything that crosses the channel is a message with a top-level `type` and a `header`, as in [common/codec.py](../common/codec.py):

| Header field | Meaning |
|--------------|---------|
| `msg_id` | `<source_id>-<seq>`, unique in a run |
| `source_id` | the sending node: `F1`..`F5`, `GS1`, `GS2`, or `C2` |
| `t_sent` | seconds, on the sender's own clock (it drifts when the run has clock drift) |
| `seq` | counts up by one per source, from 1 |
| `schema_version` | `1` |

`observation` (a node's sensor saw something; one per detection):

| Field | Meaning |
|-------|---------|
| `sensor_type` | the module's catalog `kind`: `eo_camera`, `thermal_camera`, `microphone`, `rf_receiver`, `radar` |
| `sensor_id` | the module's catalog `id`; the node carrying it is `header.source_id` |
| `t_obs` | when the sensor saw it, on the node's clock (the mock sends at once, so it equals `t_sent`) |
| `kind` | `bearing` (cameras, microphone array, RF), `range_bearing` (radar) or `detection` (a single microphone: only how loud) |
| `value` | the module's native fields, as in the `native.type` table above; angles are compass degrees |
| `cov_fields`, `covariance` | the noisy fields of `value`, in order, and their covariance matrix (noise is independent, so it is diagonal; units are the field's unit squared) |

`friendly_beacon` (a friendly drone reports its own position; read by [friend_foe/jsonl_io.py](../friend_foe/jsonl_io.py)):

| Field | Meaning |
|-------|---------|
| `friend_id` | `F1`..`F5`, same as `header.source_id` |
| `position` | `[x, y, z]` metres, with the beacon noise (`beacon.pos_sigma_m`); taken at the drone's own clock, so drift shows up as a position error |
| `velocity` | `[vx, vy, vz]` m/s |
| `covariance` | 3 × 3 position covariance |

## Drone commands

Friendly drones fly their scripted patrol loop until commanded. Commands and acks are ordinary messages over the lossy channel, with the header above.

`drone_command` (C2 to a drone):

| Field | Meaning |
|-------|---------|
| `command_id` | Unique per command. The sender repeats a command with the same id until it is acknowledged; the drone answers a repeat without carrying the command out twice |
| `drone_id` | `F1`..`F5` |
| `command` | `goto` (fly to `target` and then hold), `hold` (stop where it is), `return_to_patrol` (rejoin the scripted loop where it is now) |
| `target` | `[x, y, z]` for `goto`. Inside the 1000 m area; `z` is ignored (the drone keeps its altitude) |
| `speed_mps` | optional cap, never above the platform's `max_speed_mps` |
| `heading_deg` or `face_target` | optional camera direction for `goto` and `hold`: a compass heading (0 = north, clockwise) or an `[x, y]` point to keep facing, also while flying. `face_target` wins. Without either the heading follows the direction of travel, and a stopped drone keeps its last heading |
| `track_id` | optional, the track being investigated; echoed in `drone_state` |

`drone_state` (drone to C2): the ack of a command and later progress.

| Field | Meaning |
|-------|---------|
| `drone_id`, `command_id` | which drone, answering which command |
| `state` | `accepted` or `rejected` (the ack, with `reason`), then `on_station` (reached the `goto` point, or stopped on `hold`) and `patrolling` (back on the loop) |
| `mode` | what the drone is doing now: `patrol`, `goto`, `hold` or `return` |
| `position` | `[x, y, z]` |
| `heading_deg` | where the camera points (compass degrees) |
| `track_id`, `reason` | optional |

Retries: the sender repeats an unacknowledged command every 1.5 s, at most 5 times in all (assumed values), then reports it lost. `on_station` and `patrolling` are sent once and repeated twice, 2 s apart, because a state message has no ack of its own.

`drone_state` can serve as `investigation_status`: `accepted` = `assigned`; `mode` `goto` or `return` = `en_route`; `on_station` = `on_station`; `patrolling` after the investigation = `done`; `rejected` or a command reported lost = `aborted`.

Today the mock simulation ([ui/viewer/sim.js](../ui/viewer/sim.js), header in [messages.js](../ui/viewer/messages.js), motion maths in [drones.js](../ui/viewer/drones.js)) sends all four message types. `truth.json` is the scripted baseline: when a scenario has commands it carries `scripted_baseline_only: true`, and scoring must use the truth recorded by the run (`frames[].truth`), which follows the commanded motion. The run result lists every command as `commands`: `{command_id, drone_id, command, t_issued, attempts, t_acked, status (accepted, rejected, lost), reports}`.

## Saved simulation run (`simulations` table, `export-run.js` output)

`{ params, scenario, result }`, where `result` has `frames`, `alerts`, `timeline`, `summary`, `sensors`. Frames are one per 0.1 s (`k`, `t`, `meas`, `tracks`, `truth`, `links`, `m` = metrics). `summary` = `{rmse, countErr, swaps, ffa}` (`ffa` = friendlies flagged hostile), plus `cfa` (clutter objects tracked as hostile) when the scenario has clutter. In `meas`, `clutter: true` marks a random false alarm, not a detection of a clutter object.

To save space, numbers are rounded and a list of same-shaped objects is stored as `{"cols": [...], "rows": [[...]]}`. Read it back with `unpack()` from [seeder/tables.py](../seeder/tables.py):

```python
from tables import unpack
result = unpack(run["result"])
result["frames"][600]["tracks"][0]["x"]
```

This run comes from the mock simulation in the viewer. Treat its tracks as an example of the shape, not as a reference tracker.

## Track and investigation messages (draft, JSON Lines)

Drafts for the tracker, friend/foe and drone-behaviour modules. Not yet confirmed by the tracker and drone-behaviour owners; change them here and in the code together. Messages are one JSON object per line. Encode and decode with `encode` / `decode` in [common/codec.py](../common/codec.py), which today is JSON and can later become a compact binary format without changing the messages.

Every message has the top-level `type` and the `header` described in [Messages](#messages), for example `"header": { "msg_id": "node1-12", "source_id": "node1", "t_sent": 12.5, "seq": 12, "schema_version": 1 }`. `decode` rejects a message with a missing `type` or header field or a different `schema_version`. Positions are `x` east, `y` north, `z` altitude, in metres, as in Conventions above.

| `type` | Sent by | Fields besides `header` |
|--------|---------|-------------------------|
| `local_track` | tracker | `local_track_id`, `t_state`, `state` = `[x, y, z, vx, vy, vz]`, `covariance` (6x6), `existence_prob`; optional `class`, `class_prob` |
| `friendly_beacon` | friendly drone | see [Messages](#messages). Rate and noise come from `scenario.json` `beacon` (`rate_hz`, `pos_sigma_m`) |
| `investigation_request` | `friend_foe/` | `track_id`, `position`, `covariance` (3x3), `class_prob`, `priority`, `t_requested`, `standoff_m`, `standoff_by_module`, `weather_confidence`, `feasible` |
| `investigation_status` | drone behaviour | `track_id`, `drone_id`, `state` = `assigned`, `en_route`, `on_station`, `done` or `aborted` |

Track classes: `friendly`, `hostile`, `suspicious`, `peaceful`, `unknown`. A class always comes with a probability and is a presumption, never a deletion.

| Class | Meaning |
|-------|---------|
| `friendly` | ally: confirmed by its beacon or identity |
| `hostile` | enemy: positive behaviour evidence |
| `suspicious` | not identified, probably an enemy; worth investigating |
| `peaceful` | not identified, probably not an enemy (for example it keeps away from friendlies and moves steadily); still watched, not an ally |
| `unknown` | not identified, no evidence either way |

`peaceful` is the mirror of `suspicious`: both are leanings, not identifications. It needs positive behaviour evidence (never silence alone, because beacons can be jammed), it is dropped back to `unknown` or raised to `suspicious` when the behaviour changes, and it never stops a track from being tracked or counted. Any thresholds for it are assumptions. Neither the mock simulation nor the scenario generator produces it yet; it comes from the estimator.

`investigation_request.standoff_by_module` maps a catalog module id to `{max_range_m, recommended_m, confidence, feasible}`: how close a drone carrying that module must get to identify the object in the current weather. Pick the entries of the modules the chosen drone carries (`scenario.json` `friendlies[].sensors[].module`). `standoff_m` and `feasible` summarise the best module. The numbers are derived from the catalog, so they are assumptions unless the catalog says `verified`.

Rules the estimator follows: a request is only raised for `suspicious` tracks, never for confirmed hostiles; one request per track at a time, with a cooldown; `hostile` needs positive behaviour evidence, silence alone gives `suspicious` because beacons can be jammed.
