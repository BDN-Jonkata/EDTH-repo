# friend_foe module

Friend/foe classification: friendly beacon matching plus the Drone Behaviour pattern module.

Status: estimator, investigation trigger and drone-status mapping done and tested on synthetic data and on seeder-generated scenarios (with beacon loss, bursts, delay and clock errors), plus a loss and weather sweep; behaviour pattern not started. See [system design](../docs/system-design.md).

## What exists

| File | Contents |
|------|----------|
| [estimator.py](estimator.py) | `FriendFoeEstimator`: per-track evidence, beacon matching, class friendly / hostile / suspicious / unknown with probability and hysteresis; weighs silence by the measured beacon delivery rate |
| [investigation.py](investigation.py) | `InvestigationTrigger`: raises `investigation_request` for tracks that stay suspicious, with the weather-based standoff per catalog module, cooldown and status feedback |
| [drone_status.py](drone_status.py) | `DroneStatusMapper`: turns the mock simulation's `drone_state` messages (and commands reported lost) into `investigation_status`, using the mapping in [data-formats.md](../docs/data-formats.md); feed the result to `InvestigationTrigger.on_status` |
| [scenario_adapter.py](scenario_adapter.py) | Turns a `scenario.json` into estimator input frames: **test stand-in** for the tracker and beacon source (see below) |
| [evaluate.py](evaluate.py) | `evaluate(scenario)`: friendly false alarms, hostiles called friendly, time to confirm and to flag, requests on friendlies, standoff |
| [sweep.py](sweep.py) | `python -m friend_foe.sweep`: the estimator over beacon loss (plain and bursty) and weather, tuning or test seeds, optional CSV |
| [jsonl_io.py](jsonl_io.py) | Reads JSON Lines files of `local_track` and `friendly_beacon` messages into frames |
| [make_synthetic.py](make_synthetic.py) | Generates [data/local_tracks.jsonl](data/local_tracks.jsonl) |
| [demo.py](demo.py) | `python -m friend_foe.demo [file.jsonl or scenario.json] [weather]` |
| `test_*.py` | Tests |

Message formats are in [data-formats.md](../docs/data-formats.md).

## Rules

- A fresh beacon consistent with a track pushes it toward friendly. Each beacon matches only its nearest track.
- Silence lowers confidence slowly, per second, to a floor. Silence alone makes a track suspicious, never hostile, because beacons can be jammed.
- **Silence counts for less on a lossy link.** The estimator measures what share of the expected beacons arrive from tracks it already calls friendly (`delivery_rate`, forgetting over 30 s) and scales the silence penalty by it. At 90 % loss a friendly's missing beacons say little, so friendlies are not flagged; the price is that a silent intruder is flagged later. If every beacon is lost, the estimator cannot tell a jam from a dead link, so nobody is condemned and friendlies fade slowly.
- A beacon stamped slightly in the future is treated as clock offset (`beacon_clock_tolerance_s`), not discarded.
- Hostile needs evidence from the `behaviour_llr` hook, which the drone-behaviour module is meant to provide (negative value = hostile-like).
- Only suspicious tracks are investigated, one request per track at a time, with a cooldown.

All thresholds are in `EstimatorConfig` and are placeholders. Inputs are dataclasses mirroring the draft `LocalTrack` and `FriendlyBeacon`; replace them with the shared schemas once frozen.

## Scenario adapter (test stand-in)

`frames_from_scenario` produces tracks for every friendly and hostile from the motion formulas in `scenario.json` plus position noise, and beacons from the scenario's `beacon` settings. It applies the scenario's `degradations`, each only when its `enabled` is true: network (loss, bursty loss, delay from `latency_ms`), clock (per-node offset and drift stamp the beacon) and pose (position error added, reported as honest sigma). Assumptions where the scenario only gives ranges: bursts have a mean length of 5 messages with the configured average loss; offset and drift get a random sign. **Not modelled:** jamming zones, node dropout, topology. It never reads `truth.json`. A real tracker would not have clean tracks or know the ids, so results on it show the estimator's logic, not the real system's accuracy. Replace the adapter with the real tracker output once it exists.

## Results (adapter, `medium` preset, 20 test seeds, clear weather)

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

Limits: 90 % loss still flags friendlies sometimes; weather only reaches the standoff here, not the beacons; the hard preset's node dropout and jamming zones are not modelled; all numbers come from the adapter's clean synthetic tracks.
