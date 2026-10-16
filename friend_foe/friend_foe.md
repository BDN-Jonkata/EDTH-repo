# friend_foe module

Friend/foe classification: friendly beacon matching plus the Drone Behaviour pattern module.

Status: estimator and investigation trigger done on synthetic data; behaviour pattern not started. See [system design](../docs/system-design.md).

## What exists

| File | Contents |
|------|----------|
| [estimator.py](estimator.py) | `FriendFoeEstimator`: per-track evidence, beacon matching, class friendly / hostile / suspicious / unknown with probability and hysteresis |
| [investigation.py](investigation.py) | `InvestigationTrigger`: raises `InvestigationRequest` for tracks that stay suspicious, with weather-based standoff, cooldown and status feedback |
| [jsonl_io.py](jsonl_io.py) | Reads JSON Lines files of `local_track` and `friendly_beacon` messages into frames |
| [make_synthetic.py](make_synthetic.py) | Generates [data/local_tracks.jsonl](data/local_tracks.jsonl) |
| [demo.py](demo.py) | `python -m friend_foe.demo [path] [weather]` |
| [test_estimator.py](test_estimator.py) | Tests |

## Rules

- A fresh beacon consistent with a track pushes it toward friendly. Each beacon matches only its nearest track.
- Silence lowers confidence slowly, to a floor. Silence alone makes a track suspicious, never hostile, because beacons can be jammed.
- Hostile needs evidence from the `behaviour_llr` hook, which the drone-behaviour module is meant to provide (negative value = hostile-like).
- Only suspicious tracks are investigated, one request per track at a time, with a cooldown.

All thresholds are in `EstimatorConfig` and are placeholders. Inputs are dataclasses mirroring the draft `LocalTrack` and `FriendlyBeacon`; replace them with the `common/` schemas once frozen.
