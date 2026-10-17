# Seeder plan

What is left on the seeder, in the order to do it. Each task says why, what changes, how it is tested and what could go wrong. Update the status column as tasks finish; do not start a task without its plan being agreed. Config keys referred to here are in [seeder-config.md](seeder-config.md), file formats in [data-formats.md](data-formats.md).

Done so far: catalog and PostgreSQL storage, scenario generator with four presets, seed sets, compact saved runs and shared DB dump, commanded drone motion (mock), flight limits.

| # | Task | Why | Status |
|---|------|-----|--------|
| 1 | Shared header on the mock's `meas` and `beacon` messages | One message format across modules; the codec and the channel emulator need it | done |
| 2 | Clutter objects (birds, vehicles) | The tracker and friend/foe must not call them hostile; today there is only a false-alarm rate | done |
| 3 | Jamming zones | Graceful degradation under electronic warfare is the point of the task | done |
| 4 | Bandwidth limits | Link capacity makes "share compact tracks, not raw observations" matter | todo |
| 5 | Scenario sweeps | A table of results over many seeds for tuning and the final test | blocked by scoring |
| 6 | Moving ground units | Only if the mentor says ground units move | blocked by mentor |
| 7 | Terrain and line of sight | Only if the mentor confirms terrain matters; the largest piece | blocked by mentor |
| 8 | Catalog verification | Replace assumed numbers with datasheet values | needs people |
| 9 | Weather combinations, weather events, seasonal sky | Kris's `sensors/` already reads them; the seeder validator rejects them and the viewer has exclusive weather buttons | done |

## 1. Shared header on `meas` and `beacon`

**Change:** in `ui/viewer/sim.js` the two existing message types get `header` (built by `Drones.makeHeader`, already used by `drone_command`) and the agreed type names: `meas` becomes `observation`, `beacon` becomes `friendly_beacon`, with the fields in [data-formats.md](data-formats.md). `t_sent` is the sender's drifted clock. Move `makeHeader` into a small shared file so it is not tied to drones.

**Test:** the 8 baseline runs must produce the same tracks and metrics as now (only message fields change, not behaviour); a new node test checks every message type has the five header fields and a unique `msg_id`.

**Risk:** the observation shape must match what the sensors and tracker owners expect; check with them before renaming fields. Do not change the numbers the tracker consumes.

**Done:** header in `ui/viewer/messages.js`; `observation` follows the system-design draft plus `cov_fields` (the order of the covariance), `friendly_beacon` has exactly the fields `friend_foe/jsonl_io.py` reads. The mock tracker still reads its internal record (`z`, mock only). Verified: 8 baseline runs and 6 command runs hash identical, viewer DOM identical apart from the new script tag, all messages of a lossy run decode with `common/codec.py` from main and every beacon parses with `beacon_from_message`. Still to confirm with the tracker owner: the `observation` fields.

## 2. Clutter objects

**Change:** `environment.clutter` gets `birds` and `vehicles` counts (and keeps `false_alarms_per_min`). The generator makes them as objects in `scenario.json` (`clutter[]`: id, kind, path, speed, altitude, signature) with their own random stream so adding clutter does not move the hostiles. Birds: fast, erratic, small radar and thermal return, no RF, strong acoustic only up close. Vehicles: ground-level, slow, loud, hot, no RF. The truth file lists them with `kind: clutter`. The mock sensors detect them like any object using the signatures, and scoring counts a hostile track on a clutter object as a false alarm.

**Test:** unit tests for determinism and for the separate random stream (hostile paths identical with and without clutter); a run test that a clutter object produces detections; the baseline presets (no clutter) stay byte-identical.

**Risk:** signatures are assumptions, so say so in the catalog notes. Keep object counts small (a handful) so runs stay fast.

