# 03-Rai challenge audit

Audit date: 2026-10-17. Baseline: `7947bca631b8b18867575df4969050cb6f406de2` on `emkata`; measurements below distinguish that baseline from this working tree's fixes. Scope: repository documentation, Python sensing/channel/tracker/fusion/classification/scoring, JavaScript simulation and browser, and reproducible challenge runs. The supplied challenge and [concept](concept.md) take priority over project component ticks.

**Verdict: the app has working foundations, but does not yet meet the operational challenge.** Correct hostile count fails even in the clean official crossing. Crossing identity is not robust across seeds/loss; friendly exclusion fails in the backend's presumed-threat count under heavy loss. Imperfect sensor clocks and GNSS-denied navigation are not realistically exercised. Unit tests demonstrate component correctness, not operational acceptance.

## Requirements versus evidence

| Actual challenge requirement | Finding | Status |
|---|---|---|
| Five defensive drones, two ground sensors, about 1 km², two hostile paths crossing closely | `challenge` has the required inventory and area. Seed 4127's sampled closest approach is 15.88 m at 50.8 s. The village is a fictional visual backdrop; houses do not supply physical occlusion | Implemented scenario |
| Combine native partial/noisy cheap-sensor observations | Cameras report direction without range; acoustics/RF/radar have native fields, limited coverage, uncertainty, emission/detection constraints and resolution. Catalog/weather/noise parameters remain assumptions, not calibrated hardware evidence | Implemented simulation; validation partial |
| Reliable COP with correct hostile count over time | Viewer assesses neither crossing target hostile. Python's default classifier never produces hostile labels without behavior; its historical counter instead counts unknown/suspicious/unclassified tracks. That counter produces 3–4 near the official crossing although truth is 2 | **Fails** |
| Stable identity through the close crossing | Official clean seed happens to preserve IDs, but small loss/seed samples show swaps. Fusion previously collapsed close opposing tracks and conflicting verified identities; regression fixtures now prevent those cases. A general crossing-association solution is still open | **Not demonstrated** |
| Accurate position and velocity/headings | Both engines estimate kinematics; errors and coverage are measured below. Matched-track RMSE omits misses, so it cannot establish full-picture accuracy by itself. Challenge gives no numeric error tolerances | Partial; acceptance threshold open |
| No friendlies counted as threats | Clean samples pass. At 90% loss, baseline central count includes 3.67/5 friendlies on average; optional distributed mode includes 4.33/5. These are presumed-threat count alarms, not actual hostile labels. Viewer hostile false alarms stay zero in this crossing case while it also detects zero hostile labels | **Fails backend count policy under EW** |
| Distributed sensing with intermittent communication | Central fusion is allowed by team freedom. Python optionally runs per-node trackers and a CI merger; channel supports independent/bursty loss, delays, jamming loss, caps and faults. One merger, no peer topology/failover. Viewer has separate store-and-forward; Python does not | Partial; central choice itself is permitted |
| Imperfect clocks | Python offset/drift changes beacons, not native sensor observations. JS can drift packet timestamps but its internal observation time remains ideal. Neither estimates synchronization. A 5 s offset/10000 ppm Python clock change leaves observation packets identical | **Major modeling/handling gap** |
| Uncertain sensor positions under GNSS jamming | Python propagates beacon position uncertainty into measurements, but lacks a GNSS-denied navigation estimator. Heading error is unused; stale-pose fallback follows the scripted patrol even if a drone was commanded elsewhere. JS sensing uses true sensor coordinates; configured pose error is a no-op | Partial Python; missing JS realism |
| Degradation as message loss increases | Both engines can sweep loss; useful coverage degradation is visible. Lower count error/swaps at high loss can result from lost ghost tracks or unobserved targets. No combined EW acceptance gate passes | Measurement implemented; success unmet |

## Fresh measurements

These are **diagnostic tuning/default-seed measurements**, not a final held-out evaluation. No test seeds were used to tune fixes. Scores use simulation truth only on the evaluation side; roles and paths were not fed into inference.

### Official preset, Python central pipeline

Reproduce from the repository root:

```sh
python3 -m scoring.challenge --official --losses 0,0.5,0.9 --json out/challenge-official.json
```

Seed 4127, clear, 10 s warmup, 0.1 s sampling, 50 m association gate, **zero continuity discount**. The default Python baseline has no behavior hook. “Presumed count” below retains its historical policy: every class except friendly/peaceful counts. “Strict hostile” means only the actual hostile label. The command reports both.

| Message loss | Geometric target coverage, whole run | Presumed-count MAE | Position RMSE | Velocity RMSE | Heading RMSE | ID swaps | Friendlies in presumed count |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0% | 63.75% | 0.875 | 14.29 m | 1.99 m/s | 7.97° | 0 | 0/5 |
| 50% | 63.27% | 0.597 | 11.06 m | 2.03 m/s | 8.92° | 0 | 0/5 |
| 90% | 27.55% | 0.478 | 13.55 m | 5.58 m/s | 28.11° | 1 | 5/5 |

