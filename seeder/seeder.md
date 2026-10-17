# seeder module

Generates realistic scenario components (friendly drones, ground sensors, hostile drones, terrain) from a scenario definition, and holds the **catalog of platforms and sensor modules** they are built from.

Status: catalog, PostgreSQL storage and the scenario generator are done. See [system design](../docs/system-design.md) and [seeder config](../docs/seeder-config.md).

## Catalog

Real, cheap platforms with different sensor loadouts, so weather can be shown to hit different modules differently.

| Platform | Modules (detection) | Class |
|----------|--------------------|-------|
| `mini4pro` DJI Mini 4 Pro class | EO camera + microphone | UAS, low cost |
| `anafi_thermal` Parrot ANAFI Thermal | EO camera + thermal (Lepton 160x120) | UAS, mid |
| `px4_quad_passive` DIY PX4 quad | RF receiver + 4-ch mic array | UAS, low |
| `px4_quad_radar` DIY PX4 quad | small radar + basic camera | UAS, low |
| `skydio_x10` Skydio X10 (reference) | EO + thermal (Boson+ 640x512) + microphone | UAS, high |
| `gs_eo_acoustic` | basic camera + mic array | ground |
| `gs_radar_rf` | small radar + RF receiver | ground |

Every UAS also carries `gnss_basic` and `imu_basic`.

Files:

- [catalog/sensor_modules.json](catalog/sensor_modules.json): per module the manufacturer `spec`, the numbers the simulation uses (`sim`), output fields, and `weather_effects` (fog / rain / wind / night multipliers on range, noise and detection probability).
- [catalog/platform_models.json](catalog/platform_models.json): which modules each platform carries.

**Data quality:** `verified: true` means the `spec` was read from an official datasheet (only the Skydio X10 camera/thermal and the Parrot Lepton thermal so far). Everything else is `verified: false` with a source or note. The `sim` numbers and all `weather_effects` are **assumed starting points to tune**, not measurements.

## Sharing the database

The data in your database travels through git as [data/db-dump.json.gz](data/db-dump.json.gz): catalog, generated scenarios and saved simulations.

```
python seeder/dump.py export    # you: refresh the dump after saving new scenarios or runs, then commit it
python seeder/dump.py import    # teammates: create the schema and load everything (safe to repeat, no duplicates)
```

A teammate needs PostgreSQL, a database, `DATABASE_URL` in `.env`, and `pip install -r seeder/requirements.txt` first.

## Scenario generator

One config plus a seed gives the same scenario every time. [scenario.py](scenario.py) writes:

- `scenario.json`: what the system may read (friendly patrols with their platforms, ground sensors, hostile waypoint paths with signatures, environment, degradations, the resolved sensors per node).
- `truth.json`: ground truth, sampled positions of every object plus events (enter, exit, close crossings). For scoring only; the tracker never reads it.

What it generates: friendly patrol loops, hostile paths (`straight`, `waypoints`, `loiter`, `hover`, `mixed`, sudden turns, entry and exit times), and a planned close crossing between the first two hostiles at a chosen time and separation. Targets, friendlies and ground sensors use separate random streams, so changing one does not move the others. The config is validated (platforms must exist and be the right type, seeds must belong to the named seed set, loss between 0 and 1, and so on).

`targets.benign_count` reserves part of the total for non-allied benign drones on
an independent random stream. They fly transits, off-site orbits or hover without
friendly beacons. The busy preset mixes four of these with four threat scenarios;
`targets.behavior_demo` gives its non-crossing threats protected-area loiter/hover.
These are physical paths and scoring roles, never forced estimated flags. See
[config options](../docs/seeder-config.md) and [behavior rules](../drone_behavior/drone_behavior.md).

```
python seeder/generate.py scenarios/hard.json --seed 7        # -> out/hard-s7/
python seeder/generate.py scenarios/hard.json --sweep tuning    # every seed of a set -> out/<preset>-sweep-tuning/<seed>/
python seeder/export_scenarios.py                              # refresh ui/viewer/scenarios.js
python seeder/unverified.py                                    # worksheet of catalog numbers still to verify
python -m unittest discover -s seeder/tests -v                 # 21 tests
```

Commands: a config may list `commands` (goto, hold, return_to_patrol for a friendly drone at time `t`, with optional speed cap and camera direction). The scenario carries them sorted; the simulation sends them over the channel. The generator's own `truth.json` stays the scripted baseline and is marked `scripted_baseline_only`. Every UAS in the catalog has assumed flight limits (`spec.flight`) used for commanded motion. Message formats: [data-formats.md](../docs/data-formats.md#drone-commands).

The viewer's simulation uses the same motion maths; a test run showed the generator's truth and the simulation's truth agree to within 0.01 m.

## Sensor limits and native output

Each detection module in the catalog says what it can see and what it reports (`sim` and `native` in [sensor_modules.json](catalog/sensor_modules.json)):

| Module type | Range window | Field of view | Reports (native) |
|-------------|--------------|---------------|------------------|
| Visible camera | 3 m up to 150-250 m | 62-93 degrees, forward | bearing, elevation, class hint (friendly/unknown). **No range** |
| Thermal camera | 3 m up to 120-300 m | 41-57 degrees, forward | bearing, elevation, heat intensity. **No range** |
| Microphone array | 0 to 150 m | 360 degrees | bearing, sound level |
| Single microphone | 0 to 60 m | 360 degrees | sound level only; range is estimated from loudness |
| RF receiver | 0 to 300 m | 360 degrees | bearing, signal strength, frequency; only emitters |
| Small radar | 10 m up to 400 m | 90 degrees, forward | range, azimuth, radial speed; close targets merge in a 15 m x 3 degree cell |

Common limits: detection probability falls from `pd` at close range to `pd * pd_far` at max range, a sample rate, a processing latency, and per-field noise. Drones point their forward sensors along the flight direction; ground sensors along their mast. Weather multiplies range, noise and detection probability (`weather_effects`). The check (`seed_catalog.py --check`) requires all of these fields.

## Check and load (Python)

```
pip install -r seeder/requirements.txt
python seeder/seed_catalog.py --check    # validate, no database needed
```

`--check` enforces: every UAS has at least 2 different detection modalities, every weather has at least one module that still works, ids are consistent. It prints a table of which modules survive which weather.

## PostgreSQL

Tables: `sensor_modules`, `platform_models`, `platform_model_modules`, `simulations` (plain JSONB), view `platform_loadouts`. Schema: [db/schema.sql](db/schema.sql).

```
createdb -U postgres edth
cp .env.example .env                    # repo root; then put your real password in .env (git-ignored)
python seeder/seed_catalog.py           # create schema + load catalog

node ui/viewer/export-run.js --seed 4127 --weather fog --mode realistic --loss 30 > run.json
python seeder/save_simulation.py run.json --name "Fog, 30% loss"
```

A saved run is `params`, `scenario` and `result` (frames, alerts, timeline, summary) as JSON; one 120 s run is about 4.5 MB.

## Viewer export

`python seeder/export_catalog.py` writes `ui/viewer/catalog.js` from the catalog files, so the viewer can offer the platforms and use their sensor numbers.
