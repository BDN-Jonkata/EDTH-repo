# Branch `Krischo`: what is new and not yet in `main`

Written for the team reviewing the branch. Two parts: 5 commits that are in the branch but not in `main`, and work in the working tree that is **not committed yet**. Numbers say which seeds they come from. Sensor and signature numbers in the mock are assumptions, not measurements.

## 1. Committed, not merged (5 commits)

| Commit | What | Measured |
|---|---|---|
| `f4b4440` | Tracker: the radar's radial speed (Doppler) joins the association gate | `challenge` ID swaps per run at the close crossing: 1.8 → 0.3 (0 % loss), 2.0 → 0.3 (70 % loss) |
| `6887f9b` | Tracker: a track that was supported in the last 5 s is kept for 6 s | hostile tracked at high loss: +0.04 to +0.10 |
| `1ef6db9` | CI workflow (Python tests, seeder tests, catalog check, viewer tests); project summaries (EN and BG) with current numbers | CI has not run on GitHub yet |
| `d438698` | README status paragraph from tuning-seed numbers, not old test-seed numbers | |
| `1519efc` | Identification from RF: two receivers' bearings are crossed into a fix, the fix goes to the one track it agrees with | Python: hostile label on 23 % of tracked hostile time with 4 % on clutter; viewer: 68 % on `medium` |

Current `challenge` numbers (Python pipeline, 10 tuning seeds, message loss 0 / 30 / 50 / 70 / 90 / 95 %): hostile tracked 0.71 / 0.69 / 0.67 / 0.64 / 0.30 / 0.07; position RMSE 11.3 / 10.8 / 12.3 / 11.7 / 14.9 / 20.2 m; ID swaps 0.30 / 0.50 / 0.50 / 0.30 / 1.10 / 0.20; friendlies flagged 0 up to 70 % loss, 0.30 and 0.20 at 90 and 95 %.

## 2. In the working tree, not committed

All of this is in the viewer's simulation (`ui/viewer/`) and the seeder. The Python pipeline is not changed by it.

### Identification
- **Radio rule made safer** (`sim.js`): only a confirmed track can be called hostile from the radio; a fix that two tracks explain about equally well belongs to neither; the radio never overrides friendly or peaceful; far from the zone and not heading for it the radio alone does not make a hostile. False hostile tracks on 6 scenarios: 12 → 5.
- **Class is held** until evidence for another class comes (hostile, peaceful, friendly, object; suspicious is shown while it lasts but not held, because it sends a drone). A radio-based hostile is let go when two receivers in reach hear nothing of it for 12 s.
- **Intent from motion, learned while the run goes on** (`intent.js`, new). A physical prior (closest point of the course to the zone, closing speed, range, turn, loiter) is corrected by what the run shows afterwards: a track that reached the defended area is a positive example, one that lived 25 s and left is a negative one. No recorded training data. Hostile from the course alone is off; peaceful from the course is on.
- **Time-to-reach rule**: not on a known plan and reaching the zone within 30 s is a threat after 4 s. An object never heard on the radio waits until 15 s from the zone.
- **Defended zone** (`zone` in the scenario, default 250 m around C2, an assumption). Drawn on the map; "declared at X m outside the zone" is the new metric `summary.declare`.
- **Cleared flight plans** (`cleared_routes`, seeder option `targets.cleared_count`): a track that keeps within 50 m of a plan for 4 s is peaceful. The estimator gets the plan, never the role.
- **New class `object`** for birds and vehicles (grey icon, legend, counters; not counted as hostile, no drone is sent at it). It comes from the radar: `snr_db` now rises with the object's radar signature, the viewer adds the range back and reads a track as small (≤ −6 dB) or large (≥ +3 dB) after 5 returns, with 3 dB of hysteresis. Tags "SMALL · BIRD?", "LARGE · VEHICLE?", "NO RADIO · BIRD/VEHICLE?".
- **"No radio" is local**: it counts only time inside the reach of two receivers.

