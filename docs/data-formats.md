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

Load everything from the dump into your own database with `python seeder/dump.py import` (see [seeder.md](../seeder/seeder.md)).

**Rule:** only the scoring module may read `truth.json`. The tracker, fusion, friend/foe and predictor read `scenario.json` and the sensor messages, never the truth.

## scenario.json (`edth.scenario/1`)

Top level: `schema`, `id` (for example `hard-s3`), `name`, `seed`, `preset`, `description`, `duration_s`, `area.size_m`, `c2` (`[x, y]`), then:

| Key | Content |
|-----|---------|
| `friendlies[]` | `id`, `platform` (catalog id), `altitude_m`, `loop` = circular patrol `{cx, cy, R, v, dir (+1/-1), th0}`, `sensors[]` = `{module, kind}` resolved from the catalog |
| `ground[]` | `id`, `platform`, `position` `[x, y]`, `heading_deg`, `sensors[]` |
| `targets[]` | hostiles: `id`, `motion`, `speed_mps`, `altitude_m`, `waypoints` = `[[t, x, y], ...]` (straight lines between them), `wobble_m`, `phase`, `signature` (how well each sensor type sees it: `eo`, `thermal`, `acoustic`, `rf`, `radar`), `emits` (false = silent, invisible to RF) |
| `beacon` | friendly position beacons: `enabled`, `rate_hz`, `pos_sigma_m` |
| `sensor_set.enabled_kinds` | which sensor kinds exist in this run |
| `environment` | `weather` (`clear`, `fog`, `rain`, `wind`), `time_of_day`, `clutter.false_alarms_per_min` |
| `degradations` | `clock`, `pose`, `network` (`loss`, `burst`, `latency_ms`, `out_of_order`, `topology`, `jamming_zones`), `dropout[]` = `{node, t}` |
| `config` | the config that produced it |

A hostile's position at time `t`: walk the waypoints linearly, then add a sideways wobble of amplitude `wobble_m` that fades to zero near each waypoint. The exact formula is `target_state` in [seeder/scenario.py](../seeder/scenario.py); do not rewrite it, import it.

## truth.json (`edth.truth/2`)

```
{ "scenario_id", "seed", "duration_s", "dt_s": 0.1,
  "columns": ["t", "x", "y", "vx", "vy"],
  "objects": [ { "id": "H1", "kind": "hostile|friendly", "altitude_m": 45.0,
                 "samples": [[t, x, y, vx, vy], ...] } ],
  "events":  [ {"type": "enter|exit", "id", "t"},
               {"type": "crossing", "a", "b", "t", "sep_m", "x", "y"} ] }
```

Positions are rounded to 0.1 m, velocities to 0.01 m/s. A hostile has samples only while it is inside the area.

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

## Saved simulation run (`simulations` table, `export-run.js` output)

`{ params, scenario, result }`, where `result` has `frames`, `alerts`, `timeline`, `summary`, `sensors`. Frames are one per 0.1 s (`k`, `t`, `meas`, `tracks`, `truth`, `links`, `m` = metrics).

To save space, numbers are rounded and a list of same-shaped objects is stored as `{"cols": [...], "rows": [[...]]}`. Read it back with `unpack()` from [seeder/tables.py](../seeder/tables.py):

```python
from tables import unpack
result = unpack(run["result"])
result["frames"][600]["tracks"][0]["x"]
```

This run comes from the mock simulation in the viewer. Treat its tracks as an example of the shape, not as a reference tracker.
