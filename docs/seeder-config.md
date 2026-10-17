# Seeder config

Back to [README](../README.md) · See also [Concept](concept.md), [System design](system-design.md), [seeder module](../seeder/seeder.md)

> Status: **implemented** in [seeder/scenario.py](../seeder/scenario.py) (`python seeder/generate.py`). Presets live in [scenarios/](../scenarios/). Clutter objects (birds, vehicles) are generated and simulated by the mock. Not yet generated: moving ground units; bandwidth limits are accepted in the config but not simulated yet. Jamming zones are checked by the generator and applied by the mock.

Every scenario is fully defined by **one JSON config plus a seed**, so any run can be reproduced. The seeder turns the config into a scenario (nodes, targets, environment, degradations) and a separate ground-truth file.

## 1. Rules

- **Reproducible:** same config + same seed = identical run. Sensor noise, network and clutter use separate random streams so changing one does not change the others.
- **Ground truth is a separate file** (`truth.json`) that the tracker and fusion never read. Only scoring reads it.
- **Separate seed sets:** tuning seeds 1-99, final-test seeds 1000-1099. Never tune on the test seeds.
- **Plain JSON out:** scenario, truth and results are JSON, so the same files drive the simulation, the scoring and the demo, and can be stored as JSONB in PostgreSQL.
- **Platforms come from the catalog** (`seeder/catalog/`): a config names a platform id and gets its sensor modules.

## 2. Config sections

```json
{
  "name": "medium-crossing",
  "seed": 42,
  "preset": "medium",
  "duration_s": 120,
  "area": {"size_m": 1000, "terrain": "village-01", "terrain_shadowing": true},

  "targets": [
    {"id": "H1", "role": "hostile", "speed_mps": [8, 25], "altitude_m": [20, 120],
     "motion": "waypoints", "enter_t": 6, "exit_t": null,
     "hover_prob": 0.1, "sudden_turn_prob": 0.05,
     "signature": {"eo": 1.0, "thermal": 0.8, "acoustic": 0.7, "rf": 1.0, "radar": 0.6}}
  ],

  "friendlies": {
    "platforms": ["mini4pro", "anafi_thermal", "px4_quad_passive", "px4_quad_radar", "skydio_x10"],
    "patrol": "loops",
    "beacon": {"enabled": true, "rate_hz": 2, "pos_sigma_m": 3}
  },
  "ground": [
    {"id": "GS1", "platform": "gs_eo_acoustic", "position": [300, 300]},
    {"id": "GS2", "platform": "gs_radar_rf", "position": [655, 460]}
  ],
  "sensor_set": {"enabled_kinds": ["eo_camera", "thermal_camera", "microphone", "rf_receiver", "radar"]},

  "environment": {
    "weather": "fog:0.6+wind", "time_of_day": "day",
    "weather_events": [{"weather": "rain", "t_start": 40, "t_end": 90, "zone": {"x": 500, "y": 500, "radius_m": 200}}],
    "sky": {"date": "2026-06-21", "hour": 20.5, "lat": 50.45, "lon": 30.52, "time_scale": 60},
    "clutter": {"false_alarms_per_min": 2, "birds": 3, "vehicles": 1}
  },

  "degradations": {
    "clock":   {"enabled": true, "offset_ms": [0, 200], "drift_ppm": 50},
    "pose":    {"enabled": true, "position_err_m": 5, "heading_err_deg": 3, "drift": true},
    "network": {"enabled": true, "loss": 0.3, "burst": true, "latency_ms": [50, 400],
                "out_of_order": true, "topology": "mesh", "bandwidth_kbps": null, "jamming_zones": []},
    "dropout": [{"node": "F3", "t": 60}]
  },

  "outputs": {"scenario": "scenario.json", "ground_truth": "truth.json"}
}
```

