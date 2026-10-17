"""Distributed mode: every node runs its own tracker on its own readings and shares its tracks.

In the central pipeline one tracker sees every delivered reading. Here a node's readings go only to that
node's tracker (a node's own sensors need no network), and every `SEND_EVERY` steps the node sends its
confirmed tracks as `local_track` messages through the lossy channel to the merger (`fusion/merger.py`).
Beacons still reach every node's tracker, so each has its own friend tracks. Simplifications: a node's
own readings are used without their sensor latency, and a node's pose comes from the beacon-based
pose book like in the central mode, not from its own navigation.
"""

from typing import Dict, List, Optional, Sequence

from common.codec import Sequencer
from fusion.messages import bearing_report_message, local_track_message
from tracker.measurement import BEARING
from tracker.tracker import Tracker, TrackerConfig

SEND_EVERY = 5          # steps of 0.1 s: tracks are shared at 2 Hz, like the beacons


class NodeTrackers:
    def __init__(self, config: Optional[TrackerConfig], sequencers: Dict[str, Sequencer]):
        self.config, self.sequencers = config, sequencers
        self.trackers: Dict[str, Tracker] = {}
        self._steps = 0

    def step(self, t: float, readings: Sequence, beacons: Sequence[dict]) -> List[dict]:
        """Advance every node's tracker; returns the `local_track` messages due this step."""
        by_node: Dict[str, list] = {}
        for m in readings:
            by_node.setdefault(m.node, []).append(m)
        for node in by_node:
            self.trackers.setdefault(node, Tracker(self.config))
        confirmed = {node: tracker.step(t, by_node.get(node, []), beacons) for node, tracker in self.trackers.items()}
        reports = [bearing_report_message(m, self._sequencer(node))
                   for node, node_readings in by_node.items() for m in node_readings if m.kind == BEARING]
        self._steps += 1
        if (self._steps - 1) % SEND_EVERY:
            return reports
        return reports + [local_track_message(node, tr, t, self._sequencer(node))
                          for node, tracks in confirmed.items() for tr in tracks]

    def _sequencer(self, node: str) -> Sequencer:
        return self.sequencers.setdefault(node, Sequencer(node))
