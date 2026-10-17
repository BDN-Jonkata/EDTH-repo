"""The `local_track` message: how a node shares one of its tracks (docs/data-formats.md).

The tracker is 2D, so z and vz are sent as 0 with a large variance; only x, y, vx, vy carry information.
"""

from typing import Optional

from common.codec import Sequencer
from tracker.measurement import BEARING, Measurement, Pose2D
from tracker.tracker import Track

Z_VARIANCE = 1e4
POSITION_AXES = (0, 1, 3, 4)        # where x, y, vx, vy sit in the 6-vector


def local_track_message(node: str, track: Track, t: float, sequencer: Sequencer) -> dict:
    x, y, vx, vy = track.state
    cov = [[0.0] * 6 for _ in range(6)]
    for i, a in enumerate(POSITION_AXES):
        for j, b in enumerate(POSITION_AXES):
            cov[a][b] = track.cov[i][j]
    cov[2][2] = cov[5][5] = Z_VARIANCE
    message = {"type": "local_track", "header": sequencer.header(t), "local_track_id": f"{node}/{track.track_id}",
               "t_state": t, "state": [x, y, 0.0, vx, vy, 0.0], "covariance": cov, "existence_prob": 0.95}
    if track.friend_id is not None:
        message["friend_id"] = track.friend_id
    return message


def state_and_cov(message: dict):
    """The 4-vector and 4x4 covariance in a `local_track` message."""
    state = [message["state"][a] for a in POSITION_AXES]
    cov = [[message["covariance"][a][b] for b in POSITION_AXES] for a in POSITION_AXES]
    return state, cov


def bearing_report_message(m: Measurement, sequencer: Sequencer) -> dict:
    """A bearing no node track took, shared so the merger can cross it with another node's bearing."""
    p = m.pose
    return {"type": "bearing_report", "header": sequencer.header(m.t), "t_obs": m.t, "sensor_id": m.sensor_id,
            "pose": [p.x, p.y, p.vx, p.vy, p.sigma], "max_range_m": m.max_range_m, "bearing": m.bearing,
            "sigma_bearing": m.sigma_bearing}


def measurement_from_report(message: dict) -> Measurement:
    x, y, vx, vy, sigma = message["pose"]
    return Measurement(BEARING, message["t_obs"], message["header"]["source_id"], message["sensor_id"],
                       Pose2D(x, y, vx, vy, sigma), message["max_range_m"], bearing=message["bearing"],
                       sigma_bearing=message["sigma_bearing"])


def friend_id_of(message: dict) -> Optional[str]:
    return message.get("friend_id")
