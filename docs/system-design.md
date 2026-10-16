# System design

Back to [README](../README.md) · Previous: [Concept](concept.md)

> Status: **proposed**. Stack, simulation framework and wire format are not chosen yet (Phase 0). Everything below is language-neutral and should be confirmed or changed in Phase 0.

## 1. Overview

Modules in one codebase with clear interfaces and a message bus between them. They can be split into separate processes later if needed.

```
                 scenarios/
                     │
                     ▼
               ┌──────────┐
               │  seeder  │  creates nodes, hostiles, terrain
               └────┬─────┘
                    ▼
┌───────────────────────────────────────────────────────┐
│ simulation                                            │
│  world (2D map + height/terrain, object motion)       │
│  ground truth ─────────────────────────────┐          │
│  sensors (camera / acoustic / RF / radar)  │          │
│        │ Observation                       │          │
│        ▼                                   │          │
│  channel emulator (delay, loss, drift)     │          │
└────────┬───────────────────────────────────┼──────────┘
         │ messages per node                 │
         ▼                                   │
┌─────────────────────────────┐              │
│ NODE (one per drone/sensor) │              │
│  clock + own pose estimate  │              │
│  tracker (local tracks)     │              │
│  friend_foe (beacons +      │              │
│     behaviour)              │              │
└────────┬────────────────────┘              │
         │ LocalTrack, FriendlyBeacon        │
         ▼  (over channel emulator)          │
┌─────────────────────┐                      │
│ fusion (any         │                      │
│ reachable node / C2)│                      │
│  merge + global IDs │                      │
└────────┬────────────┘                      │
         ▼                                   ▼
   COP (Track list) ──▶ predictor ──▶ scoring ◀── ground truth
         │
         ▼
        ui
```

## 2. Module responsibilities

| Module | Inputs | Outputs | Notes |
|--------|--------|---------|-------|
| `scenarios` | n/a | scenario files | Node layout, hostile paths, weather, loss rate, seed |
| `seeder` | scenario | node specs, hostile specs, terrain | Components behave as real feeds would |
| `simulation` | node/hostile specs | ground truth, raw sensor physics, channel | Owns true time; steps the world |
| `sensors` | ground truth, weather | `Observation` | Noise, detection probability, range limits, weather effects, honest covariance |
| `tracker` | `Observation`, own-pose, `FriendlyBeacon` | `LocalTrack` | Runs on each node. KF + gated association + track management |
| `friend_foe` | beacons, track kinematics | per-track class + presumption | Beacon match first, behaviour pattern second |
| `investigation` | suspicious `Track`s, weather state, drone states | `InvestigationRequest`, drone tasking | Split in two: the estimator side raises requests and computes the required standoff from weather; the drone-behaviour side picks the drone and flies it (see 5.8) |
| `fusion` | `LocalTrack` from reachable nodes | `Track` (COP) | Covariance intersection, global ID assignment |
| `predictor` | `Track` history | predicted state + uncertainty | Optional; system works without it |
| `scoring` | `Track`, ground truth | metrics | Same metrics every phase |
| `ui` | COP, ground truth | operator view | Also usable as simulation viewer |
| `common` | n/a | schemas, time and frame helpers, bus interface | Single source of truth for messages |

## 3. Key conventions

### 3.1 Time

- Simulation owns **true time**. Each node has a **local clock** with offset and drift relative to true time (zero in the optimistic case).
- Every message carries `t_sent` (sender local clock) and `source_id`. The channel emulator adds the delivery time.
- Observations carry `t_obs` (local clock at measurement). Trackers must tolerate out-of-order and late messages (state buffer / retrodiction) in the realism phase. Optimistic phase: in-order, zero delay.
- Time-sync estimation (offset/drift between nodes) is a tracker-side function added in Phase 4, behind the same interface.

### 3.2 Coordinates

- GNSS is assumed jammed, so positions are in a **local metric frame (ENU)** shared by convention, with origin at a scenario reference point.
- Each node holds a **pose estimate with covariance** instead of ground-truth position. Optimistic phase: covariance is tiny and pose is exact.
- Height comes from terrain + object altitude; the 2D map shows it by shading/contours and labels.

### 3.3 Uncertainty

- Every measured or estimated quantity is a **mean + covariance**. Sensors must report honest covariances; this is how weather and sensor quality influence fusion.
- Tracks expose a covariance and a confidence score.

## 4. Message schemas (draft)

Field names are provisional; the final contract lives in `common/`.

