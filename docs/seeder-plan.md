# Seeder plan

What is left on the seeder, in the order to do it. Each task says why, what changes, how it is tested and what could go wrong. Update the status column as tasks finish; do not start a task without its plan being agreed. Config keys referred to here are in [seeder-config.md](seeder-config.md), file formats in [data-formats.md](data-formats.md).

Done so far: catalog and PostgreSQL storage, scenario generator with four presets, seed sets, compact saved runs and shared DB dump, commanded drone motion (mock), flight limits.

| # | Task | Why | Status |
|---|------|-----|--------|
| 1 | Shared header on the mock's `meas` and `beacon` messages | One message format across modules; the codec and the channel emulator need it | done |
| 2 | Clutter objects (birds, vehicles) | The tracker and friend/foe must not call them hostile; today there is only a false-alarm rate | todo |
| 3 | Jamming zones | Graceful degradation under electronic warfare is the point of the task | todo |
| 4 | Bandwidth limits | Link capacity makes "share compact tracks, not raw observations" matter | todo |
| 5 | Scenario sweeps | A table of results over many seeds for tuning and the final test | blocked by scoring |
| 6 | Moving ground units | Only if the mentor says ground units move | blocked by mentor |
| 7 | Terrain and line of sight | Only if the mentor confirms terrain matters; the largest piece | blocked by mentor |
| 8 | Catalog verification | Replace assumed numbers with datasheet values | needs people |

## 1. Shared header on `meas` and `beacon`

**Change:** in `ui/viewer/sim.js` the two existing message types get `header` (built by `Drones.makeHeader`, already used by `drone_command`) and the agreed type names: `meas` becomes `observation`, `beacon` becomes `friendly_beacon`, with the fields in [data-formats.md](data-formats.md). `t_sent` is the sender's drifted clock. Move `makeHeader` into a small shared file so it is not tied to drones.

**Test:** the 8 baseline runs must produce the same tracks and metrics as now (only message fields change, not behaviour); a new node test checks every message type has the five header fields and a unique `msg_id`.

**Risk:** the observation shape must match what the sensors and tracker owners expect; check with them before renaming fields. Do not change the numbers the tracker consumes.

**Done:** header in `ui/viewer/messages.js`; `observation` follows the system-design draft plus `cov_fields` (the order of the covariance), `friendly_beacon` has exactly the fields `friend_foe/jsonl_io.py` reads. The mock tracker still reads its internal record (`z`, mock only). Verified: 8 baseline runs and 6 command runs hash identical, viewer DOM identical apart from the new script tag, all messages of a lossy run decode with `common/codec.py` from main and every beacon parses with `beacon_from_message`. Still to confirm with the tracker owner: the `observation` fields.

## 2. Clutter objects

**Change:** `environment.clutter` gets `birds` and `vehicles` counts (and keeps `false_alarms_per_min`). The generator makes them as objects in `scenario.json` (`clutter[]`: id, kind, path, speed, altitude, signature) with their own random stream so adding clutter does not move the hostiles. Birds: fast, erratic, small radar and thermal return, no RF, strong acoustic only up close. Vehicles: ground-level, slow, loud, hot, no RF. The truth file lists them with `kind: clutter`. The mock sensors detect them like any object using the signatures, and scoring counts a hostile track on a clutter object as a false alarm.

**Test:** unit tests for determinism and for the separate random stream (hostile paths identical with and without clutter); a run test that a clutter object produces detections; the baseline presets (no clutter) stay byte-identical.

**Risk:** signatures are assumptions, so say so in the catalog notes. Keep object counts small (a handful) so runs stay fast.

## 3. Jamming zones

**Change:** `degradations.network.jamming_zones` = list of `{x, y, radius_m, t_start, t_end, loss, rf_noise_mult}`. Messages sent by or to a node inside a zone while it is active use the zone's loss (the higher of the zone and the base loss). RF receivers inside a zone get their noise multiplied. Beacons are lost with the rest, which is exactly what friend/foe must survive (silence is not proof of hostility).

**Test:** a node inside a zone loses messages at the zone rate and one outside does not; zone times respected; presets without zones unchanged. Add a `jammed` preset only after the numbers are checked in the viewer.

**Risk:** the sender position is used to decide membership, so a moving drone enters and leaves a zone mid-run; test that case.

## 4. Bandwidth limits

**Change:** `degradations.network.bandwidth_kbps` per link. Needs message sizes, so it depends on task 1 and on the codec (`MessageSizeLog` already counts bytes). The mock estimates a message's size from the codec's JSON length, sends at most the cap per second and drops or delays the rest (queue, drop oldest). Report bytes per type in the run result.

**Test:** with a low cap, delivered bytes per second never exceed it; with no cap, results are unchanged.

**Risk:** only meaningful with the real channel emulator; build it in the mock first, then give the rule to the simulation owner as a spec. Count size without the mock-only `z` and `arr`. Today, as plain JSON, an `observation` is about 430 bytes and a `friendly_beacon` about 290 (unrounded numbers); the codec's rounding will lower that.

## 5. Scenario sweeps

**Change:** `python seeder/generate.py scenarios/hard.json --sweep tuning` (or `test`) generates all seeds of a set and writes one summary file per run for scoring to read. The final test set is run once, at the end.

**Blocked by:** the scoring module. Until then it only produces the files.

## 6 and 7. Moving ground units, terrain

Do not plan in detail before the mentor answers what ground units are and whether terrain blocks sight. If yes: ground units reuse the waypoint motion of hostiles plus a platform with sensors; terrain adds a height map and a visibility test for every sensor-target pair (the hot spot for performance).

## 8. Catalog verification

Check each unverified module against its datasheet, set `verified: true` with the source, and replace the assumed numbers. Add the platforms' real speed and acceleration limits. This is reading work, not code.

## Order and checkpoints

1, then 2 and 3 (independent, either order), then 4. After each task: tests pass, baseline presets unchanged unless the task says otherwise, docs and `data-formats.md` updated, dump re-exported if the database changed, then review before commit.
