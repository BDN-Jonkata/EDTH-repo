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

Scenarios: the **Preset** picker (easy, medium, hard, challenge, busy) loads a scenario made by the seeder, and its weather, platforms and degradations become the starting settings. **busy** adds eight staggered drone entries with mixed flight patterns and clear conditions for watching automatic behavior (`?preset=busy`). With `python serve.py`, the **Seed** field makes a new scenario for that preset (new hostile paths and patrols) when you press Apply & restart, through `/api/scenario?preset=hard&seed=7`. Opened as a file or with plain `http.server`, only the default seed of each preset is available (`scenarios.js`, made by `python seeder/export_scenarios.py`).

Commanded drones: the mock accepts `commands` from the scenario (or `params.commands`); commands and acks cross the same lossy channel, with retries. `goto` and `hold` override autonomous assignments, and `return_to_patrol` resumes coordinated coverage. The mission controller moves all drones together under the platform flight limits and the shared separation, acceleration and sensor-yaw limits. Command validation and facing helpers live in `drones.js`; test with `node ui/viewer/test-commands.js`. The viewer has no control for sending commands yet.

Messages: every message the mock sends (`observation`, `friendly_beacon`, `drone_command`, `drone_state`) and local investigation contract event (`investigation_request`, `investigation_status`) has the shared header from `messages.js`, with the fields in [docs/data-formats.md](../docs/data-formats.md#messages); test with `node ui/viewer/test-messages.js`. Investigation events are currently delivered in process, while radio messages use the lossy channel.

Bandwidth: `degradations.network.bandwidth_kbps` (or the "Link cap per node" field in Comms impairments, empty = none) limits each node's link to C2 in Realistic mode. Messages queue in order, take their size divided by the rate, and the oldest are dropped when more than 2 s are waiting. The run result gets a `bandwidth` entry with bytes per message type. The rule is in `linkcap.js`; test with `node ui/viewer/test-bandwidth.js`.

Jamming: `degradations.network.jamming_zones` in the scenario are applied in Realistic mode. A node inside an active zone loses messages at least at the zone's rate, and RF receivers there are noisier. The map shows an active zone as a red dashed circle (with the Network links layer on). The maths is in `jamming.js`; test with `node ui/viewer/test-jamming.js`.

Weather: the left panel has toggles for fog, rain, wind and a fixed night, each with a strength, and a **sky** (date, hour with sunrise and sunset shown, latitude and longitude, clock seconds per run second) that makes night follow the season; the two combine. A scenario's `environment.weather_events` (fog bank over part of the map from t = 40 s) are applied too. Sensor quality is looked up per detection from the weather at the sensor and at the target, as in [docs/data-formats.md](../docs/data-formats.md#weather-combinations-and-weather-events). The maths is in `weather.js` (a port of `sensors/weather.py`, checked by `node ui/viewer/test-weather.js` against `sensors/testdata/weather_cases.json`); the controls are `weather-ui.js`. The place presets are examples; where the village is has not been decided. The Sensor limits table and drawn sensor wedges show the base weather. Patrol coverage history uses current weather events and the sky at each cell.

Clutter: birds and vehicles from `scenario.json` `clutter[]` move like hostiles and are seen through their signatures, but are not threats. The map shows them as grey dashed rings with their id; a hostile track on one raises a "Clutter ... tracked as hostile" alert and counts as `cfa` in the summary. Test with `node ui/viewer/test-clutter.js`.

What the mock does:

| Part | Mock behaviour |
|------|----------------|
| Scenario | Comes from the seeder: friendly patrols, ground sensors, a C2 node, hostile paths (straight, waypoints, loiter, hover, sharp turns) and a planned close crossing. A hostile's signature scales how well each sensor type sees it; silent hostiles are invisible to RF; nodes can drop out mid-run in realistic mode |
| Friendly missions | Patrol unvisited cells first, then oldest-observed cells, with shared destination reservations. After 3 s sustained suspicion, dispatch the closest suitable available drone at a weather-adjusted identification standoff, one follower per target. Search for 10 s after lost contact, then return to patrol; release identification assignments when assessment changes to friendly, peaceful or hostile |
| Models per node | Each of the 7 nodes gets a platform from the catalog, chosen in the left panel ("Models per node"). Its sensor modules, ranges, noise and weather effects come from `catalog.js`. Press Apply & restart to run the seed with your choice |
| Sensors | Each module enforces its catalog limits (range window, field of view, pointing, detection probability that falls with distance, rate, latency) and reports only its native data: cameras give bearing + elevation (no range), a microphone array bearing + level, a single microphone only loudness, RF bearing + signal strength, radar range + azimuth + radial speed. Weather (clear, fog, rain, wind, night) scales range, noise and detection probability per module. Radar merges targets inside its 15 m x 3 deg resolution cell |
| Network | Per-message loss, delay and per-node clock drift in Realistic mode. Fusion is centralised at C2 (the hybrid design is not modelled yet) |
| Tracker | One extended Kalman filter per track that takes the native data as it comes (bearing, range, radial speed updates), nearest-neighbour gated association, tentative → confirmed → coasting → deleted. Radar starts a track alone; bearing-only sensors need two nodes to cross bearings; a track is confirmed only with range data or three viewpoints. This is a baseline, not the GNN/JPDA from the design |
| Friend/foe | Verified roster/beacons establish identity. The automatic observed-motion baseline supplies a separate behavior score to the team's five-class estimator, with bounded window evidence and hysteresis. Track confirmation does not establish hostile intent. Details show separate identity/behavior percentages and reasons; see [drone behaviour](../drone_behavior/drone_behavior.md) for policy and limitations |
| Predictor | Constant-velocity extrapolation only |
| Metrics | Count error, position RMSE, ID swaps, friendly false alarms, scored against ground truth |

Catalog data: `catalog.js` is generated, do not edit it. After changing `seeder/catalog/*.json` run `python seeder/export_catalog.py`.

Panels: **Sensor feed** shows the latest records the sensors reported (only their native fields), **Sensor limits** lists every sensor's range window, field of view, pointing, rate and output, and the map draws each sensor's real coverage (wedges for forward-pointing sensors, rings for 360-degree ones). Raw observations are drawn as sensors report them: a ray for bearing-only, a ring for range-only, a point for radar.

Map: it fills its whole panel; the dashed square is the 1 km x 1 km area of operations, and you can pan and zoom past its edge.

### Coordinated movement

The patrol controller (`missions.js`) tracks observation opportunities on a 25 m grid. A cell is observed when its center falls inside an active drone-mounted sensor's range window and field of view at that sensor's sampling time. Weather-adjusted geometry applies; a successful detection is not required. Ground sensors contribute to tracking, but do not update patrol coverage history. Destinations stay at least 160 m from other drones and their goals. Patrols commit to useful legs for six seconds before replacing a covered destination, with reassessment at 1 Hz. This prevents sensor samples from continually reversing the flight direction.

Every mode maintains at least 100 m horizontal separation between friendly drones and aims for 160 m clearance. Motion uses five-second proximity predictions plus reservations for complete braking trajectories, with continuous separation checks over each 0.1 s step. Drones may cross the same location at different times. Speeds remain bounded by the scenario's per-drone speed and acceleration by 2 m/s²; slowing and hovering are allowed. Sensor yaw changes by at most 20°/s in every mode, holds steady while hovering on patrol, and interpolates across the angle boundary by the short arc. Patrol heading follows motion, while follow/search drones may yaw independently to aim sensors. Terrain avoidance and energy limits are not modeled.

Automatic following requires a confirmed track, sustained suspicion and an investigation request. The closest available drone whose sensors can identify at a safe standoff takes the assignment. It can approach using fresh COP observations before its own sensors acquire the object. Catalog identification range, current weather at both ends and a 40 m floor set standoff; smoothed track estimates and one-second anticipation guide movement. One second without fresh COP support starts a 10 s search near the last estimate, with a gradual sensor sweep. A slower drone may lose a faster target. Commands override automatic tasks; classification changes or unsuccessful search release the assignment. Tracker merges preserve single ownership. The controller's standalone compatibility mode still supports first-detector following when no investigation provider is supplied.

The **Drone missions** panel and **Mission destinations** map layer show each drone's mode and goal. Enable **Coverage age** to see red unvisited cells, cyan recent observations, and amber older observations on a 60 s scale. The **Protected areas / corridors** layer shows the configured behavior policy; the default protected radius is 150 m around C2. Mission state and coverage history follow the playback cursor, including when scrubbing backwards. Frames include additive `missions` and `coverage` fields; `missionConfig`, `behaviorConfig` and `investigations` describe the configuration and request/status records in simulation results and JSON exports. A coverage value of `-1` means unvisited; other values are the last observed simulation time in seconds, in rows from the southwest corner.

Run headless movement and integration checks from the repository root:

```
node ui/viewer/missions.test.js
```

Not implemented from the design: the measure-distance tool, true line-of-sight terrain occlusion, separate raw bearing rays for acoustic, topology comparison.