```
Header        { msg_id, source_id, t_sent, seq }

Observation   { header, sensor_type, sensor_id, t_obs,
                kind: bearing | range_bearing | position | detection,
                value, covariance, detection_prob_hint?,
                weather_state? }

FriendlyBeacon{ header, friend_id, position, covariance, velocity? }

LocalTrack    { header, local_track_id, t_state,
                state: [x, y, z, vx, vy, vz], covariance,
                existence_prob, class: friendly|hostile|suspicious|unknown,
                class_prob, sources: [sensor_type...] }

Track (COP)   { global_id, t_state, state, covariance,
                existence_prob, class, class_prob,
                contributing_nodes, age, status: tentative|confirmed|coasting|deleted }

InvestigationRequest { header, track_id, position, covariance, class_prob,
                       priority, t_requested,
                       standoff_m,                    # recommended distance of the best module
                       standoff_by_module: { <catalog module id>: {max_range_m, recommended_m,
                                              confidence, feasible} },
                       weather_confidence,            # 0..1, how much the weather leaves of the best module
                       feasible }                     # false = no module can identify it right now

InvestigationStatus  { header, track_id, drone_id,
                       state: assigned | en_route | on_station | done | aborted }

GroundTruth   { t, objects: [{id, kind: friendly|hostile, state}] }   # simulation + scoring only
```

Sharing rule: nodes send **LocalTrack and FriendlyBeacon**, not raw observations, to save bandwidth over lossy links. Raw observations stay local.

## 5. Module design

### 5.1 Channel emulator (in `simulation`)

- Per-link parameters: loss probability, delay (fixed + jitter), bandwidth cap, up/down schedule (to model intermittent links and C2 outage).
- Applies clock offset/drift when stamping messages.
- Pass-through (loss 0, delay 0) in Phase 1. All later realism is configuration, not new interfaces.
- Seeded RNG so every run is reproducible.

### 5.2 Sensors

| Sensor | Gives | Limits |
|--------|-------|--------|
| Camera | Bearing (angle), class cues | No range; degraded by fog/low light; line of sight |
| Acoustic | Rough bearing/position | Imprecise; wind and noise dependent |
| RF | Emitter bearing/presence | Only sees emitters; friendlies also emit |
| Radar (low cost) | Range + bearing | Short range, coarse resolution |

Weather modifies each sensor's noise covariance and detection probability. Terrain/height blocks line of sight (simulation computes visibility).

### 5.3 Tracker (per node)

- State: position + velocity (constant-velocity model to start; turn model if needed). EKF/UKF to handle bearing-only measurements.
- Association: gating, then GNN (assignment); upgrade to JPDA if crossing performance needs it.
- Track management: tentative → confirmed → coasting → deleted, using existence probability.
- Bearing-only observations from several nodes are triangulated at the fusion level and/or via multi-sensor updates; range-giving sensors initialise tracks faster.
- Friendly beacon matches are used to **exclude** detections from hostile tracks.

### 5.4 Friend/Foe

1. **Beacon match (primary):** a track whose position is consistent (within gate) with a received `FriendlyBeacon` is labelled friendly.
2. **Behaviour pattern (secondary):** learn the pattern friendlies follow from beacon history. When an unknown track enters range, raise an alarm and output a presumption (friendly / hostile / suspicious / unknown) with probability, by comparing its motion to the pattern.
3. Output is a class + probability on each track, never a hard delete, so mistakes stay recoverable.

### 5.5 Fusion (hybrid)

- Any reachable node or C2 can act as a merger. It receives `LocalTrack`s from reachable nodes.
- **Track-to-track association** between nodes (gated on state + covariance), then **covariance intersection** to merge, because shared history between nodes is unknown.
- **Global ID management:** a global ID persists across merges; it is mapped to the set of contributing local track IDs. Rules for split/merge at the crossing must keep IDs stable (see 5.7).
- When no merger is reachable, each node's local tracks still stand alone; the COP is stitched together when links return.

### 5.6 Predictor (optional)

- Input: recent `Track` history. Output: predicted state + uncertainty for the next seconds to minutes.
- Baseline: kinematic extrapolation. Upgrade: learned model once a baseline and metrics exist.
- Used by the tracker/fusion as an additional hint during close-range crossing; never required for correctness.

### 5.7 Identity through the crossing

The hardest case. Plan:

1. Motion continuity (velocity and heading) in the filter is the main signal.
2. Hold tracks through ambiguous associations (coast) instead of forcing a hard assignment; use JPDA if GNN swaps.
3. Use class/sensor cues (e.g. RF signature, size) as extra association features if available.
4. Predictor hints as a tie-breaker.
5. Scoring counts ID swaps explicitly; the crossing scenario is run first and often.

