# fusion module

Track merge across nodes (covariance intersection), global ID management, COP assembly. See [system design](../docs/system-design.md) 5.5.

Status: built and tested; **optional** (`python -m pipeline.sweep --distributed`). The default pipeline is still one central tracker. Not done: a merger that moves between nodes when a link is down (there is one merger that hears what the channel delivers), tracker-side use of the merged picture, and out-of-order messages.

## What exists

| File | Contents |
|------|----------|
| [ci.py](ci.py) | `intersect`, `intersect_all`: covariance intersection of 4x4 estimates, the weight chosen for the smallest position uncertainty; a small matrix inverse |
| [messages.py](messages.py) | `local_track_message` and `state_and_cov`: the `local_track` message of [data-formats.md](../docs/data-formats.md) (z sent as 0 with a large variance, `friend_id` when the track is a friend's) |
| [hub.py](hub.py) | `BearingHub`: the merger's own baseline tracker on the `bearing_report` messages every node forwards (a camera, RF or microphone node cannot start a track alone). Its tracks are shared like a node's |
| [merger.py](merger.py) | `Merger`: `ingest(messages)`, `step(t)` returns merged `Track`s with global IDs |
| `test_fusion.py` | Tests |

The per-node trackers and their wiring are in [pipeline/nodes.py](../pipeline/nodes.py) (each node's tracker is the baseline [tracker](../tracker/tracker.md) on that node's own readings).

## How it works

- Each node tracks what its own sensors read and, every 0.5 s, sends its confirmed tracks (including the friend tracks from beacons) as `local_track` messages through the lossy channel. Raw readings never leave the node.
- Every node also forwards each bearing it measured as a `bearing_report` (time, sensor, the sensor's pose with its uncertainty, bearing and noise; not the raw observation). The hub crosses bearings from different nodes into tracks, exactly as the central tracker does, and its tracks go into the merge like a node's.
- The merger keeps the latest estimate of every local track it heard, moves each to now with constant velocity, and drops one unheard for 4 s.
- **Same object?** Tracks of different nodes are grouped when the Mahalanobis distance of their positions, with the two covariances added, is inside a 99 % gate (or they are within 10 m), closest pairs first. A group never holds two tracks of one node.
- **Merge.** A group is merged with covariance intersection, because two nodes' errors are correlated (shared beacons and pose errors) and adding them as independent would be over-confident.
- **Global IDs.** A global ID is tied to the local tracks in its group, so it survives a node joining or leaving the group and a local track getting a new ID; if a group holds several global IDs the oldest wins. An ID with no member left is freed.

## Result (tuning seeds 1 to 5, `medium`, clear, `python -m pipeline.sweep --paired distributed`)

Mean difference, distributed minus central, with standard error:

| Loss | Hostile detected | False tracks per step | Position RMSE | OSPA | Count error bias | ID swaps |
|------|------------------|-----------------------|---------------|------|------------------|----------|
| 0 % | -0.07±0.03 | -0.29±0.09 | -0.5±2.1 m | -0.1±4.1 m | -0.46±0.14 | -0.2±1.2 |
| 50 % | -0.04±0.02 | +0.23±0.10 | -3.0±1.3 m | +2.1±2.1 m | +0.13±0.10 | +3.8±1.6 |

At 0 % loss the distributed system is close to the central one (hostiles tracked 7 points less, fewer ghost tracks, same position and OSPA). At 50 % loss it tracks 4 points less and swaps IDs more (3.8±1.6 per run), probably because each lost `local_track` message makes a group lose a member for a moment. These are tuning seeds and 5 runs; the test seeds have not been used.

**How the gap was closed in steps (0 % loss, hostile detected, distributed minus central):** nodes alone, 16 points less; adding the bearing hub with only the bearings no node track took, 14 less; forwarding all bearings, 8 less but with 0.8 more false tracks per step and friendlies flagged, because the hub started ghost tracks on the friendly drones; giving the hub the beacons, 7 less with fewer false tracks than central.

## Simplifications

A node's readings are used without their sensor latency; a node's pose comes from the delivered beacons, as in the central tracker, not from its own navigation; the merger is one place and always reachable except for message loss; each node's tracker sees every delivered beacon.
