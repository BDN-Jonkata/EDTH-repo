"""Encode and decode messages at the channel boundary.

JSON for now. Everything that crosses a link goes through `encode` / `decode`,
so a compact binary format (Protobuf, CBOR) can replace the body of these two
functions later without touching any module. Messages are plain dicts until
the schemas in this package are frozen.

Every message has a top-level `type` and a `header` with `msg_id`,
`source_id`, `t_sent`, `seq` and `schema_version`.
"""

import json
from collections import defaultdict
from typing import Any, Dict, Optional

SCHEMA_VERSION = 1
HEADER_FIELDS = ("msg_id", "source_id", "t_sent", "seq", "schema_version")


class CodecError(ValueError):
    """Bytes could not be decoded into a valid message (corrupted, wrong version, malformed)."""


def make_header(source_id: str, t_sent: float, seq: int) -> dict:
    return {
        "msg_id": f"{source_id}-{seq}",
        "source_id": source_id,
        "t_sent": t_sent,
        "seq": seq,
        "schema_version": SCHEMA_VERSION,
    }


class Sequencer:
    """Headers for one source. `seq` counts every message that source sends, whatever
    its type, starting at 1, so `msg_id` is unique per source (first one: `C2-1`)."""

    def __init__(self, source_id: str):
        self.source_id = source_id
        self._next = 1

    def header(self, t_sent: float) -> dict:
        header = make_header(self.source_id, t_sent, self._next)
        self._next += 1
        return header


def _round_sig(value: Any, digits: int) -> Any:
    """Round every float to `digits` significant digits; leave everything else alone."""
    if isinstance(value, float):
        return float(f"{value:.{digits}g}")
    if isinstance(value, dict):
        return {k: _round_sig(v, digits) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_round_sig(v, digits) for v in value]
    return value


def encode(msg: dict, precision: Optional[int] = None) -> bytes:
    """JSON bytes. `precision` = significant digits for floats (None keeps full precision).

    json writes 15-17 digits per float, which inflates message sizes far beyond what
    a real link would carry. Significant digits (not decimal places) keep small values
    such as covariances intact: 6 digits gives 123.457 m and 0.000412346."""
    if precision is not None:
        msg = _round_sig(msg, precision)
    return json.dumps(msg, separators=(",", ":")).encode("utf-8")


def decode(data: bytes) -> dict:
    try:
        msg = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise CodecError(f"not valid JSON: {e}") from e
    if not isinstance(msg, dict) or "type" not in msg:
        raise CodecError("message has no type")
    header = msg.get("header")
    if not isinstance(header, dict):
        raise CodecError("message has no header")
    missing = [f for f in HEADER_FIELDS if f not in header]
    if missing:
        raise CodecError(f"header missing {missing}")
    if header["schema_version"] != SCHEMA_VERSION:
        raise CodecError(f"schema_version {header['schema_version']} != {SCHEMA_VERSION}")
    return msg


class MessageSizeLog:
    """Counts messages and bytes per message type, to report bandwidth."""

    def __init__(self, precision: Optional[int] = None) -> None:
        self.precision = precision
        self.count: Dict[str, int] = defaultdict(int)
        self.bytes: Dict[str, int] = defaultdict(int)

    def record(self, msg: dict, data: bytes) -> None:
        self.count[msg["type"]] += 1
        self.bytes[msg["type"]] += len(data)

    def encode(self, msg: dict) -> bytes:
        data = encode(msg, self.precision)
        self.record(msg, data)
        return data

    def summary(self) -> Dict[str, dict]:
        return {
            t: {"count": n, "bytes": self.bytes[t], "avg_bytes": self.bytes[t] / n}
            for t, n in self.count.items()
        }
