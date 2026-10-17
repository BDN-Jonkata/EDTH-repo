# predictor module

Short-horizon prediction on top of tracker output, used to hold identity. See [system design](../docs/system-design.md) 5.6 and 5.7.

Status: **done, with a measured result of no effect.** A constant-velocity identity keeper and a learned motion model for its gate are built and tested. Both are **off by default** because neither changed the ID swaps (below). Not planned: using predictions inside the tracker's association at the close crossing (crossings are 1 to 2 of the swaps in 5 tuning runs, so the gain would be at most 0.2 to 0.4 swaps per run).

## What exists

| File | Contents |
|------|----------|
| [identity.py](identity.py) | `IdentityKeeper().step(t, tracks)` returns the confirmed tracks with stable IDs. It remembers each lost confirmed track, extrapolates it with constant velocity, and gives its ID to a new confirmed track that falls inside the growing gate (3 sigma, 20 to 120 m) with a similar velocity. Friend tracks are not touched. |
| [motion.py](motion.py) | `MotionModel`: the learned part. For horizons of 1 to 30 s it holds the rms distance of a track's real position from a straight-line extrapolation and the 95th percentile of its velocity change; `fit` pools pairs of samples of one track. Saved in [motion_model.json](motion_model.json) |
| [train.py](train.py) | `python -m predictor.train --seeds 5 --losses 0,0.3` samples the tracker's own confirmed, really-updated tracks once a second on the tuning seeds and fits the model. It never reads `truth.json` |
| `test_identity.py`, `test_motion.py` | Tests |

Run it with `python -m pipeline.sweep --keep-identity` (guessed gate) or `--keep-identity learned` (gate and velocity test from the learned model), or compare on the same seeds with `--paired identity`.

## Learned motion model

Fitted on 5 tuning seeds at 0 % and 30 % loss (57 tracks): the spread from a straight line is 7 m after 1 s, 20 m after 5 s, 49 m after 12 s and 160 m after 30 s; the 95th percentile of the velocity change is 2.9 m/s after 1 s and 10 m/s after 12 s. The old guess (3 m/s² of random acceleration) said 150 m after 10 s, so it was far too wide, and the new gate is much tighter. Only 57 tracks, from our own simulator: the numbers describe it, not real targets. The training seeds are the same as the ones measured below, so a gain would have been optimistic; there was none.

## Why

Most ID swaps in the pipeline look like re-acquisitions: a confirmed track is dropped after about 10 s without a reading, and a new track with a new ID starts later (see [tracker.md](../tracker/tracker.md)). The idea: predict where the lost target should be and hand its ID back.

## Result: no measurable effect

With the learned gate (`--paired identity --keep-identity learned`, the same 5 tuning seeds, 0 % and 50 % loss) the result is identical to the guessed gate: ID swaps 0.00±0.00 and -0.20±0.20, every other column 0.00. The first measurement, with the guessed gate:

`python -m pipeline.sweep --paired identity --set tuning --seeds 5 --losses 0,0.5`: ID swaps changed by 0.00±0.00 at 0 % loss and -0.20±0.20 at 50 %; every other column unchanged. One tuning seed, event by event: new tracks appeared 170 to 300 m from where the lost track should have been after 10 to 20 s, and the velocity of a new track is still rough when it is confirmed. Constant-velocity extrapolation over a gap that long is wrong, and a gate wide enough to catch them would give one target's ID to another. Many of the "lost" tracks are also ghost tracks, not hostiles, so there is nothing to bring back.

So the swaps are not mainly "same target, same path, long gap". Before spending more here, find out what they are (a swap between two hostiles at the crossing, a ghost taking over a hostile's match, or a restart) with a per-swap log from `scoring/`. Not done yet.
