"""Out-of-sequence readings: a reading that arrives late is applied to its track at the time it was taken.

Each track keeps a checkpoint (its state at some time in the recent past) and a log of the readings applied since,
each with the time it was applied and the state it left the track in. A late reading is put into that log by its own
time: the track goes back to the state just before it, takes the reading, and the logged readings after it are applied
again, so the filter ends up as if the reading had come on time. Only the entries after the reading are redone, so a
reading that is only a fraction of a second late costs a few updates. The log covers `oosm_window_s`; older readings
are folded into the checkpoint, and a reading older than the checkpoint is dropped.

Replay is exact for this filter and simple; the cheaper one-step-lag methods are only good for short delays, and
here the delays are seconds (delay bursts). Only the tracker's own readings are logged, not beacons: friendly tracks
are not replayed. Off unless `TrackerConfig.oosm` is set, so the baseline is unchanged.
"""

from typing import List, Optional, Tuple

from tracker.ekf import Mat, Vec, predict
from tracker.measurement import Measurement
from tracker.models import apply_measurement

Checkpoint = Tuple[float, Vec, Mat]   # time, state, covariance
Entry = Tuple[float, Measurement, Vec, Mat]   # time it was applied, the reading, the state and covariance it left


def start_log(track, t: float) -> None:
    """The track's history starts now: its checkpoint is the state it was born with."""
    track.checkpoint = (t, list(track.state), [list(row) for row in track.cov])
    track.log = []


def record(track, t: float, m: Measurement) -> None:
    """A reading was just applied to the track at time `t`: keep it with the state it left."""
    track.log.append((t, m, list(track.state), [list(row) for row in track.cov]))


def _advance(state: Vec, cov: Mat, t_from: float, t_to: float, accel: float):
    return predict(state, cov, t_to - t_from, accel) if t_to > t_from else (state, cov)


def _before(track, t: float) -> Tuple[int, Checkpoint]:
    """(number of log entries at or before `t`, the track's state after the last of them or at the checkpoint)."""
    k = len(track.log)
    while k > 0 and track.log[k - 1][0] > t:
        k -= 1
    if k == 0:
        return 0, track.checkpoint
    te, _m, state, cov = track.log[k - 1]
    return k, (te, state, cov)


def state_at(track, accel: float, t_query: float, now: float, current_state: Vec, current_cov: Mat):
    """The track as it was at `t_query`, or None when that is older than its history. A track without a log
    (a friendly's) is taken back along its velocity, which is enough to tell whether a late reading is its own."""
    if getattr(track, "checkpoint", None) is None:
        dt = now - t_query
        return [current_state[0] - current_state[2] * dt, current_state[1] - current_state[3] * dt,
                current_state[2], current_state[3]], current_cov
    if track.checkpoint[0] > t_query:
        return None
    _k, (t, state, cov) = _before(track, t_query)
    return _advance(state, cov, t, t_query, accel)


def insert(track, accel: float, m: Measurement, until: float):
    """Put a late reading into the track's history by its own time and return (state, cov) at `until`: the track
    goes back to just before the reading, takes it, and the readings logged after it are applied again."""
    k, (t, state, cov) = _before(track, m.t)
    state, cov = apply_measurement(*_advance(state, cov, t, m.t, accel), m)
    t, redone = m.t, [(m.t, m, state, cov)]
    for te, later, _s, _c in track.log[k:]:
        state, cov = apply_measurement(*_advance(state, cov, t, te, accel), later)
        t = te
        redone.append((te, later, state, cov))
    track.log[k:] = redone
    return _advance(state, cov, t, until, accel)


def fold_old(track, t: float, window_s: float) -> None:
    """Readings older than the window go into the checkpoint, so the log stays short."""
    while track.log and track.log[0][0] < t - window_s:
        te, _m, state, cov = track.log.pop(0)
        track.checkpoint = (te, state, cov)
