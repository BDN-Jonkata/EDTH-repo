# Data formats

The JSON that the seeder produces and the other modules read. If you are an agent working on another module, start here. Each part says which file defines it, so check the file when in doubt.

## Conventions

- Area: a 1000 m x 1000 m square. `x` is east, `y` is north, in metres, origin at the south-west corner. `z`/altitude is metres above ground.
- Time is seconds from the start of the run (`t = 0`). Velocities are m/s.
- Angles: `bearing_deg`, `azimuth_deg` and `heading_deg` are compass degrees, 0 = north, clockwise. A friendly's `loop.th0` is a maths angle in radians (0 = east, counter-clockwise) because it is used in `cos`/`sin`.
- IDs: friendlies `F1..F5`, ground sensors `GS1..GS2`, hostiles `H1..Hn`, the fusion node `C2`.
- A scenario is fully determined by its config and `seed`. Same input, same output.

## Where the data comes from

| What | Made by | Read it from |
|------|---------|--------------|
| Sensor modules and platform models | hand-edited catalog | [seeder/catalog/](../seeder/catalog/) (JSON), or the PostgreSQL tables of the same names |
| Scenario configs (presets) | hand-edited | [scenarios/](../scenarios/) |
| `scenario.json` (what the system may read) | `python seeder/generate.py scenarios/hard.json --seed 3` | `out/<id>/scenario.json`, or `seeder/scenario.py` `generate(config)` |
| `truth.json` (scoring only) | same command | `out/<id>/truth.json` |
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
| `targets[]` | hostiles: `id`, `motion`, `speed_mps`, `altitude_m`, `waypoints` = `[[t, x, y], ...]` (straight lines between them), `wobble_m`, `phase`, `signature` (how well each sensor type sees it: `eo`, `thermal`, `acoustic`, `rf`, `radar`), `emits` (false = silent, invisible to RF) |
| `clutter[]` | birds and vehicles: real objects the sensors see that are **not threats**. Same fields as `targets[]` plus `type` (`bird` or `vehicle`) and `role: "clutter"`; `emits` is always false. Empty by default |
| `beacon` | friendly position beacons: `enabled`, `rate_hz`, `pos_sigma_m` |
| `sensor_set.enabled_kinds` | which sensor kinds exist in this run |
| `environment` | `weather` (`clear`, `fog`, `rain`, `wind`), `time_of_day`, `clutter` = `{false_alarms_per_min, birds, vehicles}` (the last two are object counts, 0 to 10) |
| `degradations` | `clock`, `pose`, `network` (`loss`, `burst`, `latency_ms`, `out_of_order`, `topology`, `jamming_zones`), `dropout[]` = `{node, t}` |
| `config` | the config that produced it |

A hostile's (or clutter object's) position at time `t`: walk the waypoints linearly, then add a sideways wobble of amplitude `wobble_m` that fades to zero near each waypoint. The exact formula is `target_state` in [seeder/scenario.py](../seeder/scenario.py); do not rewrite it, import it.

## truth.json (`edth.truth/2`)

```
{ "scenario_id", "seed", "duration_s", "dt_s": 0.1,
  "columns": ["t", "x", "y", "vx", "vy"],
  "objects": [ { "id": "H1", "kind": "hostile|friendly|clutter", "altitude_m": 45.0,
                 "samples": [[t, x, y, vx, vy], ...] } ],   -- a clutter object also has "type": "bird|vehicle"
  "events":  [ {"type": "enter|exit", "id", "t"},
               {"type": "crossing", "a", "b", "t", "sep_m", "x", "y"} ] }
```

Positions are rounded to 0.1 m, velocities to 0.01 m/s. A hostile or clutter object has samples only while it is inside the area. Events are about hostiles only. Scoring: a hostile track on a clutter object is a false alarm, not a missed hostile.

## Catalog

`sensor_modules.json` is a list of modules; each has:

- `id`, `kind` (`eo_camera`, `thermal_camera`, `microphone`, `rf_receiver`, `radar`, `gnss`, `imu`), `name`
- `sim`: `range_m`, `min_range_m`, `fov_deg`, `pointing` (`forward` or `omni`), `pd`, `pd_far`, `rate_hz`, `latency_ms`, `noise` per field
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
