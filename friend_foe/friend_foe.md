# friend_foe module

Friend/foe classification: friendly beacon matching plus the Drone Behaviour pattern module.

Status: estimator, investigation trigger, drone-status mapping and an automatic observed-motion baseline are implemented. The behavior baseline supplies the existing hook and is connected to the viewer. See [drone behaviour](../drone_behavior/drone_behavior.md) for policy assumptions, validation and limits, and [system design](../docs/system-design.md) for the broader architecture.

## What exists

| File | Contents |
|------|----------|
| [estimator.py](estimator.py) | `FriendFoeEstimator`: per-track evidence, beacon matching, class friendly / hostile / suspicious / peaceful / unknown with probability and hysteresis; two evidence axes (beacon, behaviour); weighs silence by the measured beacon delivery rate |
| [automatic.py](automatic.py) | `AutomaticEstimator`: observed-motion history/evidence through `threat_llr`, verified roster initialization and automatic flag selection; Python reference for the viewer |
| [investigation.py](investigation.py) | `InvestigationTrigger`: raises `investigation_request` for tracks that stay suspicious, with the weather-based standoff per catalog module, cooldown and status feedback |
| [drone_status.py](drone_status.py) | `DroneStatusMapper`: turns the mock simulation's `drone_state` messages (and commands reported lost) into `investigation_status`, using the mapping in [data-formats.md](../docs/data-formats.md); feed the result to `InvestigationTrigger.on_status` |
| [scenario_adapter.py](scenario_adapter.py) | Turns a `scenario.json` into estimator input frames: **test stand-in** for the tracker and beacon source (see below) |
| [evaluate.py](evaluate.py) | `evaluate(scenario, threat_llr=None, automatic=False)`: friendly false alarms, hostiles called friendly or peaceful, clutter flagged, time to confirm and to flag, requests on friendlies and on clutter, standoff; opt into the automatic behavior baseline |
| [sweep.py](sweep.py) | `python -m friend_foe.sweep`: the estimator over beacon loss (plain and bursty) and weather, optional `--birds` and `--vehicles`, tuning or test seeds, optional CSV |
| [jsonl_io.py](jsonl_io.py) | Reads JSON Lines files of `local_track` and `friendly_beacon` messages into frames |
| [make_synthetic.py](make_synthetic.py) | Generates [data/local_tracks.jsonl](data/local_tracks.jsonl) |
| [demo.py](demo.py) | `python -m friend_foe.demo [file.jsonl or scenario.json] [weather]` |
| `test_*.py` | Tests |

Message formats are in [data-formats.md](../docs/data-formats.md).

## Rules

