# Concept

Back to [README](../README.md) · Next: [System design](system-design.md)

## 1. Problem

Combine partial, noisy observations from several low-cost, low-SWaP UAS and ground sensors into one reliable Common Operational Picture (COP), fused across distributed nodes with imperfect clocks, uncertain positions and lossy communication. The picture must give the **number of hostile targets** and keep a **stable identity, position and velocity** for each.

### Context

- No single node sees enough: cameras give direction but no range, acoustics are imprecise, RF only catches emitters, low-cost radar has limited range and resolution.
- GNSS is jammed, clocks drift, messages are delayed or lost.
- Friendly drones also appear in sensor data and must **not** be counted as threats.
- We decide what to share, where to fuse and how to express uncertainty.

### Scenario

- 5 defensive drones + 2 ground sensors covering a village of about 1 km².
- Under EW, links to C2 and between nodes are intermittent.
- 2 hostile drones enter and cross paths at close range.
- Through the crossing the operator keeps an accurate hostile count, positions and headings, with **no identity swaps** and **no friendlies flagged as threats**.

### Team freedom

Sensor types, network and fusion architecture (centralized / decentralized / hybrid), simulation framework.

### Success criteria

| # | Criterion |
|---|-----------|
| 1 | Correct target count over time |
| 2 | Position error |
| 3 | Identity consistency through the crossing |
| 4 | Graceful degradation as message loss increases |

---

## 2. Our approach

Start with the **most optimistic case** (clean data, no drift, no loss) to get an end-to-end pipeline working, then progressively add realism (missing data, clock drift, position uncertainty, message loss).

Guiding ideas:

1. **The tracker is the core.** Identity through the crossing is a data-association problem. We build a classical multi-target tracker first (Kalman-type filter, gated association, track management). AI is only an optional prediction layer on top.
2. **Hybrid fusion.** Each node tracks locally and shares compact tracks with covariances. Whichever node is reachable (or C2) merges them. This keeps working when links drop.
3. **Realism is designed in, switched on later.** A network channel emulator sits in the simulation from day one (pass-through at first). Every message carries timestamp, source ID and uncertainty from day one.
4. **Friendlies are identified cooperatively first.** Friendly beacons (ID + position) are the primary signal; behaviour-pattern matching is the secondary signal for unknown drones.
5. **Weather is part of the sensor model.** It changes noise and detection probability, and sensors report honest covariances, so no hand-made trust hierarchy is needed.
6. **Everything is scored against ground truth** with the same metrics in every phase.

## 3. Components (summary)

Details and interfaces are in [system-design.md](system-design.md).

| Component | Idea |
|-----------|------|
| Seeder | Generates realistic scenario components. Each returns data as it would in practice. |
| Simulation | 2D map with height/terrain shown in some way. Source of observations and ground truth. Includes the network channel emulator. |
| Sensors | Camera (bearing only), acoustic, RF (emitters only), radar (limited range/resolution), with weather effects. |
| Tracker | Per-node local multi-target tracking: count, ID, position, velocity, uncertainty. |
| Friend/Foe | Beacon matching plus Drone Behaviour module: learns the friendly pattern, alarms when an unknown drone enters range and outputs a friendly/hostile presumption. |
| Fusion | Merges tracks from nodes (covariance intersection), keeps global IDs, builds the COP. |
| Predictor | Optional short-horizon prediction (seconds to minutes) to help hold identity through the crossing. |
| Degradation / time-sync | Later phase: clock drift, delay, out-of-order and missing data, handled at the channel-to-tracker interface. |
| Scoring | Metrics against ground truth, headline result is metrics vs message loss. |

## 4. Metrics

Defined up front so every phase is scored the same way. Headline result: **metrics vs. message-loss rate**.

| Metric | Definition |
|--------|-----------|
| Count error | Estimated vs. true hostile count over time |
| Position error | RMSE of track position vs. ground truth (OSPA as combined metric) |
| Velocity/heading error | RMSE of velocity and heading |
| ID swaps | Number of identity swaps through the crossing |
| Friendly false alarms | Friendlies flagged as threats |
| Degradation curve | All of the above vs. message loss (0 → high %) |

## 5. Open questions

- Confirm fusion topology (hybrid proposed).
- Simulation framework and language/stack.
- Which AI approach for the predictor.
- How uncertainty is expressed in the COP (covariances, per-track confidence).
