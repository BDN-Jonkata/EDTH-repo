# common module

Shared message schemas (Observation, LocalTrack, FriendlyBeacon, Track), time and coordinate utilities, message bus interface.

Status: codec started; schemas, time/frame helpers and bus not started. See [system design](../docs/system-design.md).

## What exists

| File | Contents |
|------|----------|
| [codec.py](codec.py) | `encode(msg) -> bytes`, `decode(bytes) -> msg` (JSON for now), `make_header`, `CodecError`, `MessageSizeLog` (messages and bytes per type) |
| [test_codec.py](test_codec.py) | Tests |

Every message crossing a link goes through `encode` / `decode`, so a compact binary format can replace JSON later without touching other modules. Decoding rejects corrupted bytes, missing `type` or header fields, and a wrong `schema_version` with `CodecError`. Messages are plain dicts until the schemas are frozen.

Baseline for later comparison: a friendly beacon is about 190 bytes as JSON.