- A fresh beacon consistent with a track pushes it toward friendly. Each beacon matches only its nearest track.
- Silence lowers identity confidence slowly, per second, to a floor. In `AutomaticEstimator` silence alone leaves a contact **unknown**. Suspicion also needs observed behavior risk (`p_hostile` at least 0.65, exit 0.55). The raw `FriendFoeEstimator` keeps the older silence-to-suspicious rule for beacon-only baseline comparisons (`suspicious_requires_behavior=False`).
- A previously verified friendly losing contact keeps its identity while the evidence supports it, then fades to **unknown** without new risk evidence. A dead or jammed transmitter is not an enemy cue. Coasting and observation age describe the lost contact separately from its assessment; fresh matching beacons can restore friendly identity.
- **Silence counts for less on a lossy link.** The estimator measures what share of the expected beacons arrive from tracks it already calls friendly (`delivery_rate`, forgetting over 30 s) and scales the silence penalty by it. At 90 % loss a friendly's missing beacons say little, so friendlies are not flagged; the price is that a silent intruder is flagged later. If every beacon is lost, the estimator cannot tell a jam from a dead link, so nobody is condemned and friendlies fade slowly.
- A beacon stamped slightly in the future is treated as clock offset (`beacon_clock_tolerance_s`), not discarded.
- **Two kinds of evidence.** The beacon axis (friendly or not) is moved by beacons and silence. The behaviour axis (hostile-like or peaceful-like, `p_hostile`) is moved **only** by the `threat_llr` hook, which the drone-behaviour module is meant to provide: per update, a positive number is hostile-like and a negative one peaceful-like. It forgets over 20 s, so a track that changes behaviour changes class.
- **Hostile and peaceful both need behavior evidence.** Silence establishes neither. A beacon match is primary: a friendly stays friendly whatever its behaviour looks like. See [the automatic rules](../drone_behavior/drone_behavior.md#evidence-rules) for sustained safe transit, safe orbit, protected entry and persistent loiter. Behavior never establishes ally identity.
- Only suspicious tracks are investigated, one request per track at a time, with a cooldown. A peaceful track is still tracked and counted but never sent a drone; a hostile one needs no identification.
- The hook changed: it was `behaviour_llr` on the beacon scale (negative = hostile-like). It is now `threat_llr` on its own scale (positive = hostile-like). Nobody has built against the old one.

All thresholds are in `EstimatorConfig` and are placeholders. Inputs are dataclasses mirroring the draft `LocalTrack` and `FriendlyBeacon`; replace them with the shared schemas once frozen.

## Scenario adapter (test stand-in)

`frames_from_scenario` produces tracks for every friendly, hostile and clutter object (birds and vehicles, which never send beacons) from the motion formulas in `scenario.json` plus position noise, and beacons from the scenario's `beacon` settings. It applies the scenario's `degradations`, each only when its `enabled` is true: network (loss, bursty loss, delay from `latency_ms`), clock (per-node offset and drift stamp the beacon) and pose (position error added, reported as honest sigma). Assumptions where the scenario only gives ranges: bursts have a mean length of 5 messages with the configured average loss; offset and drift get a random sign. **Not modelled:** jamming zones, node dropout, topology. It never reads `truth.json`. A real tracker would not have clean tracks or know the ids, so results on it show the estimator's logic, not the real system's accuracy. Replace the adapter with the real tracker output once it exists.

## Beacon-only baseline results (adapter, `medium` preset, 20 test seeds, clear weather)

Run `python -m friend_foe.sweep --set test --seeds 20`. Tuned on the tuning seeds only; no number below was fitted to the test seeds.

| Beacon loss | Friendlies flagged (of 5) | Friendly time flagged | Hostile called friendly | Time to confirm a friendly | Time to flag a hostile | Requests sent to friendlies |
|-------------|---------------------------|-----------------------|-------------------------|----------------------------|------------------------|-----------------------------|
| 0 % | 0 | 0 % | 0 % | 2.0 s | 4.0 s | 0 |
| 10 % | 0 | 0 % | 0 % | 2.0 s | 4.6 s | 0 |
| 30 % | 0 | 0 % | 0 % | 2.3 s | 5.6 s | 0 |
| 50 % | 0 | 0 % | 0 % | 3.1 s | 7.4 s | 0 |
| 70 % | 0 | 0 % | 0 % | 5.5 s | 10.8 s | 0 |
| 90 % | 1.9 | 3 % | 0 % | 27.6 s | 10.3 s | 1.6 |

Bursty loss with the same averages gives the same picture (at 90 %: 1.7 friendlies flagged, 27.2 s to confirm). Before the delivery-rate weighting, at 90 % loss 3.75 of 5 friendlies were flagged and about 6 drones were sent at friendlies (tuning seeds). A hostile is never called friendly at any loss. Weather does not change the classification; it changes the standoff: mean requested standoff is 105 m in clear weather and wind, and 73.5 m in fog and rain, and none of these requests was infeasible because the scenarios carry a thermal camera.

## Drones wasted on clutter (adapter, `medium` preset, 20 test seeds, 15 % beacon loss, clear weather)

In the raw beacon-only baseline, birds and vehicles have no beacons, so they look exactly like silent hostiles: `suspicious`, and each one is sent a drone. The automatic pipeline requires behavioral risk before dispatching. Historical baseline mean investigation requests per 120 s run (the trigger repeats a request after 30 s when no drone answers, so these include repeats):

| Clutter objects | No behaviour module: requests in total | of which on clutter | Perfect behaviour module (oracle, upper bound) |
|-----------------|----------------------------------------|---------------------|-----------------------------------------------|
| none | 10.2 | 0 | 0 |
| 2 birds + 2 vehicles | 22.4 | 12.2 (54 %) | 0 |
| 5 birds + 5 vehicles | 39.5 | 29.3 (74 %) | 0 |

With a perfect module (a **test oracle that cheats from the track id**, not a real module) clutter is called peaceful 98 % of the time and hostiles are called hostile, so no drone is needed at all and none is sent at a bird. A real module will be somewhere in between. The point: **the behaviour module is what saves the drones**, and a hostile called peaceful is the worst error, so `hostile_as_peaceful_frac` is in every evaluation (0 here, 80 % or more for a deliberately wrong oracle in the tests).

## Limits of all results

90 % loss still flags friendlies sometimes; weather only reaches the standoff here, not the beacons; the hard preset's node dropout and jamming zones are not modelled; clutter is drawn from the seeder's assumed signatures and motion, and the adapter's tracks are clean (a real tracker would see birds and vehicles less cleanly); the peaceful thresholds are assumptions; all numbers come from the adapter's synthetic tracks, not a real tracker.