The hostile count at integer times 45–56 s is **3 → 4 → 3 versus true 2** at zero loss. Two ghosts cause excess count. Over the ±3 s window around closest approach (47.8–53.8 s):

| Loss | Target coverage | Position RMSE | ID swaps | Exact presumed count | Exact strict hostile count | Friendlies in presumed count |
|---|---:|---:|---:|---:|---:|---:|
| 0% | 100% | 4.23 m | 0 | 0% of steps | 0% | 0 |
| 50% | 100% | 5.48 m | 0 | 100% | 0% | 0 |
| 90% | 50% | 12.20 m | 0 | 59.0% | 0% | 2 |

At 90% loss, one hostile is missed while friendly tracks sometimes make the total look correct. Zero crossing swaps with 50% coverage is not identity success. Strict hostile count is zero throughout this crossing at every tested loss.

### Three tuning seeds, Python central

```sh
python3 -m scoring.challenge --set tuning --seeds 3 --losses 0,0.5,0.9 --json out/challenge-tuning.json
```

Same scorer, no behavior/trust/OOSM options, independent loss. Means across three runs:

| Loss | Target coverage | Presumed-count MAE | Exact presumed count | Position RMSE | Velocity RMSE | ID swaps/run | Friendlies in presumed count |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0% | 63.02% | 0.717 | 44.5% | 10.34 m | 2.94 m/s | 1.33 | 0/5 |
| 50% | 59.74% | 0.676 | 49.0% | 11.96 m | 2.28 m/s | 1.67 | 0/5 |
| 90% | 15.98% | 1.131 | 25.6% | 15.61 m | 5.04 m/s | 1.00 | 3.67/5 |

Kinematic averages omit runs without relevant matched samples; coverage does not. Strict hostile detection is 0% here because the baseline does not call anything hostile. This is not comparable to papers reporting verified-hostile detection.

### Optional Python distributed fusion, after scoped fixes

```sh
python3 -m pipeline.sweep --preset challenge --set tuning --seeds 3 --losses 0,0.5,0.9 --distributed --csv out/challenge-distributed.csv
```

This existing sweep uses the **legacy 10 m scoring continuity discount**, unlike the challenge diagnostic. Do not compare swap totals as though the scorers were identical.

| Loss | Presumed-threat target coverage | Presumed-count MAE | Position RMSE | ID swaps/run | Friendlies in presumed count |
|---|---:|---:|---:|---:|---:|
| 0% | 58.19% | 0.656 | 12.39 m | 1.67 | 0/5 |
| 50% | 52.54% | 0.669 | 10.15 m | 2.00 | 0/5 |
| 90% | 28.20% | 0.882 | 12.15 m | 10.67 | 4.33/5 |

Before the fusion fixes, clean swap mean was 2.67; after, 1.67 on these three seeds. This small sample does not establish a general improvement or challenge acceptance.

### JavaScript viewer, after metric/sensor fixes

`Sim.run({scenario:SCENARIOS.challenge,seed:4127,mode:'realistic',weather:'clear',loss,delayMs:200,driftMs:200})`, loss 0/50/90. Scored over its existing 45–90 s evaluation interval, 60 m geometric gate; swaps/false alarms cover the whole run. This differs from the Python experiment's timing, sensors and control logic.

| Loss | Actual hostile-count MAE | Exact hostile count | Target coverage | Position RMSE | Velocity RMSE | Heading RMSE | ID swaps | Hostile-label friendly alarms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0% | 2 | 0% | 66.63% | 6.95 m | 1.71 m/s | 7.47° | 0 | 0 |
| 50% | 2 | 0% | 55.43% | 12.25 m | 2.18 m/s | 8.77° | 1 | 0 |
| 90% | 2 | 0% | 28.16% | 8.95 m | 4.66 m/s | 25.38° | 1 | 0 |

Before the scoring fix, all three runs reported null position error and zero swaps because only hostile-labelled tracks were evaluated. The updated metrics expose tracking quality while preserving the real classification failure. Better matched RMSE at 90% than 50% is survivor bias, not better total performance.

## Bugs fixed during this audit

- **Complete burst loss did not lose packets.** `Loss(1, burst=True)` previously delivered all 100 probe packets; it now drops every packet, with boundary regressions.
- **Delayed fusion overwrote newer states.** Per-local-track state-time/sequence watermarks reject stale and replayed reports, including after expiry. This assumes a stable sender epoch; reboot/clock-reset protocol remains unspecified.
- **Close fusion collapsed different targets.** Verified-identity conflicts and uncertainty-aware velocity compatibility now prevent merging opposing targets or F1/F2, including through an intermediate report. No claim is made for indistinguishable motion at high uncertainty.
- **Radar resolution broke across ±π.** Viewer azimuth comparisons and merged bearing centroids now wrap correctly; the regression covers a genuinely unresolved pair on opposite sides of the angle seam.
- **Scores hid unclassified targets and crossing swaps.** Tracking is evaluated independently of labels, using all confirmed/coasting contacts and all active truth kinds. Viewer matching uses optimal one-to-one distance assignment without the old strong continuity preference. Rolling errors weight matched samples correctly; velocity, heading and coverage are exposed.
- **Count semantics were inconsistent and implicit.** Python now exposes strict-hostile count/recall alongside legacy presumed-count metrics; neither overwrites the other. `scoring.challenge` requires a complete cadence of observations on both sides of the crossing before reporting identity success. It separately checks that every real target is labelled hostile, so hostile ghost tracks cannot conceal unknown real targets through count cancellation.
- **Retrospective playback looked live.** The UI labels later-arrival position corrections explicitly; metrics remain live. It also identifies the JavaScript simulation engine.

