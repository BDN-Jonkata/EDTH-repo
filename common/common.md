# common module

Shared message schemas (Observation, LocalTrack, FriendlyBeacon, Track), time and coordinate utilities, message bus interface.

Status: codec started; schemas, time/frame helpers and bus not started. See [system design](../docs/system-design.md).

## What exists

| File | Contents |
|------|----------|
| [codec.py](codec.py) | `encode(msg, precision=None) -> bytes`, `decode(bytes) -> msg` (JSON for now), `make_header`, `Sequencer`, `CodecError`, `MessageSizeLog` (messages and bytes per type) |
| [channel.py](channel.py) | `Channel(scenario, seed, position_of)`: `send` and `deliver` with loss (independent or bursty, one chain per sender) and delay from `degradations.network`; also, when the scenario has them, jamming zones (needs `position_of(node, t)`), a link cap and node dropout, as in the viewer's mock simulation; `Loss`, `Clock` (a node's offset and drift) |
| [jamming.py](jamming.py), [linkcap.py](linkcap.py) | Python ports of `ui/viewer/jamming.js` and `linkcap.js` (the mock is the reference): `loss_at`, `rf_noise_mult`, `LinkCap` (enqueue, drain, summary) |
| [golden.py](golden.py) | `python -m common.golden` writes `testdata/channel_cases.json`, the cases both implementations must answer the same; `ui/viewer/test-channel-port.js` checks the JavaScript against it |
| [assignment.py](assignment.py) | `assign(cost, gate)`: optimal one-to-one assignment (Hungarian), pure Python; used by the tracker and by scoring |
| [seeder_import.py](seeder_import.py) | `ensure_seeder_on_path()`: lets other packages import the seeder's flat `catalog` and `scenario` modules |
| `test_codec.py`, `test_channel.py`, `test_golden.py` | Tests |

Every message crossing a link goes through `encode` / `decode`, so a compact binary format can replace JSON later without touching other modules. Decoding rejects corrupted bytes, missing `type` or header fields, and a wrong `schema_version` with `CodecError`. Messages are plain dicts until the schemas are frozen.

## Headers and sequence numbers

`Sequencer(source_id).header(t_sent)` makes the header. One sequencer per sending node: `seq` counts **every** message that node sends, whatever its type, and starts at 1, so `msg_id` is unique per source (the first message of C2 is `C2-1`). Use one sequencer per node, not one per message type, or ids collide.

## Precision and message size

`json` writes 15 to 17 digits per float, which makes messages bigger than a real link would carry. `encode(msg, precision=6)` rounds floats to that many significant digits (significant, not decimal places, so a covariance of 0.000412 survives). Set it the same way for all senders before tuning a bandwidth cap. `MessageSizeLog(precision=...)` reports sizes with the same setting.

Measured on a beacon with realistic values (positions in a 1 km area, velocities, a noisy timestamp): 298 bytes at full precision, 244 at `precision=6`, 232 at `precision=4`. These are the numbers to compare a binary format against.

## What the channel emulator owns, not the codec

Delivery time and destination travel in an envelope around the bytes, not inside the message. Corruption is treated as loss by the emulator (a real radio drops frames with a bad checksum), so the codec has no CRC. `t_sent` must come from the sender's own, possibly drifted, clock.
