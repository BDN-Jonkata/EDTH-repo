# EDTH-repo

Distributed multi-sensor fusion into a single Common Operational Picture (COP) under electronic warfare (EW).

Combine partial, noisy observations from low-cost UAS and ground sensors, fused across distributed nodes with imperfect clocks, uncertain positions and lossy communication, into one picture that gives the **number of hostile targets** with a **stable identity, position and velocity** for each, and never flags friendlies as threats.

> Status: **planning phase, first code in.** A first simulation viewer with a built-in mock simulation runs from [ui/viewer](ui/viewer/) (see [ui/ui.md](ui/ui.md)), and the seeder catalog exists in [seeder/](seeder/). Weather and sensor quality (`sensors/`), the friend/foe estimator with investigation trigger and drone-status mapping (`friend_foe/`) and the JSON codec (`common/codec.py`) exist and are tested; the mock simulation accepts drone commands. The real simulation, tracker and fusion are not implemented yet.

Run the tests (Python 3.11+): `python -m pip install pytest`, then `python -m pytest` from the repo root.

## Documents

| Document | Contents |
|----------|----------|
| [docs/concept.md](docs/concept.md) | Problem statement, scenario, success criteria, our approach, components, metrics |
| [docs/system-design.md](docs/system-design.md) | Architecture, module responsibilities, conventions (time, coordinates, uncertainty), message schemas, module design, repo layout, open decisions |
| [docs/seeder-config.md](docs/seeder-config.md) | Scenario config (one JSON + seed), degradation switches, presets, open questions for the mentor |
| [docs/data-formats.md](docs/data-formats.md) | The JSON the seeder produces (scenario, truth, catalog, saved runs) and how to read it; start here if you build another module |
| [docs/seeder-plan.md](docs/seeder-plan.md) | What is left on the seeder, in order, with the plan, test and risks of each task |
| [docs/team-plan.md](docs/team-plan.md) | Work split between 3 people, interfaces between them, per-phase tasks, working agreements |

## Repository layout

| Folder | Purpose |
|--------|---------|
| [docs/](docs/) | Concept and system design |
| [common/](common/) | Shared message schemas, time/frame helpers, bus interface |
| [scenarios/](scenarios/) | Scenario presets (configs) |
| [seeder/](seeder/) | Platform/sensor catalog (PostgreSQL) and the scenario generator |
| [simulation/](simulation/) | 2D world, ground truth, network channel emulator |
| [sensors/](sensors/) | Camera, acoustic, RF, radar models incl. weather effects |
| [tracker/](tracker/) | Multi-target tracker (a central baseline now; per-node trackers later) |
| [pipeline/](pipeline/) | The whole chain on one scenario: sensors, lossy network, tracker, friend/foe, scoring |
| [friend_foe/](friend_foe/) | Friendly beacon matching and drone behaviour pattern |
| [drone_behavior/](drone_behavior/drone_behavior.md) | Automatic observed-motion evidence, policy configuration and reference tests |
| [fusion/](fusion/) | Cross-node track merge, global IDs, COP |
| [predictor/](predictor/) | Optional short-horizon prediction |
| [scoring/](scoring/) | Metrics harness |
| [ui/](ui/) | Operator view and simulation viewer (first version in `ui/viewer`, run with `python serve.py` there) |

## Architecture in one paragraph

Modules in one codebase with a message bus between them. A seeder builds the scenario; the simulation moves everything on a 2D map with terrain/height and produces ground truth plus sensor observations, which pass through a network channel emulator (pass-through at first, lossy and drifting later). Each node runs a local tracker and friend/foe classification, and shares compact tracks with covariances. Any reachable node or C2 merges them into the COP using covariance intersection. An optional predictor helps hold identities through the crossing. A scoring harness compares everything with ground truth. See [system design](docs/system-design.md).

---

## Project plan

Phased, starting from the optimistic case. Status legend: ⬜ not started · 🟨 in progress · ✅ done.

### Phase 0 - Foundation

