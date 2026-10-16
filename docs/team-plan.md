# Team plan (3 people)

Back to [README](../README.md) · See also [Concept](concept.md), [System design](system-design.md)

Roles are named **A / B / C**. Put real names in the table below once decided.

| Person | Role | Name |
|--------|------|------|
| A | Platform and world | TBD |
| B | Tracking and fusion | TBD |
| C | Sensing, classification and evaluation | TBD |

## 1. Split of ownership

| Person | Owns (folders) | Delivers |
|--------|----------------|----------|
| **A** | `common`, `scenarios`, `seeder`, `simulation` | Message schemas and bus, scenario files, seeded components, 2D world with terrain/height, ground truth, network channel emulator |
| **B** | `tracker`, `fusion`, `predictor` | Per-node tracker (KF + association + track management), cross-node merge with covariance intersection, global IDs, short-horizon predictor |
| **C** | `sensors`, `friend_foe`, `scoring`, `ui` | Sensor models incl. weather, beacon matching and drone behaviour module, metrics harness and sweeps, operator view |

Why this split: each person has one clear input and one clear output, so work can run in parallel against agreed interfaces.

```
 A: world + schemas ──Observation/GroundTruth──▶ C: sensors ──Observation──▶ B: tracker ──LocalTrack──▶ B: fusion ──Track──▶ C: scoring / ui
                                                  C: friend_foe ◀── beacons ── A
```

## 2. Interfaces between people (the contracts)

These must be agreed first because they are what lets all three work at once.

| Contract | Producer → Consumer | Defined in |
|----------|--------------------|-----------|
| `GroundTruth` | A → C (scoring, sensors) | `common/` |
| `Observation` | C (sensors) → B (tracker) | `common/` |
| `FriendlyBeacon` | A (simulation) → B, C | `common/` |
| `LocalTrack` | B (tracker) → B (fusion), C (friend_foe) | `common/` |
| `Track` (COP) | B (fusion) → C (scoring, ui) | `common/` |
| Channel API (send/receive with link params) | A → everyone | `simulation/` |

A owns `common/`, but **schema changes need a quick OK from B and C**.

## 3. Phase-by-phase plan

### Phase 0 - Foundation (all three, first)

| Who | Task |
|-----|------|
| All | Decide stack, simulation framework, message bus; confirm hybrid topology |
| All | Review and freeze first version of the schemas (target: end of Phase 0) |
| A | Repo tooling: environment setup, formatter/linter, CI skeleton, run entry points |
| B | Pick filter and association approach (EKF/UKF, GNN) and write the short note in system-design |
| C | Define metrics precisely and the ground-truth matching rule |

**Done when:** schemas frozen in `common/`, everyone can run an empty pipeline end to end.

### Phase 1 - Optimistic pipeline

| Who | Task | Needs from others |
|-----|------|-------------------|
| A | Seeder + scenario file for 5 drones, 2 ground sensors, 2 hostiles, terrain | none |
| A | Simulation: world step, scripted crossing, ground truth output, pass-through channel | none |
| A | Emit `FriendlyBeacon`s from friendly drones | schemas |
| C | Ideal sensor models (camera bearing, acoustic, RF, radar) producing `Observation` | `GroundTruth` from A (use a hand-made stub until ready) |
| C | Beacon matching in `friend_foe` | `FriendlyBeacon`, `LocalTrack` |
| C | Scoring harness: count, position/velocity error, ID swaps, friendly false alarms | `GroundTruth`, `Track` (stub tracks until B is ready) |
| B | Baseline tracker: KF + GNN + track management, single-node first | `Observation` (use recorded or synthetic file until C is ready) |
| B | Single merged COP output as `Track` | `LocalTrack` |

**Exit criteria (all):** correct hostile count, no ID swaps through the crossing, zero friendlies flagged, on clean data.

**Integration point 1:** end of Phase 1. A, B and C plug their modules together and run the crossing scenario through scoring.

### Phase 2 - Distributed fusion and behaviour

| Who | Task |
|-----|------|
| A | Multiple nodes in the simulation, per-node clocks and poses (still ideal), channel API supports per-link config |
| B | Per-node trackers sharing compact tracks; merge with covariance intersection; global ID management |
| C | Drone Behaviour module (friendly pattern, alarm, presumption); weather effects in sensor models; basic COP view in `ui` |

### Phase 3 - Prediction

| Who | Task |
|-----|------|
| B | Predictor (kinematic baseline, then learned) and use as a tie-breaker in association |
| C | Score predictor impact on ID swaps at the crossing |
| A | Harder crossing variants (closer, different speeds, occlusion by terrain) |

### Phase 4 - Realism

| Who | Task |
|-----|------|
| A | Channel emulator: loss, delay/jitter, intermittent links, clock offset/drift, node pose uncertainty (GNSS-denied) |
| B | Time-sync handling, late/out-of-order messages, tracker robustness to missing data |
| C | Sensor noise and bias, message-loss sweep runner, degradation curves |

### Phase 5 - Evaluation and delivery

| Who | Task |
|-----|------|
| A | Scenario sweeps, reproducibility (seeds), performance |
| B | Topology comparison (centralized / decentralized / hybrid) if time allows |
| C | Final metrics, operator view polish, plots for the presentation |
| All | Demo script, write-up, final presentation |

## 4. Working agreements

- **Branches:** one branch per task, merge to `main` through a pull request; the other two review anything touching `common/`.
- **Stubs first:** if your input is not ready, use a small recorded or hand-made file in the agreed format. Nobody waits on anybody.
- **Seeded runs only:** every run takes a seed so results can be reproduced.
- **Sync:** short daily check (what is done, what is blocked, what changes in `common/`); integration points are Phase 1 end and each phase end after that.
- **Status:** update the phase tables in the [README](../README.md) when a task changes state.

## 5. Risks to this split

| Risk | Mitigation |
|------|------------|
| B is blocked waiting for sensors and simulation | Synthetic observation file in the agreed format from day one |
| A has the heaviest early load (schemas, simulation, channel) | C helps with schemas in Phase 0; channel emulator is pass-through until Phase 4 |
| Schema changes break others | Changes in `common/` need B and C approval; keep a changelog line in the PR |
| C's workload peaks late (sweeps, plots) | Scoring harness is built in Phase 1 so late work is only configuration and plotting |
