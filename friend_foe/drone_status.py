"""Turn the drone side's messages into `investigation_status` messages.

The mapping is the one in docs/data-formats.md ("Drone commands"):

    drone_state  accepted                    -> assigned
                 accepted, mode goto/return  -> en_route (after assigned)
                 on_station                  -> on_station
                 patrolling, after a check   -> done
                 rejected                    -> aborted
    a command the sender reported lost       -> aborted

A `patrolling` message after `return_to_patrol` often carries no `track_id`, and a
lost command only shows up in C2's own log, so the mapper remembers which track
each command and each drone is working on.
"""

from typing import Dict, List, Optional

from common.codec import Sequencer


class DroneStatusMapper:
    def __init__(self, source_id: str = "estimator"):
        self._sequencer = Sequencer(source_id)
        self._command: Dict[str, dict] = {}       # command_id -> {drone_id, track_id}
        self._active_track: Dict[str, str] = {}   # drone_id -> track it is checking

    def note_command(self, command: dict) -> None:
        """Remember a `drone_command` that was sent (or a scenario `commands[]` entry)."""
        self._command[command["command_id"]] = {
            "drone_id": command["drone_id"],
            "track_id": command.get("track_id"),
        }

    def from_drone_state(self, msg: dict) -> List[dict]:
        drone, state = msg["drone_id"], msg["state"]
        track = self._track_of(msg)
        if track is None:
            return []
        t = msg["header"]["t_sent"]
        if state == "accepted":
            self._active_track[drone] = track
            states = ["assigned"] + (["en_route"] if msg.get("mode") in ("goto", "return") else [])
        elif state == "rejected":
            self._active_track.pop(drone, None)
            states = ["aborted"]
        elif state == "on_station":
            states = ["on_station"]
        elif state == "patrolling":
            self._active_track.pop(drone, None)
            states = ["done"]
        else:
            return []
        return [self._status(t, track, drone, s) for s in states]

    def from_command_lost(self, command_id: str, t: float) -> List[dict]:
        known = self._command.get(command_id)
        if known is None or known["track_id"] is None:
            return []
        self._active_track.pop(known["drone_id"], None)
        return [self._status(t, known["track_id"], known["drone_id"], "aborted")]

    def _track_of(self, msg: dict) -> Optional[str]:
        """The track a drone_state is about: its own field, else the command's, else what the drone is checking."""
        known = self._command.get(msg.get("command_id"), {})
        return msg.get("track_id") or known.get("track_id") or self._active_track.get(msg["drone_id"])

    def _status(self, t: float, track_id: str, drone_id: str, state: str) -> dict:
        return {
            "type": "investigation_status",
            "header": self._sequencer.header(t),
            "track_id": track_id,
            "drone_id": drone_id,
            "state": state,
        }