| Status | Task |
|--------|------|
| 🟨 | Folder structure and docs (concept, system design) |
| ⬜ | Decide fusion topology (hybrid proposed) and module boundaries |
| 🟨 | Define shared message schema (observation, track, uncertainty, timestamp, source ID): header, beacon, track, investigation and drone-command messages drafted in `docs/data-formats.md`; observation and final COP track not frozen |
| 🟨 | Choose stack, simulation framework and message bus: Python, JSON Lines and PostgreSQL chosen; bus and the real simulation framework still open (a JavaScript mock simulation runs in the viewer) |
| 🟨 | Define scoring metrics and ground-truth format: `truth.json` format, metrics and the scoring module defined and done |
| 🟨 | Set up environment, tooling, CI: Python environment, pytest and unittest suites, node tests, `.env` and PostgreSQL done; no CI and no formatter yet |

### Phase 1 - Optimistic pipeline (clean data)

| Status | Task |
|--------|------|
| 🟨 | Seeder: sensor and platform catalog, PostgreSQL storage, scenario generator (friendly patrols, ground sensors, hostile paths, planned close crossing, four presets, tuning and test seeds) done; also clutter objects (birds, vehicles), weather combinations, weather events and a seasonal sky, and jamming zones in the config; terrain, moving ground units and bandwidth limits are not in the generator |
| 🟨 | Simulation: the viewer runs a JavaScript mock simulation (2D map with terrain/height display, crossing, commanded drone motion, clutter objects, per-detection weather with a sky control, jamming zones); the real simulation module is not started |
| ✅ | Network channel (`common/channel.py`): loss (independent or bursty, per sender), delay and node clocks from the scenario's `degradations`; jamming zones, node dropout and topology not modelled in Python (the viewer's mock simulation has a channel with jamming zones) |
| ✅ | Sensor observation models (`sensors/observe.py`, `native.py`, `beacons.py`): range window, field of view, detection probability, signatures, weather per detection, native fields with honest noise; the viewer's mock simulation has its own JavaScript version |
| ✅ | Baseline tracker (`tracker/`): central Kalman tracker on native readings, gated association, radar or two-bearing start, support rules, friendly beacon tracks; tested. Weak spot: a hostile is tracked 57 % of the time, see [tracker.md](tracker/tracker.md) |
| ✅ | Friend/Foe estimator: beacon matching, delivery-rate-weighted silence, `peaceful` class and behaviour hook (`threat_llr`), tested on synthetic data and seeder scenarios through a test adapter (`friend_foe/`) |
| ✅ | Friend/foe estimator fed from the real tracker and delivered beacons (`pipeline/`); the test adapter remains for quick experiments |
| ✅ | Scoring of one run (`scoring/`): optimal matching to `truth.json`, count error, position/velocity/heading error, OSPA, ID swaps, friendly and clutter false alarms; tested |
| ✅ | Message-loss sweep for the whole pipeline (`python -m pipeline.sweep`, results in [tracker.md](tracker/tracker.md#results)) |
| ⬜ | Reader for the viewer's result JSON in `scoring/` |

**Exit criteria:** correct hostile count, no ID swaps through the crossing, zero friendlies flagged, on clean data.

### Phase 2 - Distributed fusion and behaviour

| Status | Task |
|--------|------|
| ⬜ | Per-node local trackers sharing compact tracks |
| ⬜ | Track merge with covariance intersection |
| ✅ | Drone Behaviour module (`drone_behavior/`, Emkata): automatic observed-motion evidence for the estimator's `threat_llr` hook, policy configuration, parity with the viewer's JavaScript. On the pipeline's tracks it calls some hostiles but **no clutter peaceful** (birds and vehicles stay suspicious), so it does not yet save the wasted dispatches: [pipeline.md](pipeline/pipeline.md) |
| ✅ | Weather model (`sensors/`): several anomalies at once, anomalies that start, end and cover a zone, seasonal sun for day and night, per-module quality and sensor hierarchy from the catalog's `weather_effects`, shared golden cases for the JS port; tested |
| ✅ | Weather applied to simulated observations: the Python observation models and the viewer's mock simulation both look up sensor quality per detection from the weather at the sensor and at the target (combinations, events and sky are accepted by the seeder and the viewer); standoff uses the catalog's `sim.ident_range_m` |
| ✅ | Suspicious class, investigation trigger and weather-based standoff per catalog module; reads drone acks through `DroneStatusMapper`; tested |
| ✅ | Trigger connected to the real tracker in Python: `python -m pipeline.sweep --investigate` sends a stand-in drone (`pipeline/fleet.py`, `dispatch.py`) at suspicious tracks and scores against the trajectories flown. Result: hostile tracked 2 to 4 points more at 0 and 50 % loss, but more false tracks and flagged friendlies, see [pipeline.md](pipeline/pipeline.md) |
| ✅ | Closest-drone investigation of suspicious tracks in the viewer's mock simulation (Emkata, `ui/viewer/investigations.js`): closest drone with a feasible sensor, standoff from `ident_range_m` and weather, commanded motion with ack and retry, release on a final class, cooldown |

### Phase 3 - Prediction

| Status | Task |
|--------|------|
| ⬜ | Predictor: short-horizon prediction (seconds to minutes) |
| ⬜ | Use prediction to hold identity through the close-range crossing |

### Phase 4 - Realism

| Status | Task |
|--------|------|
| 🟨 | Noise and bias on sensors: honest per-field noise, scaled by weather, is in the observation models; bias is not modelled |
| 🟨 | Clock drift and time-sync handling: node clocks (offset, drift) stamp beacons in `common/channel.py`; the tracker does no time-sync |
| 🟨 | Position uncertainty (GNSS-denied): pose error is added to beacons and the tracker takes node poses from them; no pose estimation |
| 🟨 | Missing data, delay, out-of-order messages: loss and delay are in the channel; the tracker uses readings at arrival time and does not handle out-of-order ones |
| ✅ | Message-loss sweep for the friend/foe estimator, with weather and clutter (`python -m friend_foe.sweep`, results in `friend_foe/friend_foe.md`) |
| ✅ | Message-loss sweep for the whole pipeline (`python -m pipeline.sweep`, see Phase 1) |

### Phase 5 - Evaluation and delivery

| Status | Task |
|--------|------|
| ⬜ | Run full scenario sweeps and collect metrics |
| ⬜ | Compare centralized / decentralized / hybrid if time allows |
| ⬜ | Operator view / COP visualisation |
| ⬜ | Demo, write-up, final presentation |

---

## Risks

| Risk | Mitigation |
|------|------------|
| Identity swaps at the crossing | Classical association baseline first; prediction as an add-on; test the crossing first |
| Central design breaks under link loss | Hybrid topology and channel emulator from Phase 1 |
| Friendlies flagged as hostile | Friendly beacon matching + behaviour pattern; friendly false alarms scored as their own metric |
| Scope too large | Optimistic case first; each phase has its own exit criteria |
| Integration overhead | Modules in one codebase; fix message schema early (Phase 0) |

## Team and ownership

Detailed split and per-phase tasks: [docs/team-plan.md](docs/team-plan.md).

| Person | Area | Name |
|--------|------|------|
| A | Platform and world: `common`, `scenarios`, `seeder`, `simulation` (incl. channel emulator), the viewer's mock simulation | Orlin |
| Drone behaviour | Drone selection and flight, the behaviour module that feeds `threat_llr` | Emkata |
| C | Sensing, classification, evaluation: `sensors`, `friend_foe`, `scoring`, `pipeline`, `ui` | Kristian |
| B | Tracking and fusion: `tracker`, `fusion`, `predictor` | **nobody: the team is three people.** The baseline tracker and the pipeline were built by C. Per-node trackers, fusion and the predictor are unowned |

## Decisions log

| Date | Decision |
|------|----------|
| 2026-10-16 | Start with the most optimistic case; add realism in later phases |
| 2026-10-16 | Initial layout: Seeder, Simulation, Drone Behaviour, Meteorologic, Estimator, Degradation/time-sync (later) |
| 2026-10-16 | Revised: classical tracker is the core and AI only does prediction; hybrid fusion proposed; channel emulator in the simulation from the start; modules in one codebase instead of separate microservices; weather folded into sensor models; friendlies identified by broadcast first and behaviour second; metrics defined up front |
| 2026-10-16 | Repo split into per-module folders; concept and system design moved to separate docs |
| 2026-10-16 | Work split into 3 roles (A platform/world, B tracking/fusion, C sensing/evaluation) with agreed interfaces in `common/` |
| 2026-10-17 | Seeder catalog: 5 real UAS models + 2 ground sensors with different sensor loadouts and per-weather effects; stored in PostgreSQL, simulations saved as plain JSONB; seeder in Python |
| 2026-10-17 | Adopted team notes: scenarios are one JSON config + seed with a separate ground-truth file and separate tuning/test seeds; per-degradation switches; presets; radar resolution cell; sensor set switchable per scenario; catalog numbers moved to the more conservative values |
| 2026-10-17 | Viewer runs the seed with a platform chosen per node from the catalog; weather now includes night; map fills its panel |
| 2026-10-17 | Sensor limits enforced (range window, field of view, pointing, falling detection probability, rate, latency); sensors report native data only (cameras bearing+elevation, no range) and the tracker consumes it with EKF updates |
| 2026-10-17 | Scenario generator in the seeder: one config + seed gives a scenario and a separate ground-truth file; four presets (easy, medium, hard, challenge); tuning and test seed sets; viewer runs generated scenarios through serve.py |
| 2026-10-17 | Tracks get a `suspicious` class. Suspicious tracks are investigated by sending the closest suitable drone. The drone-behaviour owner picks and flies the drone; the weather/estimator owner provides the trigger and the weather-based standoff distance (`required_standoff`). Messages `InvestigationRequest` and `InvestigationStatus` added to the draft schemas |
| 2026-10-17 | First standalone code: `sensors/weather.py` and `sensors/quality.py`, `friend_foe/estimator.py` and `friend_foe/investigation.py`, `common/codec.py` (`encode`/`decode` plus message size log). Placeholder numbers throughout, to be tuned |
| 2026-10-17 | Weather standoff now built on the seeder catalog (`sim.range_m`, `sim.min_range_m`, `weather_effects`) instead of a separate table; the request lists a standoff per catalog module (`standoff_by_module`) so the drone-behaviour side picks the modules of the drone it chooses. The one missing number, how much of a module's range is good enough to identify, is a placeholder (`IDENT_FRACTION`) until the catalog gets a field for it. Track and investigation message formats added to `docs/data-formats.md` |
| 2026-10-17 | Agreed with the seeder/simulation owner: standard header `msg_id`, `source_id`, `t_sent`, `seq`, `schema_version` plus a top-level `type`; `seq` starts at 1 and counts every message a node sends (`Sequencer`); optional float rounding at encode (`precision`) so message sizes are realistic; corruption is treated as loss by the channel emulator, no CRC; delivery time and destination live in an envelope around the bytes |
| 2026-10-17 | Drone commands go over the same lossy channel as everything else with ack and retry (every 1.5 s, at most 5 tries, assumed); `goto` and `hold` can set a heading or face a target so a forward camera points at the object; flight limits per UAS are in the catalog and marked assumed; `drone_state` doubles as `investigation_status` (mapping in `docs/data-formats.md`) |
| 2026-10-17 | Friend/foe estimator weighs silence by the measured beacon delivery rate, and decays per second instead of per update. A loss and weather sweep (`friend_foe/sweep.py`, `evaluate.py`) on seeder-generated scenarios with bursty loss, delay, clock offset and pose error showed it holds up to about 70 % beacon loss and degrades at 90 %, with a hostile never called friendly; a silent intruder is flagged later as loss rises (4 s at 0 %, about 10 s at 70 %). Tuned on the tuning seeds, reported on the test seeds |
| 2026-10-18 | Combined meteorological anomalies: weather can be several anomalies at once (`fog+wind`), each with a strength (`rain:0.6`), and anomalies can start, end and cover a zone (`weather_events`); effects multiply, a worst-case assumption. The catalog check only tests single weathers; in combination platforms lose every working detection module (fog+wind leaves `mini4pro` and `gs_eo_acoustic` with none, fog+rain+wind at night leaves 4 of 7 platforms), see `python -m sensors.report`. The scenario format is a proposal; the seeder and viewer accept one weather only until the seeder owner agrees a plan |
| 2026-10-18 | Day and night follow the season: darkness comes from the sun's height above the horizon, computed from `environment.sky` = date, clock time, latitude and longitude (`sensors/daylight.py`), not from fixed hours, because the length of the day depends on the season and the latitude. The night effect gets a strength from 0 to 1 through twilight. The viewer shows night only as one of five exclusive weather buttons and the seeder's `time_of_day` is not read by it; a day/night switch or hour slider in the viewer would need the date and place too (proposed to the seeder owner) |
| 2026-10-18 | Estimator gets the `peaceful` class and a second evidence axis. Beacon evidence (friendly or not) and behaviour evidence (hostile-like or peaceful-like, `threat_llr` hook for the drone-behaviour module) are kept apart; hostile and peaceful both need positive behaviour evidence, silence alone only gives suspicious; a beacon match stays friendly whatever the behaviour looks like. The hook changed from `behaviour_llr` (beacon scale) to `threat_llr` (own scale, positive = hostile-like). Measured on clutter: with no behaviour module, 54 % of investigation requests go to birds and vehicles with 2+2 clutter objects and 74 % with 5+5, so the behaviour module is what saves the drones (`friend_foe/friend_foe.md`) |
| 2026-10-18 | The team is three people (Orlin: platform and world; Emkata: drone behaviour; Kristian: sensing, classification, evaluation), so role B had no owner. Built the missing chain in Python without waiting: a shared channel with loss, delay and clocks (`common/channel.py`), sensor observation models and a beacon source (`sensors/`), a central baseline tracker (`tracker/`), the pipeline that connects them to the estimator and to scoring (`pipeline/`), and a scoring module (`scoring/`). First end-to-end numbers on the test seeds: a hostile is tracked 57 % of the time at 0 % message loss and 23 % at 90 %, no friendly is flagged up to 50 % loss (`tracker/tracker.md`) |
| 2026-10-18 | Closed the investigation loop in the Python pipeline with a stand-in fleet and dispatcher (`pipeline/fleet.py`, `dispatch.py`). Scoring now takes friendly trajectories recorded during the run (`scoring.truth.with_recorded_samples`), because `truth.json` holds only the scripted patrol. A reviewed finding on the behaviour module's evaluation: pre-registering friendly ids as verified made friendlies look confirmed at t = 0 because the test adapter names tracks with the true ids; with a real tracker it has no effect, and beacons-only results are the honest ones |
| 2026-10-17 | JSON (JSON Lines) for messages while building the pipeline. `encode`/`decode` pair at the channel boundary so a compact binary format (Protobuf/CBOR) can replace it later without touching modules |
| 2026-10-17 | Shared message header on the mock's messages (`observation`, `friendly_beacon`, drone commands and states), one `messages.js`, matching `common/codec.py`; the mock tracker still reads an internal record that is not part of the format |
| 2026-10-17 | Clutter objects (birds, vehicles): real objects the sensors see that are not threats, generated from their own random stream so hostile paths do not move; a hostile track on one counts as a clutter false alarm (`cfa`) in the mock. Signatures are assumptions |
| 2026-10-17 | Track class `peaceful` added: not identified, probably not an enemy, the mirror of `suspicious`. Needs positive behaviour evidence, never silence alone; the estimator has to produce it (not built yet) |
| 2026-10-17 | Weather combinations, events and sky supported by the seeder validator and the viewer: JS port (`ui/viewer/weather.js`) checked against the shared cases generated from the Python reference (relative tolerance 1e-9); sensor quality is looked up per detection from the weather at the sensor and at the target; the combined-weather table is information only in the catalog check; `sim.ident_range_m` added to the catalog (assumed) |
| 2026-10-17 | Jamming zones (`degradations.network.jamming_zones`): messages sent by or to a node inside an active zone use the higher loss, RF receivers there get more noise; the sender's true position and the true time decide; Realistic mode only. Beacons are lost too, which friend/foe must survive |
