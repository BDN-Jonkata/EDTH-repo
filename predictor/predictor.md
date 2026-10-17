# predictor module

Short-horizon prediction on top of tracker output, used to hold identity. See [system design](../docs/system-design.md) 5.6 and 5.7.

Status: a **constant-velocity identity keeper** is built and tested. It is **off by default** because it did not measurably help (below). Not done: a learned predictor, and using predictions inside the tracker's association at the close crossing.

## What exists

| File | Contents |
|------|----------|
| [identity.py](identity.py) | `IdentityKeeper().step(t, tracks)` returns the confirmed tracks with stable IDs. It remembers each lost confirmed track, extrapolates it with constant velocity, and gives its ID to a new confirmed track that falls inside the growing gate (3 sigma, 20 to 120 m) with a similar velocity. Friend tracks are not touched. |
| `test_identity.py` | Tests |

Run it with `python -m pipeline.sweep --keep-identity`, or compare on the same seeds with `--paired identity`.

## Why

Most ID swaps in the pipeline look like re-acquisitions: a confirmed track is dropped after about 10 s without a reading, and a new track with a new ID starts later (see [tracker.md](../tracker/tracker.md)). The idea: predict where the lost target should be and hand its ID back.

## Result: no measurable effect

`python -m pipeline.sweep --paired identity --set tuning --seeds 5 --losses 0,0.5`: ID swaps changed by 0.00±0.00 at 0 % loss and -0.20±0.20 at 50 %; every other column unchanged. One tuning seed, event by event: new tracks appeared 170 to 300 m from where the lost track should have been after 10 to 20 s, and the velocity of a new track is still rough when it is confirmed. Constant-velocity extrapolation over a gap that long is wrong, and a gate wide enough to catch them would give one target's ID to another. Many of the "lost" tracks are also ghost tracks, not hostiles, so there is nothing to bring back.

So the swaps are not mainly "same target, same path, long gap". Before spending more here, find out what they are (a swap between two hostiles at the crossing, a ghost taking over a hostile's match, or a restart) with a per-swap log from `scoring/`. Not done yet.