### Crossing identity in the viewer's tracker
- **The radar's radial speed gates its record** (3 degrees of freedom: range, bearing, radial speed), the same fix as `f4b4440` in Python. `challenge`, viewer, 4 seeds, clear weather: ID swaps per run at 0 / 30 % loss 2.8 / 2.5 → 0.5 / 1.0 on tuning seeds; test seeds 1000–1003 give 1.0 / 1.3 / 0.8 / 3.3 at 0 / 30 / 70 / 90 % loss. RMSE 12.7 → 5.7 m (test seeds 5.3 to 10.9 m), friendlies flagged 0.8 → 0.0 (test seeds 0.0 to 0.3), hostile count exact in 26 → 43 % of frames (test seeds 24 to 36 %). What is left of the count error is hostiles missing (0.7 to 0.8 of 2), not extra ones.
- **Radio band**: a transmitter heard on the friendly data band (5745 MHz in the mock, an assumption) is a friendly, never a hostile; the fix of a friendly's radio no longer lands on a duplicate track and calls it hostile.

### Messages
- **Repeat of readings on bad links** (`repeatObs: 'auto'`): 1 copy on a good link, 2 or 3 on a bad one, the first copy to arrive counts. Hostile tracked, 3 scenarios: 50 % loss 0.82 → 0.85, 70 % 0.75 → 0.86, 90 % 0.47 → 0.69. Costs bandwidth. The node reads its link quality from the channel in the mock; a real node would learn it from C2's acknowledgements.

### Seeder
- **Bug fixed:** friendly loops could start closer than 100 m, the mission controller refused and the run crashed, which is what happened when the seed was changed in the viewer. Start angles are redrawn until the starts are 110 m apart (seeds that never clashed keep their scenario). Checked on 9 presets × 199 seeds: closest start 111 m.
- New preset **`mixed`** (3 hostiles with pursuit and intercept, 3 benign drones of which 2 on a known plan, 2 birds, 2 vehicles), `zone`, `cleared_count`; `docs/scenario-contents.md` lists every preset's objects (generated).

### Tests added
`test-intent.js` (7 checks), `test-held-class.js`, `test-size.js`, `test-weather-system.js`; `test-assessments.js` updated for held classes. Tool: `weather-sweep.js`.

## 3. Results on seeds not used for tuning

24 new scenarios from `mixed`, `busy` and `challenge`, 30 % message loss. Tuning seeds 11–18 and test seeds 1000–1007; nothing was tuned on the test seeds and they were run once.

| | Tuning | Test |
|---|---|---|
| Hostile → hostile | 77 % | 77 % |
| Hostiles declared at least once | 70 of 72 | 72 of 72 |
| Mean range outside the zone when declared | 31 m | 32 m |
| Benign with a plan → peaceful | 93 % | 87 % |
| Benign without a plan → hostile | 40 % | 42 % |
| Birds → object (hostile) | 59 % (19 %) | 76 % (9 %) |
| Vehicles → object (hostile) | 75 % (3 %) | 82 % (9 %) |
| Hostile tracked fraction | 0.87 | 0.90 |

The old fixed seeds gave better numbers for birds and vehicles (71–83 % object): part of the thresholds had leaned on them.

## 3b. In weather

`node ui/viewer/weather-sweep.js` runs the same scenarios under single conditions and combinations (`test-weather-system.js` is the light check that is part of the tests). 3 `mixed` scenarios (seeds 11–13) and 1 `challenge` (seed 11), 30 % message loss, one run each, so differences of a few points are noise. "Hostile" is the share of all frames of a real hostile in which a track on it is called hostile (an untracked hostile counts against it); "range" is how far outside the zone it was when first called hostile (negative: already inside).

| Weather | Tracked | Hostile | Declared | Range | Birds object / hostile | Plan peaceful | Count error | RMSE |
|---|---|---|---|---|---|---|---|---|
| clear | 0.88 | 49 % | 11/11 | −10 m | 62 % / 22 % | 93 % | 0.66 | 9.5 m |
| rain | 0.69 | 40 % | 10/11 | −6 m | 84 % / 6 % | 79 % | 0.89 | 11.8 m |
| fog | 0.76 | 43 % | 10/11 | 19 m | 71 % / 15 % | 89 % | 1.00 | 12.0 m |
| wind | 0.78 | 51 % | 11/11 | 15 m | 89 % / 5 % | 91 % | 0.47 | 7.4 m |
| night | 0.89 | 53 % | 11/11 | 22 m | 79 % / 11 % | 91 % | 0.91 | 11.9 m |
| rain + night | 0.65 | 40 % | 11/11 | −30 m | 66 % / 21 % | 83 % | 1.34 | 15.0 m |
| fog + night | 0.73 | 38 % | 10/11 | 18 m | 72 % / 16 % | 87 % | 0.89 | 12.2 m |
| fog + rain | 0.53 | 26 % | 10/11 | −41 m | 54 % / 23 % | 76 % | 1.42 | 15.8 m |
| fog + wind | 0.74 | 46 % | 9/11 | 0 m | 87 % / 8 % | 87 % | 0.45 | 10.5 m |
| rain + wind | 0.70 | 39 % | 11/11 | −35 m | 77 % / 16 % | 81 % | 1.16 | 14.1 m |
| rain + wind + night | 0.77 | 45 % | 11/11 | −36 m | 58 % / 20 % | 75 % | 2.18 | 13.9 m |
| fog + rain + wind + night | 0.63 | 33 % | 10/11 | −56 m | 67 % / 21 % | 74 % | 0.99 | 13.9 m |