**Done:** `scenario.json` `clutter[]` has the same shape as `targets[]` (plus `type`, `role: clutter`), so `target_state` and the mock move both; built by one shared `_path_object`, paths from `_free_path`, own `clutter` random stream. Counts are 0 to 10 per type. Signatures and motion live in `CLUTTER_KINDS` in `seeder/scenario.py`, marked assumed and listed in [seeder-config.md](seeder-config.md), not in the catalog (the catalog describes our sensors and platforms, not the world). Simplified from the plan: a bird's acoustic signature is just weak (0.3), with no extra "only up close" rule. The mock counts a hostile track on clutter as `cfa` (in the summary only when the scenario has clutter) and draws clutter as grey dashed rings. No preset has clutter yet. Verified: 24 preset scenario and truth files (4 presets × 6 seeds) identical apart from the new keys; 8 baseline runs and 6 command runs hash identical; viewer DOM identical for 5 views; 6 new generator tests, 5 new mock tests (`node ui/viewer/test-clutter.js`); a generated `hard` scenario with 4 birds and 2 vehicles runs through `generate.py` and `export-run.js`, and the viewer shows them.

## 3. Jamming zones

**Change:** `degradations.network.jamming_zones` = list of `{x, y, radius_m, t_start, t_end, loss, rf_noise_mult}`. Messages sent by or to a node inside a zone while it is active use the zone's loss (the higher of the zone and the base loss). RF receivers inside a zone get their noise multiplied. Beacons are lost with the rest, which is exactly what friend/foe must survive (silence is not proof of hostility).

**Test:** a node inside a zone loses messages at the zone rate and one outside does not; zone times respected; presets without zones unchanged. Add a `jammed` preset only after the numbers are checked in the viewer.

**Risk:** the sender position is used to decide membership, so a moving drone enters and leaves a zone mid-run; test that case.

**Done:** `_check_jamming` in `seeder/scenario.py` (x, y, radius_m and loss required; t_start, t_end and rf_noise_mult optional; the generator only passes zones on). `ui/viewer/jamming.js` has the zone maths; `sim.js` takes the loss from `lossFor` in `sendMessage` (same single random draw per message, only the threshold changes) and `jammedRf` raises RF noise through `sensorAt`; the map draws active zones as red dashed circles. Zones apply in Realistic mode only. Verified: 41 seeder tests (3 new); `test-jamming.js` (7 tests: a node inside loses at the zone rate and one outside does not, start and end times, a drone flying through is jammed only while inside, RF noise, optimistic mode, empty list equals no zones); 8 baseline and 6 command run hashes identical; `scenarios.js` unchanged; a temporary preset with a zone showed correctly in the viewer. No `jammed` preset yet, as planned: add one after you have seen the numbers.

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

## 9. Weather combinations, weather events, seasonal sky

Requested by Kris (branch Krischo, commit 4336605). Format: "Weather combinations and weather events (proposed)" in [data-formats.md](data-formats.md) on that branch. Everything is backward compatible: a single weather keeps working.

