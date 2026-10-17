# Compact coverage and cooperative review

Implemented in the JavaScript viewer on 2026-10-18. The Python pipeline's separate flight/dispatch implementation is unchanged. This extends the viewer's existing behavior estimator; its Python/JavaScript pursuit-policy parity remains separately tested.

## Patrol behavior

`ui/viewer/coverage.js` scores sensor footprints, rather than flying to the oldest grid cell itself. Patrol positions stay at least 120 m from the map edge. Sensors can watch outward from an interior position; yaw remains bounded at 20°/s and the existing acceleration, stopping-path and 100 m separation checks remain active.

Coverage includes live ground sensors, field of view, minimum range, weather and a conservative 85% of modeled range. RF is useful for emitter corroboration but does not certify area coverage of silent objects. The planner rewards unseen/stale cells strongly and reserves overlap, rather than stretching independent sensors to their maximum reach. It replans every three seconds instead of reversing on each sensor update.

The active watch area starts from available sensor capacity. After deployment it contracts to a contiguous area whose cells have been observed recently; expansion requires already-fresh surrounding cells. The full 1 km² map is retained. The GUI reports the active area in km², cells without an observation opportunity in the last ten seconds, and lifetime coverage of the full map separately. Gray cells outside the active watch area are **not** claimed covered. This is a patrol service area, not a hostility/protection zone.

Coverage means a modeled observation opportunity, not a guaranteed detection. Startup transit, weather, failures, sensor dead zones and lost communication can leave gaps. They remain visible in the counter and heatmap. Reducing the serviced area does not satisfy the challenge's full-village requirement by itself.

## Extra observers without abandoning the watch

`investigations.js` can request observations of an unidentified contact before it becomes suspicious. C2-bound tracks get priority after two seconds; ordinary unresolved contacts are reviewed after five seconds with the existing short dispatch delay. Fast ground cues get up to 1.5 seconds to contribute before a drone is requested. Ground pointing is simulated with the same 20°/s slew limit; physical steerability is an assumption for this simulated controller.

When one node is insufficient, the current observer keeps its patrol and another suitable drone is selected. Existing encounter-reference allies are still excluded. RF-only aircraft need observed emitter evidence. A second sensor can corroborate kinematics at its conservative detection range; it does not have to approach to the much shorter identity-inspection range. A drone already in range can turn its sensor from its current station if coverage permits. Identification/observation geometry retains the 40 m minimum standoff; corroboration does not assert visual identity.

The departure check compares the candidate's conservative footprint throughout its planned route and yaw slew against the current watch. Local weather is evaluated at each affected cell. The route cannot leave sole-covered cells behind or send the aircraft beyond the compact operating area. Stationary backup observers supporting the departure are reserved; their patrol positions/ground pointing are held for that task. A moving or offline aircraft is not treated as a stationary backup. The checks are repeated as the estimate changes. If no suitable observer can leave, the current watch is retained and the track detail states the reason. These sampled predictions do not constitute a formal continuous-coverage guarantee under arbitrary future motion/failures.

## Evidence and the 5–10 second review

`assessment.js` receives only delivered native observations, track estimates/covariance and the public C2 location. It never reads target roles or future paths. It distinguishes sensor corroboration from friendly identity and hostile intent:

- Reports must be fresh (two seconds); replayed/coasting states cannot accumulate observation history. History is sampled at 0.5 seconds over six seconds.
- Multiple modules on the same node count as one observer. Independent viewing geometry requires distinct nodes, at least 40 m baseline and at least 15° bearing intersection. Merged radar returns do not count as independent resolved evidence.
- Position uncertainty must be at most 25 m. Corroboration requires usable history of at least 2.5 seconds and an evidence-quality score of at least 65%. Scores are simulation heuristics, not calibrated probabilities.
- A sustained approach to C2 uses observed closure and predicted course/closest approach, not membership of a geographic zone. When independent observations corroborate it, the contact can become **suspicious** within the review window. Heading toward C2 alone never produces a hostile label; hostile still needs the existing responsive-pursuit/intercept evidence. Verified fleet identity remains primary.
- Recent corroborated suspicion decays rather than vanishing on a single missing source or direction update. It is not strengthened by prediction alone.
- The five-second review point and ten-second deadline are shown with contributing nodes, confidence, ground cues and any coverage restriction. Insufficient evidence at the deadline produces an explicit overdue alert; it does not create artificial confidence or silently mark an object hostile.

A contact already well localized by two sensors may still have unknown allegiance. Additional views improve kinematic evidence; they cannot establish intent from indistinguishable benign motion. The deadline runs from observed/reviewable contact, not an unseen truth entry. Total link loss or an unreachable target cannot guarantee an assessment within ten seconds.

## Verification

Run from the repository root:

```sh
node ui/viewer/test-cooperative.js
node ui/viewer/missions.test.js
node ui/viewer/test-assessments.js
node ui/viewer/test-behavior.js
python3 -m pytest -q
```

New regression cases cover independent versus repeated/collinear observations, stale and merged returns, friendly identity, a native noisy inbound case with 20% message loss/200 ms delay, ground-first review, coverage-safe departures, border goals, RF coverage and adaptive range contraction. Movement tests retain separation, acceleration, sensor-yaw and repeatability checks. The assessment suite uses a separate positive observed-pursuit fixture: compact patrols need not generate the repeated maneuvers that the old busy demo happened to expose.

In the noisy inbound fixture, first observation is at 0.6 s and corroborated suspicion at 4.4 s: **3.8 s after first observation**, with both ground nodes and two drones contributing. This is a reproducible fixture result, not a guarantee at every loss/weather level. Thirteen new cooperative regressions and the existing Python suite (448 tests plus four subtests) pass.

Clear-weather default-seed comparison against `cc4e224`, scoring the same conservative non-RF footprints on the final active disk in both versions, sampled every 0.5 s over 60–120 s:

| Preset | Compared area | Before: cells fresh within 10 s | After | Before: border destinations | After |
|---|---:|---:|---:|---:|---:|
| challenge | 0.125 km² | 58.0% | 100.0% | 70.1% | 0% |
| busy | 0.100 km² | 53.5% | 98.4% | 91.2% | 0% |

These are small diagnostic runs, not full-village coverage certification. Some transient gaps remain in busy traffic; the controller reports them. The movement sweep across 15 seed/weather combinations retained at least 154.69 m separation, 20°/s maximum yaw and 2 m/s² maximum acceleration. All 19 JavaScript suites completed successfully after updating their motion-dependent observation fixtures. Browser checks passed for challenge, busy, jammed and outage, including the coverage/review controls and mobile overflow. No seeder source or production scenario was changed.
