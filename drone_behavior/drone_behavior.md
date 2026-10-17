# Automatic drone behaviour assessment

The Python reference is [patterns.py](patterns.py), connected to the team's
two-axis estimator through [AutomaticEstimator](../friend_foe/automatic.py).
The viewer uses [behavior.js](../ui/viewer/behavior.js) and
[friend-foe.js](../ui/viewer/friend-foe.js); parity tests compare complete input
sequences with the Python reference. No server call is needed per simulation frame.

The existing five labels and `EstimatorConfig` thresholds remain authoritative.
The module supplies positive hostile-like or negative peaceful-like evidence to
`threat_llr`. Identity is separate: only verified roster sync or matching friendly
beacons can establish an ally. Similar motion cannot verify identity. One identity
can match one track per update, and reusing a packet cannot accumulate confidence.

## Inputs and policy

Runtime inputs are observed position, velocity, position uncertainty, existence
probability, state/observation times, received beacons, and our known protected
areas and authorized corridors. IDs are opaque keys. Target/clutter roles, future
waypoints, signatures, truth matches and scoring results are excluded.

Default simulation policy protects a **150 m radius around the known C2**. This is
an explicit scenario assumption, not a learned real-world safety boundary. Override
it using `BehaviorConfig` in Python or `Sim.run({behavior: ...})` in JavaScript.
`scenario.config.drone_behavior`, when supplied by the caller, also supplies policy.
No corridor is authorized by default. Example policy:

```json
{
  "protected_zones": [{"x": 500, "y": 500, "radius_m": 150}],
  "corridors": [{"start": [0, 100], "end": [1000, 100], "half_width_m": 30, "max_speed_mps": 20}]
}
```

The module samples at most twice per second, retains a 20 s history, requires
4 s of usable history, and resets that history after a gap over 2 s. States with
position sigma over 25 m or existence below 0.6 add no motion evidence. Lower
uncertainty increases the weight of accepted evidence. The viewer passes the last
associated measurement time as internal `observed_t`; coasting, replay and late
packets do not count as new observations. A real tracker must provide equivalent
freshness metadata. This optional field is internal, not a shared message change.

## Evidence rules

| Observed pattern | Evidence before quality weighting |
|---|---:|
| Sustained approach predicted to enter a protected area | +1.2, insufficient by itself for a hostile flag |
| Clearly observed outside-to-inside entry, then at least 2 s confidently inside | +3.2 |
| At least 12 s loitering/hovering mostly inside, still confidently inside | +3.0 |
| At least 10 s within an authorized corridor, consistent direction and speed, progress at least 40 m, outside all protected areas | −3.2 |
| Smooth transit outside protected areas | −0.7, insufficient by itself for a peaceful flag |
| Similar speed/turn pattern to a beacon-verified patrol | −0.5, insufficient by itself for a peaceful flag |
| Erratic motion, missing identity, or ambiguous geometry | No directional motion evidence |

Protected-area tests include a two-sigma margin. Correlated approach/entry cues
use the strongest score rather than summing. A rolling window represents one
bounded evidence state: the hook supplies the change after the estimator's decay,
not the same window's full score every frame. Scores therefore cannot grow toward
certainty merely because rendering or tracker updates are frequent. Missing
observations let evidence decay; TTL expiration clears both estimator and feature
memory. The team's hysteresis selects flags without human approval.

`p_friendly` and `p_hostile` are **independent simulation scores**, not a five-way
distribution and not calibrated probabilities of real intent. A benign aircraft,
bird or vehicle entering the protected area can trigger a threat assessment.
Kinematically indistinguishable objects receive the same result. Unknown clutter
can remain suspicious and still consume investigations; this baseline does not
claim reliable bird/vehicle recognition. Calibration needs representative benign
non-allied drone and clutter measurements, beyond scripted clean adapter tracks.

## Automatic investigations

The viewer's [investigations.js](../ui/viewer/investigations.js) implements the
existing request/status contract in process. A confirmed track must remain
suspicious for 3 s. The closest available drone with a feasible sensor is selected,
one per target. Catalog `ident_range_m` and weather at both ends determine its
standoff goal, with a 40 m floor; an RF-only drone needs recent observed emitter
evidence. The goal is not a guaranteed distance from an uncontrolled moving object.
The fleet's 100 m mutual separation,
braking reservations, acceleration and sensor-yaw limits remain in force.

Commands override automatic assignments. Loss of contact searches for 10 s, then
returns to patrol. Friendly, peaceful or hostile assessments end identification
and release the drone; these tracks continue to be tracked. Assignment, en-route,
on-station, done and aborted states are recorded. Requests have a 30 s cooldown.
This mock's investigation contract events are local; observation/beacon/command
radio loss still uses the channel. Separate distributed delivery of investigation
requests/statuses remains part of the future real modules.

## Validation

From the repository root:

```sh
python3 -m pytest -q
node ui/viewer/test-behavior.js
node ui/viewer/test-investigations.js
node ui/viewer/missions.test.js
node ui/viewer/test-commands.js
node ui/viewer/test-messages.js
node ui/viewer/test-weather.js
node ui/viewer/test-clutter.js
node ui/viewer/test-jamming.js
python3 -m drone_behavior.evaluate --preset medium --seeds 1 7 83 --birds 2 --vehicles 2
```

The behavior parity test launches Python to produce reference sequences. Tests
cover history warmup, noisy boundaries, erratic non-threat motion, rate dependence,
coasting, replay, identity priority, one-to-one matching, behavior changes, TTL,
weather feasibility, dispatch/release/cooldown, and motion limits. Existing seeder
seed separation remains unchanged: tune on 1–99; reserve 1000–1099 for final tests.

The evaluation CLI prints both beacon-only and automatic metrics, including
friendly false flags, hostile-as-peaceful errors, detection delay and clutter
investigations. It uses the existing clean-track adapter, so its results are a
logic check, not real-tracker accuracy or calibration evidence.