### 5.8 Investigation of suspicious tracks

A track classed `suspicious` is checked by sending a drone close enough to identify it. The work is split between two owners with one contract (`InvestigationRequest` / `InvestigationStatus`, section 4).

**Estimator / weather side (provides the trigger and the standoff):**

- Raise an `InvestigationRequest` when a track has stayed `suspicious` for a set time. Apply a cooldown and allow one drone per track, to avoid oscillation.
- Compute how close a drone must get to identify the object, using the weather:

```
required_standoff(module, target_position, t, weather) -> {
    max_range_m,      # farthest distance at which this module can still identify the object
    recommended_m,    # distance to aim for: about 70% of max, never inside the module's minimum range
    confidence,       # 0..1, share of clear-weather capability that the weather leaves
    feasible          # false if the module cannot identify the object right now
}
```

- `module` is a sensor module from the seeder catalog. The request lists the result for every detection module a drone may carry (`standoff_by_module`), so the drone-behaviour side looks up the modules of the drone it considers (`scenario.json` `friendlies[].sensors`).
- All numbers come from the catalog: the module's `sim.range_m` and `sim.min_range_m`, scaled by its `weather_effects` for the active conditions (`environment.weather` and `time_of_day`; effects multiply, for example fog at night). The one number the catalog lacks is how much of the detection range is good enough to *identify* (a camera sees class cues, a microphone only hears presence). A placeholder fraction per module kind (`IDENT_FRACTION` in `sensors/quality.py`) fills in until the catalog gets a field for it.
- Re-evaluate on request, because weather changes during the flight.
- After arrival, new observations from the drone feed the estimator, which upgrades or downgrades the suspicion.

**Drone-behaviour side (owns the movement):**

- Choose which drone goes. Start with the closest; later weigh distance, whether its sensors suit the weather (from the standoff values), and the need to keep coverage of the village.
- Fly to `standoff_m`, hold, report `InvestigationStatus`, then return to patrol.
- Own the minimum safe distance. The estimator reports what is physically needed to identify; the behaviour side may enforce a larger floor for objects that could be hostile.
- If `feasible` is false, do not dispatch, or pick a drone with a suitable sensor.

**Notes:**

- Phase 1: log requests only, nothing moves. Close the loop once simulation and drone behaviour exist.
- A close drone also gives a range measurement, which helps separate the two hostiles at the crossing.
- The simulation must accept commanded drone motion instead of only scripted paths.

### 5.9 Scoring

Inputs are the COP and ground truth. Matching of estimated tracks to true objects uses optimal assignment per timestep (OSPA-style). ID swaps are detected by changes in the assignment between consecutive timesteps. Output is a metrics table per run plus sweeps over message loss. Metric definitions are in [concept.md](concept.md#4-metrics).

## 6. Run modes

| Mode | Purpose |
|------|---------|
| Single run | One scenario, one seed; viewer + metrics |
| Sweep | Same scenario across loss rates / seeds; produces degradation curves |
| Headless | CI and batch evaluation without UI |

## 7. Repository layout

```
.
├── README.md            overview, plan, links
├── docs/                concept.md, system-design.md
├── common/              schemas, time/frame helpers, bus interface
├── scenarios/           scenario definitions
├── seeder/
├── simulation/          world, ground truth, channel emulator
├── sensors/
├── tracker/
├── friend_foe/
├── fusion/
├── predictor/
├── scoring/
└── ui/
```

## 8. Phase mapping

| Phase | Design elements activated |
|-------|---------------------------|
| 0 | Confirm topology, schemas, stack, metrics |
| 1 | seeder, simulation, ideal sensors, pass-through channel, single baseline tracker, beacon matching, scoring |
| 2 | per-node trackers, fusion with covariance intersection, behaviour module, weather, investigation of suspicious tracks (standoff from weather, closest-drone tasking) |
| 3 | predictor |
| 4 | channel loss/delay/drift, pose uncertainty, time-sync, late/out-of-order handling |
| 5 | sweeps, topology comparison, UI polish, demo |

## 9. Decisions to make in Phase 0

- Language/stack and simulation framework.
- Message bus and wire format (in-process queue vs. network transport; JSON vs. binary).
- Tracker filter details (EKF vs UKF, motion model) and association (GNN vs JPDA).
- Whether the final COP is merged on a single designated node or on any reachable node.
- UI technology.
- Who owns the minimum safe approach distance (proposed: drone-behaviour owner).
- Drone selection rule beyond "closest" (distance + sensor suitability under the weather).
