# EDTH-repo

Distributed multi-sensor fusion into a single Common Operational Picture (COP) under electronic warfare (EW).

Combine partial, noisy observations from low-cost UAS and ground sensors, fused across distributed nodes with imperfect clocks, uncertain positions and lossy communication, into one picture that gives the **number of hostile targets** with a **stable identity, position and velocity** for each, and never flags friendlies as threats.

> Status: **planning phase.** Folder structure and documents are in place; nothing is implemented yet.

## Documents

| Document | Contents |
|----------|----------|
| [docs/concept.md](docs/concept.md) | Problem statement, scenario, success criteria, our approach, components, metrics |
| [docs/system-design.md](docs/system-design.md) | Architecture, module responsibilities, conventions (time, coordinates, uncertainty), message schemas, module design, repo layout, open decisions |
| [docs/team-plan.md](docs/team-plan.md) | Work split between 3 people, interfaces between them, per-phase tasks, working agreements |

## Repository layout

| Folder | Purpose |
|--------|---------|
| [docs/](docs/) | Concept and system design |
| [common/](common/) | Shared message schemas, time/frame helpers, bus interface |
| [scenarios/](scenarios/) | Scenario definitions |
| [seeder/](seeder/) | Generates realistic scenario components |
| [simulation/](simulation/) | 2D world, ground truth, network channel emulator |
| [sensors/](sensors/) | Camera, acoustic, RF, radar models incl. weather effects |
| [tracker/](tracker/) | Per-node local multi-target tracker |
| [friend_foe/](friend_foe/) | Friendly beacon matching and drone behaviour pattern |
| [fusion/](fusion/) | Cross-node track merge, global IDs, COP |
| [predictor/](predictor/) | Optional short-horizon prediction |
| [scoring/](scoring/) | Metrics harness |
| [ui/](ui/) | Operator view and simulation viewer |

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
| ⬜ | Define shared message schema (observation, track, uncertainty, timestamp, source ID) |
| ⬜ | Choose stack, simulation framework and message bus |
| ⬜ | Define scoring metrics and ground-truth format |
| ⬜ | Set up environment, tooling, CI |

### Phase 1 - Optimistic pipeline (clean data)

| Status | Task |
|--------|------|
| ⬜ | Seeder: friendlies, ground sensors, 2 hostiles, terrain |
| ⬜ | Simulation: 2D map, height/terrain display, scripted crossing |
| ⬜ | Network channel emulator (pass-through) |
| ⬜ | Sensor models: camera (bearing), acoustic, RF, radar (ideal) |
| ⬜ | Baseline tracker: KF + GNN association + track management |
| ⬜ | Friend/Foe: friendly ID/position beacon matching |
| ⬜ | Scoring harness implementing the metrics |

**Exit criteria:** correct hostile count, no ID swaps through the crossing, zero friendlies flagged, on clean data.

### Phase 2 - Distributed fusion and behaviour

| Status | Task |
|--------|------|
| ⬜ | Per-node local trackers sharing compact tracks |
| ⬜ | Track merge with covariance intersection |
| ⬜ | Drone Behaviour module: friendly pattern + hostile presumption |
| ⬜ | Weather effects in sensor models |

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
| ⬜ | Message-loss sweep (0 → high %) with degradation curves |

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
