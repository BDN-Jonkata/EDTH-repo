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

What the mock does:

| Part | Mock behaviour |
|------|----------------|
| Scenario | 5 friendly drones on circular patrols, 2 ground sensors, C2 node, 2 hostiles that cross at about 13 m separation at t = 51 s |
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