## Project ticks versus requirements

The README, project summary, tracker and sensors docs now distinguish implemented components from operational success, remove stale “not implemented” claims, and retain historical measurements with qualifiers.

| Project tick/claim | Audit interpretation |
|---|---|
| Seeder, native sensors, channel, tracker, estimator, scoring ✅ | Implemented and tested; success criteria remain unmet. Default `challenge` has no EW/pose/clock degradation enabled |
| Per-node tracking/CI merger ✅ | Implemented optional Python mode, not an any-node/failover COP |
| Automatic five-class behavior ✅ | Pattern logic and viewer traffic demonstration exist. Ordinary crossing hostile paths need not pursue allies, so pursuit detection cannot validate hostile count in this challenge. Python safe/raw behavior modes also differ from the viewer |
| Health/trust ✅ | Implemented options; Python trust is central-only and off by default. JS health/trust port is not the live viewer's assessment engine |
| Predictor ✅ | Implemented optional keepers; documented experiments do not demonstrate reliable crossing improvement |
| Crossing identity “not planned” ⬜ | Corrected to **required/open**, since the challenge explicitly demands it |
| Clock/pose realism 🟨 | Correctly incomplete; ideal sensor timestamps/poses still mask major requirements |
| Operator COP visualization ⬜ | Corrected to partial: JS viewer and Python exported-run reader exist; live Python COP integration remains open |
| Centralized/distributed comparison ⬜ | Small comparisons exist; broad, consistent challenge validation remains open |
| Final sweeps/demo/report ⬜/🟨 | Still open; these small diagnostics are not final results |

## Priority work to reach acceptance

1. **Define observable hostile evidence for this scenario.** A straight flight or close crossing does not establish hostile intent. Provide modeled RF/visual identity evidence or an explicit, testable mission classification rule; verify it automatically without accessing truth. Keep cooperative identity, unidentified contacts and hostile count distinct. Do not fix recall by promoting every unknown or by changing hostile truth paths to suit a pursuit detector.
2. **Make one COP the integrated product.** Connect the operator viewer to Python tracker/fusion outputs, or explicitly choose the JS engine as the submission and implement its missing realism. Shared seeds/catalogs do not make two engines equivalent.
3. **Fix coverage and crossing association/count together.** Measure viewpoint observability, missed-target intervals, ghosts and identity switches around the crossing. Improve sensor placement/cueing and association while respecting unresolved sensor cells; preserve verified-friendly continuity through link loss without assuming silence proves hostility.
4. **Exercise the actual impairment requirements.** Apply per-node clocks to sensor timestamps, estimate time offset/drift with uncertainty, and propagate node position/heading uncertainty from GNSS-denied navigation. Evaluate delayed and out-of-order updates causally; keep retrospective playback separate.
5. **Freeze an acceptance protocol, then evaluate held-out seeds.** Agree error tolerances, acquisition warmup, crossing interval, and EW/loss conditions. Require exact hostile count, zero friendly threat flags and fully observed stable crossing identities together. Report position/velocity/heading errors beside coverage, misses and ghosts. Retain unknown/insufficient-data results where observability is absent; complete communication blackout cannot guarantee new detections.

## Verification

Baseline Python tests: **415 passed**. After scoped fixes and scoring regressions: **435 passed, 4 subtests passed** (`python3 -m pytest -q`). Regression coverage includes stale/replayed fusion, conflicting identities and opposite-motion crossing, lossy boundaries, missing-target/ghost cancellation, strict versus presumed counts, incomplete crossing histories/truth and close swaps without continuity discounts.

All **168 JavaScript checks across 18 suites passed**, including the new metric and radar seam regressions. Browser verification passed for all eight presets (`easy`, `medium`, `hard`, `challenge`, `busy`, `dusk`, `jammed`, `outage`), metric rendering, the loss chart's coverage values, retrospective-mode labelling and a 390 px mobile viewport. No browser runtime errors or horizontal mobile page overflow were observed. These are software checks, not a claim that all presets satisfy the challenge.

No seeder source, scenario fleet or ground-truth roles were changed. Historical result tables were preserved. Publishing these fixes does not establish challenge acceptance; the operational gaps above remain open.
