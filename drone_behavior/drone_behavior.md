# Automatic drone behaviour assessment

The Python reference is [patterns.py](patterns.py), connected to the team's
two-axis estimator through [AutomaticEstimator](../friend_foe/automatic.py).
The viewer uses [behavior.js](../ui/viewer/behavior.js) and
[friend-foe.js](../ui/viewer/friend-foe.js); parity tests compare complete input
sequences with the Python reference. No server call is needed per simulation frame.

The team's five labels remain authoritative: `friendly`, `peaceful`, `unknown`,
`suspicious`, and `hostile`.
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
Association jumps also start a new history. A 1.5 s velocity filter suppresses
tracker derivative noise; heading, turn coherence and integrated displacement
must describe a consistent observed path.

## Evidence rules

| Observed pattern | Evidence before quality weighting |
|---|---:|
| Sustained approach predicted to enter a protected area | +1.2, insufficient by itself for a hostile flag |
| Clearly observed outside-to-inside entry, then at least 2 s confidently inside | +1.5, supports suspicion rather than hostility |
| At least 8 s loitering/hovering, mostly inside | +1.8, supports suspicion |
| At least 18 s persistent loiter, at least 85% of history inside and currently deep inside | +3.4 |
| Two observed outside-to-inside intrusions at least 4 s apart within the history | +3.4 |
| At least 10 s within an authorized corridor, consistent direction/speed, progress at least 40 m, clear of protected areas and not converging | −3.2 |
| At least 15–18 s consistent transit, position/velocity agreement, over 60 m progress, protected-area clearance and a non-converging course | ramps to −3.4; no corridor required |
| At least 18 s coherent off-site orbit, over 100 m travel, consistent speed/turn and protected-area clearance | −3.3 |
| Developing transit with less supporting evidence | −0.7, insufficient by itself for a peaceful flag |
| Similar speed/turn pattern to a beacon-verified patrol | −0.5, insufficient by itself for a peaceful flag |
| Erratic motion, missing identity, or ambiguous geometry | No directional motion evidence |

Protected-area tests include a two-sigma margin. Peaceful assessments additionally
require a 40 m clearance margin throughout the history. A straight course is
projected up to 60 s ahead; a mature coherent orbit uses its estimated circle so
the tangent does not make its assessment flicker each revolution. Positive risk
overrides peaceful evidence. Correlated approach/entry cues
use the strongest score rather than summing. A rolling window represents one
bounded evidence state: the hook supplies the change after the estimator's decay,
not the same window's full score every frame. Scores therefore cannot grow toward
certainty merely because rendering or tracker updates are frequent. Missing
observations let evidence decay; TTL expiration clears both estimator and feature
memory. The team's hysteresis selects flags without human approval.

In the automatic pipeline, missing identity alone leaves a contact `unknown`.
Suspicion additionally requires behavior score at least 0.65 (exit 0.55) and low
identity confidence. Peaceful needs score at most 0.1 (exit 0.3); hostile needs at
least 0.9 (exit 0.7). The raw beacon-only estimator retains its older silence rule
for baseline comparisons. Neither smooth flight nor a peaceful assessment can
establish `friendly` identity.

`p_friendly` and `p_hostile` are **independent simulation scores**, not a five-way
distribution and not calibrated probabilities of real intent. A benign aircraft,
bird or vehicle entering the protected area can trigger a threat assessment.
Kinematically indistinguishable objects receive the same result. Clutter showing
protected-area intrusion or loiter can still consume investigations; this baseline does not
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
node ui/viewer/test-assessments.js
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
cover all five simultaneous labels in mixed sensor traffic, benign false flags,
truth-role independence, history warmup, noisy transit/orbits, single versus repeated
intrusions, noisy boundaries, erratic non-threat motion, rate dependence,
coasting, replay, identity priority, one-to-one matching, behavior changes, TTL,
weather feasibility, dispatch/release/cooldown, and motion limits. Existing seeder
seed separation remains unchanged: tune on 1–99; reserve 1000–1099 for final tests.

The evaluation CLI prints both beacon-only and automatic metrics, including
friendly/benign false flags, benign peaceful time, hostile-as-peaceful errors,
detection delay and clutter/benign investigations. It uses the existing clean-track adapter, so its results are a
logic check, not real-tracker accuracy or calibration evidence.
