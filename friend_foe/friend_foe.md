# friend_foe module

Friend/foe classification: friendly beacon matching plus the Drone Behaviour pattern module.

Status: estimator and investigation trigger done and tested on synthetic data and on seeder-generated scenarios; behaviour pattern not started. See [system design](../docs/system-design.md).

## What exists

| File | Contents |
|------|----------|
| [estimator.py](estimator.py) | `FriendFoeEstimator`: per-track evidence, beacon matching, class friendly / hostile / suspicious / unknown with probability and hysteresis |
| [investigation.py](investigation.py) | `InvestigationTrigger`: raises `investigation_request` for tracks that stay suspicious, with the weather-based standoff per catalog module, cooldown and status feedback |
| [drone_status.py](drone_status.py) | `DroneStatusMapper`: turns the mock simulation's `drone_state` messages (and commands reported lost) into `investigation_status`, using the mapping in [data-formats.md](../docs/data-formats.md); feed the result to `InvestigationTrigger.on_status` |
| [scenario_adapter.py](scenario_adapter.py) | Turns a `scenario.json` into estimator input frames: **test stand-in** for the tracker and beacon source (see below) |
| [jsonl_io.py](jsonl_io.py) | Reads JSON Lines files of `local_track` and `friendly_beacon` messages into frames |
| [make_synthetic.py](make_synthetic.py) | Generates [data/local_tracks.jsonl](data/local_tracks.jsonl) |
| [demo.py](demo.py) | `python -m friend_foe.demo [file.jsonl or scenario.json] [weather]` |
| [test_estimator.py](test_estimator.py), [test_scenario_adapter.py](test_scenario_adapter.py), [test_drone_status.py](test_drone_status.py) | Tests |

Message formats are in [data-formats.md](../docs/data-formats.md).

## Rules

- A fresh beacon consistent with a track pushes it toward friendly. Each beacon matches only its nearest track.
- Silence lowers confidence slowly, to a floor. Silence alone makes a track suspicious, never hostile, because beacons can be jammed.
- Hostile needs evidence from the `behaviour_llr` hook, which the drone-behaviour module is meant to provide (negative value = hostile-like).
- Only suspicious tracks are investigated, one request per track at a time, with a cooldown.

All thresholds are in `EstimatorConfig` and are placeholders. Inputs are dataclasses mirroring the draft `LocalTrack` and `FriendlyBeacon`; replace them with the shared schemas once frozen.

## Scenario adapter (test stand-in)

`frames_from_scenario` produces tracks for every friendly and hostile from the motion formulas in `scenario.json` plus position noise, and beacons from the scenario's `beacon` settings with `degradations.network.loss` applied. It never reads `truth.json`. A real tracker would not have clean tracks or know the ids, so results on it show the estimator's logic, not the real system's accuracy. On the generated scenarios all friendlies end `friendly` and all hostiles `suspicious`, and no friendly is ever investigated. Replace the adapter with the real tracker output once it exists.
