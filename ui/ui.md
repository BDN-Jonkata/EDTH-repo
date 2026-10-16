# ui module

Operator view / COP visualisation and simulation viewer.

Status: first working version in [viewer/](viewer/). See [system design](../docs/system-design.md).

## Simulation viewer (`viewer/`)

Implements the Claude Design mockup: map with terrain/height, layer toggles, track table, alerts, track detail, playback and metrics.

It is plain HTML/JS/CSS with no install step. It runs a **built-in mock simulation** (`sim.js`) that stands in for the real `seeder`, `simulation`, `sensors`, `tracker`, `fusion` and `friend_foe` modules until those exist. The whole 120 s scenario is computed up front (deterministic for a given seed) and then replayed, so playback can be scrubbed and stepped.

Run it:

```
cd ui/viewer
python serve.py
# open http://localhost:8000
```

`serve.py` is a static server that turns browser caching off, so a refresh always shows the latest files (plain `python -m http.server` can serve stale files). Opening `index.html` directly also works. Optional URL parameters: `?t=49.5` opens paused at that time, `?tab=deg` opens the degradation chart, `?weather=night` and `?seed=7` preselect those settings.

Scenarios: the **Preset** picker (easy, medium, hard, challenge) loads a scenario made by the seeder, and its weather, platforms and degradations become the starting settings. With `python serve.py`, the **Seed** field makes a new scenario for that preset (new hostile paths and patrols) when you press Apply & restart, through `/api/scenario?preset=hard&seed=7`. Opened as a file or with plain `http.server`, only the default seed of each preset is available (`scenarios.js`, made by `python seeder/export_scenarios.py`).

Commanded drones: the mock accepts `commands` from the scenario (or `params.commands`) and flies the drone under its platform's speed, acceleration and turn limits; commands and acks cross the same lossy channel, with retries. Motion maths is in `drones.js`; test with `node ui/viewer/test-commands.js`. The viewer has no control for sending commands yet.

Messages: every message the mock sends (`observation`, `friendly_beacon`, `drone_command`, `drone_state`) has the shared header from `messages.js`, with the fields in [docs/data-formats.md](../docs/data-formats.md#messages); test with `node ui/viewer/test-messages.js`.

What the mock does:

| Part | Mock behaviour |
|------|----------------|
| Scenario | Comes from the seeder: friendly patrols, ground sensors, a C2 node, hostile paths (straight, waypoints, loiter, hover, sharp turns) and a planned close crossing. A hostile's signature scales how well each sensor type sees it; silent hostiles are invisible to RF; nodes can drop out mid-run in realistic mode |
| Models per node | Each of the 7 nodes gets a platform from the catalog, chosen in the left panel ("Models per node"). Its sensor modules, ranges, noise and weather effects come from `catalog.js`. Press Apply & restart to run the seed with your choice |
| Sensors | Each module enforces its catalog limits (range window, field of view, pointing, detection probability that falls with distance, rate, latency) and reports only its native data: cameras give bearing + elevation (no range), a microphone array bearing + level, a single microphone only loudness, RF bearing + signal strength, radar range + azimuth + radial speed. Weather (clear, fog, rain, wind, night) scales range, noise and detection probability per module. Radar merges targets inside its 15 m x 3 deg resolution cell |
| Network | Per-message loss, delay and per-node clock drift in Realistic mode. Fusion is centralised at C2 (the hybrid design is not modelled yet) |
| Tracker | One extended Kalman filter per track that takes the native data as it comes (bearing, range, radial speed updates), nearest-neighbour gated association, tentative → confirmed → coasting → deleted. Radar starts a track alone; bearing-only sensors need two nodes to cross bearings; a track is confirmed only with range data or three viewpoints. This is a baseline, not the GNN/JPDA from the design |
| Friend/foe | Friendly beacons (ID + position at 2 Hz). Detections explained by a beacon are not counted as threats. No behaviour-pattern module yet |
| Predictor | Constant-velocity extrapolation only |
| Metrics | Count error, position RMSE, ID swaps, friendly false alarms, scored against ground truth |

Catalog data: `catalog.js` is generated, do not edit it. After changing `seeder/catalog/*.json` run `python seeder/export_catalog.py`.

Panels: **Sensor feed** shows the latest records the sensors reported (only their native fields), **Sensor limits** lists every sensor's range window, field of view, pointing, rate and output, and the map draws each sensor's real coverage (wedges for forward-pointing sensors, rings for 360-degree ones). Raw observations are drawn as sensors report them: a ray for bearing-only, a ring for range-only, a point for radar.

Map: it fills its whole panel; the dashed square is the 1 km x 1 km area of operations, and you can pan and zoom past its edge.

Not implemented from the design: the measure-distance tool, true line-of-sight terrain occlusion, separate raw bearing rays for acoustic, topology comparison.
