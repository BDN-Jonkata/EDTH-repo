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
| [tracker/](tracker/) | Per-node local multi-target tracker |
| [friend_foe/](friend_foe/) | Friendly beacon matching and drone behaviour pattern |
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
| 🟨 | Define scoring metrics and ground-truth format: `truth.json` format and metrics defined; scoring module not started |
| 🟨 | Set up environment, tooling, CI: Python environment, pytest and unittest suites, node tests, `.env` and PostgreSQL done; no CI and no formatter yet |

### Phase 1 - Optimistic pipeline (clean data)

| Status | Task |
|--------|------|
| 🟨 | Seeder: sensor and platform catalog, PostgreSQL storage, scenario generator (friendly patrols, ground sensors, hostile paths, planned close crossing, four presets, tuning and test seeds) done; terrain is not in the generator |
| 🟨 | Simulation: the viewer runs a JavaScript mock simulation (2D map with terrain/height display, crossing, commanded drone motion); the real simulation module is not started |
| 🟨 | Network channel emulator: the mock simulation has a lossy channel; the real emulator is not started |
| 🟨 | Sensor models: the mock simulation enforces sensor limits and native outputs from the catalog; the `sensors/` observation models are not started (weather and quality are done) |
| 🟨 | Baseline tracker: only a mock tracker in the viewer simulation (an example of the shape, not a reference tracker); the real tracker is not started |
| 🟨 | Friend/Foe: friendly ID/position beacon matching (estimator done and tested on synthetic data and on seeder-generated scenarios through a test adapter; not yet fed by the real tracker) |
| 🟨 | Scoring harness implementing the metrics: the viewer shows metrics; the scoring module is not started |

**Exit criteria:** correct hostile count, no ID swaps through the crossing, zero friendlies flagged, on clean data.

### Phase 2 - Distributed fusion and behaviour

| Status | Task |
|--------|------|
| ⬜ | Per-node local trackers sharing compact tracks |
| ⬜ | Track merge with covariance intersection |
| ⬜ | Drone Behaviour module: friendly pattern + hostile presumption |
| 🟨 | Weather effects in sensor models (conditions from `scenario.json`, per-module quality and sensor hierarchy built on the catalog's `weather_effects`, done and tested; not yet applied to simulated observations) |
| 🟨 | Suspicious class and trigger; weather-based standoff distance per catalog module (done and tested; the trigger also reads drone acks through `DroneStatusMapper`; not yet connected to the real tracker) |
| 🟨 | Closest-drone investigation of suspicious tracks: commanded drone motion with ack and retry exists in the mock simulation (`goto`, `hold`, `return_to_patrol`, flight limits); the drone-behaviour module that picks the drone is not started |

### Phase 3 - Prediction

| Status | Task |
|--------|------|
| ⬜ | Predictor: short-horizon prediction (seconds to minutes) |
| ⬜ | Use prediction to hold identity through the close-range crossing |

### Phase 4 - Realism

| Status | Task |
|--------|------|
| ⬜ | Noise and bias on sensors |
| ⬜ | Clock drift and time-sync handling |
| ⬜ | Position uncertainty (GNSS-denied) |
| ⬜ | Missing data, delay, out-of-order messages |
| 🟨 | Message-loss sweep (0 → high %) with degradation curves: done for the friend/foe estimator (`python -m friend_foe.sweep`, results in `friend_foe/friend_foe.md`); not for the whole pipeline |

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
| A | Platform and world: `common`, `scenarios`, `seeder`, `simulation` (incl. channel emulator) | TBD |
| B | Tracking and fusion: `tracker`, `fusion`, `predictor` | TBD |
| C | Sensing, classification, evaluation: `sensors`, `friend_foe`, `scoring`, `ui` | TBD |

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
| 2026-10-17 | JSON (JSON Lines) for messages while building the pipeline. `encode`/`decode` pair at the channel boundary so a compact binary format (Protobuf/CBOR) can replace it later without touching modules |
