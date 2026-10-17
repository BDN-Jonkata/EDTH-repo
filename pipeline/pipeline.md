# pipeline

The whole chain on one scenario: sensors, lossy network, tracker, friend/foe, scoring.

Status: done and tested for the central baseline. See [tracker](../tracker/tracker.md), [sensors](../sensors/sensors.md), [scoring](../scoring/scoring.md).

| File | Contents |
|------|----------|
| [run.py](run.py) | `Pipeline(scenario, seed).step(t)`, `run(scenario, seed)` (frames of confirmed tracks), `scored_frames(scenario, seed)` (the tracks with the estimator's classes, ready for `scoring.metrics.score`) |
| [sweep.py](sweep.py) | `python -m pipeline.sweep --set test --seeds 20 [--weather fog+wind] [--birds 2 --vehicles 2] [--csv file]`: the metrics over message loss |
| `test_run.py` | End-to-end tests |

```
sensors/observe.py + sensors/beacons.py    what the nodes sense and send (needs the true positions)
common/channel.py                          loss, burst, delay from the scenario's degradations
tracker/ (+ PoseBook)                      one central tracker on what the channel delivered
friend_foe/                                classification from tracks and delivered beacons, every 0.5 s
scoring/                                   metrics against truth.json
```

Everything before the channel is the simulation side and may use the truth; the tracker and the estimator see only delivered messages. The clock is 0.1 s. Not modelled: jamming zones, node dropout, topology (see [common/channel.py](../common/channel.py)). Weather reaches the sensors per detection through the weather provider; it does not yet change the tracker.

Results: [tracker.md](../tracker/tracker.md#results).

## With the automatic behaviour module

`python -m pipeline.sweep --behaviour` puts `drone_behavior/` (`AutomaticEstimator`) behind the estimator. Test seeds 1000 to 1009, `medium` preset, 15 % message loss, clear weather:

| Clutter | Behaviour module | Count error | Clutter flagged | Hostile tracked | Friendlies flagged |
|---------|------------------|-------------|-----------------|-----------------|--------------------|
| none | off | 1.49 | 0 | 56 % | 0.2 |
| none | on | 1.49 | 0 | 56 % | 0.2 |
| 2 birds + 2 vehicles | off | 2.60 | 38 % | 53 % | 0.2 |
| 2 birds + 2 vehicles | on | 2.60 | 38 % | 53 % | 0.2 |

Identical: the module calls some tracks hostile (hostile is counted like suspicious here) but never calls anything peaceful on these tracks, because its peaceful evidence needs a clear authorized-corridor transit and its motion cues stay below the thresholds ("consistent transit" and "ambiguous motion" in `explain`). This agrees with its own documentation, which claims no bird or vehicle recognition. The oracle test in [friend_foe.md](../friend_foe/friend_foe.md) shows the hook could remove the wasted dispatches given better evidence.