**Change:**
1. **Validator** (`seeder/scenario.py`): `environment.weather` accepts `fog+wind` and `rain:0.6+wind`; `environment.weather_events[]` and `environment.sky` are checked and passed through to `scenario.json` unchanged. The checks call `sensors/weather.py` (`parse_weather`) and `sensors/daylight.py` (`sky_from_dict`) instead of copying them. The generator does not use weather for anything, so no random stream changes.
2. **Viewer** (`ui/viewer/sim.js`, `app.js`, `index.html`): the five exclusive weather buttons become toggles for fog, rain and wind, each with a strength slider. The Night button is replaced by a sky control: date picker, hour slider with sunrise and sunset marked, and a place (latitude and longitude, plus a few presets). `buildSensors` multiplies the active effects (strength moves a multiplier that share of the way to 1; overlapping effects multiply, events take the strongest strength of each effect). Night is a strength from 0 to 1 and combines with fog and rain. `weather_events` change a sensor's multiplier by time and by its position inside the zone, so the multiplier is looked up per detection, not once per run.
3. **Catalog check** (`seed_catalog.py --check`): also test the combinations, and report platforms that lose every working detection module.
4. **Catalog field** `sim.ident_range_m` per module (Kris's item a), so `sensors/` can drop its placeholder fraction of `sim.range_m`. Assumed numbers, marked as such.

**Left out:** moon and cloud cover; the `sensors/report.py` table (Kris's); changing any module's weather multipliers (that is catalog verification, task 8).

**Test:** unit tests for the validator (accepts the new forms, rejects bad strengths, unknown names, a zone without radius, a sky missing one of its four fields); a Node test that the product of effects and the strongest-strength rule match `sensors/weather.py` on a fixed table of cases, and that an event covers a detection only inside its zone and time. Single-weather runs must stay byte-identical (8 baseline hashes, 6 command hashes, 5 viewer views).

**Risks and decisions for the team:**
- **Two languages:** the weather product and the sun position exist in Python (`sensors/`) and the viewer needs them in JS. Recommended: a small JS port plus a shared table of test cases that both sides check, so they cannot drift apart. The alternative is to precompute the effects per second in the seeder and ship them in `scenario.json`; that stops the date and hour sliders working live. Your call.
- **Merge first:** this needs `sensors/weather.py` and `daylight.py`, which are on origin/Krischo only. Merge it into Orcho before starting.
- **Where is the village?** Without a default latitude and longitude the sky cannot be used by presets. Ask the mentor; until then the viewer's place presets are only examples and presets stay without `sky`.
- **Platforms with no working module:** Kris's finding (fog + wind leaves `mini4pro` and `gs_eo_acoustic` blind; fog + rain + wind at night leaves 4 of 7 platforms blind) is realistic physics, not a bug. Recommended: the check reports it as information and does not fail, and no module is made artificially robust. Giving a platform a robust module is a design decision about the platforms, not about the check.
- **`en_route` (Kris's item b):** the mapping in `docs/data-formats.md` was meant as you emit it: an accepted `goto` or `return` gives `assigned` then `en_route`, and the mock does the same. No change.

**Order:** merge Krischo, then 1, 3, 4 (small), then 2 (largest), then docs.

**Done:** Kris agreed to the plan and the four recommendations (JS port with shared cases and tolerance 1e-9, merge first, report-only catalog check). Validator: `_check_weather` in `seeder/scenario.py` calls `sensors.weather.weather_from_scenario` (repo root put on `sys.path`), so the generator only passes `weather`, `weather_events` and `sky` through. Viewer: `ui/viewer/weather.js` is the port (parse, strengths, product of effects, events, sun, `conditions_between`); `weather-ui.js` has the toggles with strengths and the sky controls; `sim.js` builds the sensors for the weather that never changes and looks the rest up per detection (`sensorAt`), including radar false alarms. Catalog: `seed_catalog.py --check` prints the combined-weather table (information only, from `sensors/report.py`); `sim.ident_range_m` added to every detection module (assumed: Kris's placeholder fractions of `range_m`: EO 0.6, thermal 0.5, RF 0.3, microphone 0.2, radar 0.2) and validated. Verified: 38 seeder tests; `test-weather.js` (all of `weather_cases.json`, plus simulation checks: an event over everything equals that weather all run, an event that starts at 60 s leaves the first minute as in clear weather, a far event changes nothing, a sky at midday equals clear and at midnight equals a fixed night); 8 baseline and 6 command run hashes identical; the 5 viewer views identical except the new controls; `scenarios.js` unchanged. Not done: the DB catalog and `db-dump.json.gz` were not refreshed for `ident_range_m` (needs the database: `python seeder/seed_catalog.py`, then `python seeder/dump.py export`); the Sensor limits table and coverage show the base weather only.

## Order and checkpoints

1, then 2 and 3 (independent, either order), then 4. After each task: tests pass, baseline presets unchanged unless the task says otherwise, docs and `data-formats.md` updated, dump re-exported if the database changed, then review before commit.