What it shows: night alone costs nothing (radar, RF and microphones do not need light); rain is the hardest single condition and fog + rain the hardest pair (tracked 0.53, hostile 26 %); rain-containing conditions declare the hostile only after it is inside the zone. Every condition still declares 9 to 11 of 11 hostiles at least once, and nothing crashes.

Friendlies called hostile ("ffa") went from 1.3 per run in clear weather to 3.8 in rain + wind + night. Part of that is the scoring: a track counts as a friendly flagged when a hostile track is within 40 m of a friendly, which is what a real hostile in pursuit does. The rest was real: a track beside a friendly whose beacon was lost took the radio's or the course's verdict. Fixed by not giving a new hostile verdict to a track within 60 m of a friendly the base still knows (`besideFriend`): rain + wind + night 3.8 → 2.0, clear 1.3 → 1.0. Not zero yet; the table above was measured before that fix.

## 4. Tried and removed
Sector planning of the drones, moving ground sensors, a learned motion model (no effect on swaps), RF-started tracks (earlier for 2 of 12 hostiles, 35–40 % of fixes on nothing), faster confirmation (the gap is 0–2 s), a microphone as a second source of size (13.9 % of drone frames misread), hostile from the course alone, a single-receiver RF rule, other drone layouts and watch radii (no gain).

## 5. Open problems and decisions
1. **Detection is late.** 7 of 12 hostiles are tracked 20 s or more after they appear, declared 30–110 m outside the zone, not 200 m. No sensor in reach; layout and radius changes did not help.
2. **Benign without a plan is 42 % hostile.** On the same course, speed and radio it looks like a hostile. Only a known route tells them apart. Needs the organisers' rules.
3. **Zone radius 250 m is an assumption.** The "unknown transmitter in the zone is hostile" rule is a team decision.
4. **Held classes** keep a false hostile for good, except a radio-based one.
5. **Two trackers.** Python (README tables) and the viewer's JS are different code; intent, plans, zone, size, held classes and repeat exist only in the viewer.
6. **Message loss in the earlier session's comparisons was 0.3 %, not 30 %** (the viewer reads the loss in percent). Those relative comparisons stand; the loss numbers above (30, 50, 70, 90 %) are from runs with the right value.
7. **Tests:** after the last changes I ran `test-size`, `test-held-class`, `test-intent`, `test-emitters`, `test-clutter`, `test-assessments` and the seeder tests, not the whole viewer suite, the Python suite or `seed_catalog --check` after every step. Run all of them before merging.
8. `classifyFrame` in `sim.js` is now longer than the 50-line rule; split it before merging.

## 6. Files
Changed: `seeder/scenario.py`, `scenarios/scenarios.md`, `docs/data-formats.md`, `docs/seeder-config.md`, `ui/viewer/{sim,app,legend,missions}.js`, `ui/viewer/index.html`, `ui/viewer/scenarios.js` (generated), `ui/viewer/test-assessments.js`.
New: `ui/viewer/intent.js`, `ui/viewer/assets/track-icons/object.svg`, `ui/viewer/test-{intent,held-class,size,weather-system}.js`, `ui/viewer/weather-sweep.js`, `scenarios/mixed.json`, `docs/scenario-contents.md`, this file.

Suggested commits: (1) `Viewer: radio rule, held classes, learned intent, zone, cleared plans, declare-range metric`; (2) `Viewer: object class for birds and vehicles, read from radar size`; (3) `Viewer: repeat of readings on bad links`; (4) `Seeder: zone, cleared_count, mixed preset; friendly starts 110 m apart (a new seed no longer crashes)`.
