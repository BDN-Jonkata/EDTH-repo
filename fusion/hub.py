"""The merger's own tracker for bearings.

A node with only a camera, RF receiver or microphone array cannot start a track: one bearing says nothing
about range. Every node forwards its bearings (`bearing_report`, a few numbers each, not the raw
observation); here they are crossed with other nodes' bearings by the same baseline tracker, and its
confirmed tracks are shared like any node's, to be merged with the node tracks. Forwarding only the bearings
no node track took was tried first and gained little: the useful pairs are a bearing from one node and a
bearing, or a radar track, from another. The hub also gets the beacons; without them it started ghost tracks
on the friendly drones.
"""

from typing import List, Optional, Sequence

from common.codec import Sequencer
from fusion.messages import local_track_message, measurement_from_report
from tracker.tracker import Tracker, TrackerConfig

HUB = "hub"


class BearingHub:
    def __init__(self, config: Optional[TrackerConfig] = None):
        self.tracker = Tracker(config)
        self.sequencer = Sequencer(HUB)

    def step(self, t: float, delivered: Sequence[dict]) -> List[dict]:
        """Track the bearing reports that arrived; returns the hub's tracks as `local_track` messages."""
        readings = [measurement_from_report(m) for m in delivered if m["type"] == "bearing_report"]
        beacons = [m for m in delivered if m["type"] == "friendly_beacon"]       # so a friend's bearings are absorbed
        return [local_track_message(HUB, tr, t, self.sequencer) for tr in self.tracker.step(t, readings, beacons)]