| Section | Controls |
|---------|----------|
| `targets` | Speed and altitude ranges, motion style (straight, waypoints, loiter, hover, sudden turns, speed changes), entry and exit times (births and deaths), per-sensor-type signature (lower signature = lower detection probability at range), groups that fly close, cross or split |
| `friendlies` | Which catalog platforms, patrol pattern, whether they broadcast their own pose and uncertainty (beacon) |
| `ground` | Ground sensor platforms and positions. Also optional moving ground units that carry sensors or act as clutter |
| `sensor_set` | Which sensor kinds are switched on. Lets us run "camera + acoustic only" against "camera + radar" on the same seed |
| `environment` | Weather and time of day (change each module differently, see the catalog `weather_effects`). `weather` can combine anomalies (`fog+wind`, with a strength such as `rain:0.6`); `weather_events[]` are anomalies that come and go, over a zone of the map; `sky` makes night follow the date, hour and place (it replaces `time_of_day`). Formats and rules: [data-formats.md](data-formats.md#weather-combinations-and-weather-events). The generator does not use any of this, it only checks and passes it on; the viewer applies it. Also clutter, terrain line-of-sight shadowing (not yet). `clutter.false_alarms_per_min` is random radar false alarms; `clutter.birds` and `clutter.vehicles` are how many real non-threat objects cross the area (0 to 10 each, default 0) |
| `degradations` | Each has its own on/off and strength: clock offset and drift, node position and heading error, packet loss (random or bursty), latency, out-of-order delivery, node dropout |
| `network` | Topology (mesh or neighbours only), bandwidth limits, jamming zones where links degrade: `jamming_zones[]` = `{x, y, radius_m, loss, t_start?, t_end?, rf_noise_mult?}`, see [data-formats.md](data-formats.md#jamming-zones) |

Clutter objects (`CLUTTER_KINDS` in [seeder/scenario.py](../seeder/scenario.py), all numbers **assumed**) fly waypoint paths like hostiles and come from their own random stream, so adding them never moves the hostiles or friendlies:

| Type | Motion | Speed | Altitude | Signature (1.0 = a small drone) |
|------|--------|-------|----------|-------------------------------|
| bird | erratic: random waypoints, frequent sudden turns, 8 m wobble | 6-14 m/s | 10-60 m | weak: EO 0.6, thermal 0.5, acoustic 0.3, radar 0.3 |
| vehicle | a road across the area with one bend | 4-12 m/s | 1-2 m | strong: EO 1.3, thermal 1.5, acoustic 1.5, radar 1.5 |

Neither emits RF, so RF never sees them. The system must not call them hostile; the mock baseline does, and its summary counts that as `cfa`.

Per-sensor behaviour (field of view, max range, detection probability that falls with range, noise that grows with range, false-alarm rate, missed detections, sample rate, processing delay) comes from the catalog `sim` block, not the scenario config. The radar module carries a **resolution cell** (about 15 m in range by 3 degrees); two targets inside one cell merge into a single measurement, which is what makes the crossing hard.

## 3. Presets

| Preset | Targets | Sensors | Degradations |
|--------|---------|---------|--------------|
| easy | 1 hostile | 5 drones + 2 ground, clean | none |
| medium | 2-3 hostiles, one close crossing | full set | moderate noise, 10-20 % loss |
| hard | up to 5 hostiles, close crossings, hover | full set | 40 % bursty loss, clock drift, pose error, one node dropout |
| challenge | the task scenario: 5 drones, 2 ground sensors, 2 hostiles crossing, about 1 km² | full set | tuned for the graded loss sweep |

## 4. Open questions for the mentor

- Do friendly drones broadcast their own pose, and with what uncertainty? (Our friend/foe design depends on it.)
- Is radar available to us as a simulated sensor, or only as provided hardware? We keep it in the model either way and make the sensor set switchable.
- What are the real specs of the sensors the organisers provide? All numbers in the catalog are assumed starting points.
- What are the ground units: sensor carriers, clutter, or both?
