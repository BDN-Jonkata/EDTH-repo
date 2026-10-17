"""Out-of-sequence readings: a reading that arrives late is applied to its track at the time it was taken.

Each track keeps a checkpoint (its state at some time in the recent past) and a log of the readings applied since,
each with the time it was applied. A late reading is put into that log by its own time and the track is replayed
from the checkpoint to now, so the filter ends up as if the reading had come on time. The log covers
`oosm_window_s`; older readings are folded into the checkpoint, and a reading older than the checkpoint is dropped.

Replay is exact for this filter and simple; the cheaper one-step-lag methods are only good for short delays, and
here the delays are seconds (delay bursts). Only the tracker's own readings are logged, not beacons: friendly tracks
are not replayed. Off unless `TrackerConfig.oosm` is set, so the baseline is unchanged.
"""

from typing import List, Optional, Tuple

from tracker.ekf import Mat, Vec, predict
from tracker.measurement import Measurement
from tracker.models import apply_measurement

Checkpoint = Tuple[float, Vec, Mat]   # time, state, covariance
Event = Tuple[float, Measurement]     # time it was applied, the reading


def start_log(track, t: float) -> None:
    """The track's history starts now: its checkpoint is the state it was born with."""
    track.checkpoint = (t, list(track.state), [list(row) for row in track.cov])
    track.log = []


def record(track, t: float, m: Measurement) -> None:
    track.log.append((t, m))


def _advance(state: Vec, cov: Mat, t_from: float, t_to: float, accel: float):
    return predict(state, cov, t_to - t_from, accel) if t_to > t_from else (state, cov)


def replay(track, accel: float, until: float, extra: Optional[Measurement] = None):
    """(state, cov) of the track at `until`: from its checkpoint, with the logged readings (and `extra`, taken at
    `extra.t`) applied in time order."""
    t, state, cov = track.checkpoint
    events: List[Event] = list(track.log) + ([(extra.t, extra)] if extra is not None else [])
    for te, m in sorted(events, key=lambda e: e[0]):
        if te > until:
            break
        state, cov = _advance(state, cov, t, te, accel)
        state, cov = apply_measurement(state, cov, m)
        t = te
    return _advance(state, cov, t, until, accel)


def state_at(track, accel: float, t_query: float, now: float, current_state: Vec, current_cov: Mat):
    """The track as it was at `t_query`, or None when that is older than its history. A track without a log
    (a friendly's) is taken back along its velocity, which is enough to tell whether a late reading is its own."""
    if getattr(track, "checkpoint", None) is None:
        dt = now - t_query
        return [current_state[0] - current_state[2] * dt, current_state[1] - current_state[3] * dt,
                current_state[2], current_state[3]], current_cov
    if track.checkpoint[0] > t_query:
        return None
    return replay(track, accel, t_query)


def fold_old(track, t: float, window_s: float, accel: float) -> None:
    """Readings older than the window go into the checkpoint, so the log stays short."""
    while track.log and track.log[0][0] < t - window_s:
        te, m = track.log.pop(0)
        t0, state, cov = track.checkpoint
        state, cov = apply_measurement(*_advance(state, cov, t0, te, accel), m)
        track.checkpoint = (te, state, cov)


def insert(track, m: Measurement) -> None:
    """Put a late reading into the log in time order (it has already been replayed into the state)."""
    track.log.append((m.t, m))
    track.log.sort(key=lambda e: e[0])
