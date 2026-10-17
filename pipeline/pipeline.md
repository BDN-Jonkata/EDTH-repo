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
