# seeder module

Generates realistic scenario components (friendly drones, ground sensors, hostile drones, terrain) from a scenario definition, and holds the **catalog of platforms and sensor modules** they are built from.

Status: catalog and PostgreSQL storage done; scenario generation not started. See [system design](../docs/system-design.md) and [seeder config](../docs/seeder-config.md).

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
