# Automatic drone behaviour assessment

The Python reference is [patterns.py](patterns.py), with relative encounters in
[encounters.py](encounters.py). [AutomaticEstimator](../friend_foe/automatic.py)
feeds the team's two-axis classifier. The viewer ports both modules and compares
complete trajectories with the Python reference.

The five existing flags remain `friendly`, `peaceful`, `unknown`, `suspicious`
and `hostile`. Identity comes from verified roster sync or fresh matching trusted
beacons. Motion never establishes friendly identity.

## Inputs

Only estimated position/velocity, uncertainty, existence, observation freshness,
received trusted beacons and previously verified ally histories enter inference.
There is no protected zone, C2-distance rule, boundary crossing rule or privileged
scenario role. Absolute location cannot change an assessment. `for_area(c2)` is
retained as a compatibility constructor and ignores C2. Optional authorized transit
corridors remain a benign configuration input; none is configured by default.

At most two samples per second form a 20 s window. Observation gaps over 2 s and
association jumps reset history. Position sigma over 25 m or existence below 0.6
adds no behavioral evidence. A 1.5 s velocity filter reduces derivative noise.
Stale/predicted observations cannot accumulate evidence. Ally references must be
fresh, sufficiently observed and verified; input ordering cannot change them.

## Encounter evidence

Relative position and velocity predict closing rate, closest approach and time
to intercept. This is risk evidence, not proof of intent. Relative-state/time
prediction is also used in [NASA's detect-and-avoid work](https://software.nasa.gov/software/LAR-18464-1);
our pursuit rules and numerical thresholds are simulation assumptions and do not
implement or claim certification under that system.

| Observed evidence | Score before uncertainty weighting |
|---|---:|
| A sustained predicted intercept with a moving ally | +1.2, suspicion only |
| Repeated distinct intercept approaches | +2.1, suspicion only |
| Contact responds after at least two distinct ally course changes and follows its motion | +1.8 |
| Responsive pursuit plus sustained faster closure toward an intercept, or repeated intercepts | +3.8 |
| Consistent transit over 15–18 s, over 60 m progress and position/velocity agreement | ramps to −3.4 |
| Consistent orbit over 18 s, over 100 m travel and position/velocity agreement | −3.3 |
| Developing transit / similarity to a verified patrol | weak negative evidence only |
| Hover, erratic motion, silence or unfamiliar identity alone | no hostile evidence |

A single crossing cannot establish hostility. Close distance alone cannot either.
A contact must react **after** our ally's maneuvers; zero-lag parallel flight and
our investigator reacting to the contact do not establish responsive pursuit.
A continuous circle is one maneuver, not many decisions. Poor relative precision
or unresolved overlapping tracks cannot establish an intercept. Converging
traffic blocks a premature peaceful assessment. Independent risk overrides benign
motion; correlated cues use the strongest score, not a sum of duplicate cues.

The rolling window is one bounded evidence state. The hook sends its change after
forgetting, rather than adding the whole score each frame. Frame rate therefore
does not create confidence. Scores decay and history expires; a genuine breakoff
can return a contact to unknown or peaceful.
When a maneuver leaves the moving window, earlier encounter evidence decays with
the configured 20 s time constant instead of vanishing on the next sample.
Details explicitly mark this retained evidence and its age. Sustained safe
transit/orbit can replace it; an association reset discards it.

## Automatic decisions and GUI percentages

The viewer displays the actual identity score (`p_friendly`) and behavior risk
(`p_hostile`) beside every track, plus the selected flag's score when applicable.
Details show these percentages, peaceful evidence (`1 − p_hostile`), observation
quality, matched maneuvers, closure, response lag, reasons and the real thresholds.
These independent simulation scores are not a calibrated five-way probability
distribution and do not sum to 100%. Unknown has no invented probability.

Identity is primary: enter friendly at 90%, retain at 70%. Otherwise behavior
enters hostile at 90% (retain 70%) or peaceful at risk at most 10% (retain at most
30%, subject to `peaceful_min_updates`). Suspicion additionally needs low identity
(at most 30%, retain 40%) and risk at least 65% (retain 55%). Ambiguous history stays
unknown. The raw beacon-only estimator keeps its older silence rule solely for
baseline comparisons; the automatic pipeline requires behavioral risk.

Known friendly tracks coast after 1 s without an update. Their identity can fade
to unknown; missing beacons alone do not accuse them or dispatch an investigation.
Fresh matching beacons restore identity. Simulator dropout is not an inference
feature. Coasting describes tracking status separately from the assessment flag.

## Simulation and investigations

The busy preset contains physical simulator actors that follow or intercept
moving allies, alongside ordinary non-allied transit, orbit and hover. They react
to actually flown trajectories; flags never control their scripts. This changes
sensor observations, not estimator inputs or forced labels. The seeder source is
unchanged. Its scripted truth remains the baseline; use the viewer's recorded
truth for responsive actors, as for commanded friendly motion.

Suspicion must persist for 3 s before the closest suitable available drone is
assigned. Catalog/weather identification ranges, RF feasibility, one follower per
target, command priority, cooldown and search/release behavior remain in force.
An ally being approached is excluded from investigating that encounter; another
available drone observes it while the approached ally keeps its mission.
The fleet keeps its 100 m mutual separation, acceleration and sensor-turn limits.

Kinematically indistinguishable benign and hostile objects receive the same
assessment. Smooth flight cannot prove harmless intent; a contact without enough
observable interaction can remain unknown/peaceful despite a hostile scenario role.

## Validation

```sh
python3 -m pytest -q
node ui/viewer/test-behavior.js
node ui/viewer/test-assessments.js
node ui/viewer/test-traffic.js
node ui/viewer/test-investigations.js
node ui/viewer/missions.test.js
node ui/viewer/test-commands.js
node ui/viewer/test-messages.js
node ui/viewer/test-weather.js
node ui/viewer/test-clutter.js
node ui/viewer/test-jamming.js
node ui/viewer/test-bandwidth.js
```

The parity runner uses `python` on Windows and `python3` elsewhere; `PYTHON` can
specify an executable path. Tests cover pursuit, reverse causality, crossings,
parallel traffic, uncertain/stale references, identity priority, geography and
input-order independence, dropout/recovery, replay, frame-rate invariance and
motion limits. Tune on seeds 1–99; reserve 1000–1099 for final evaluation.
