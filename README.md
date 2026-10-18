# EDTH-repo

Distributed multi-sensor fusion into a single Common Operational Picture (COP) under electronic warfare (EW).

Combine partial, noisy observations from low-cost UAS and ground sensors, fused across distributed nodes with imperfect clocks, uncertain positions and lossy communication, into one picture that gives the **number of hostile targets** with a **stable identity, position and velocity** for each, and never flags friendlies as threats.

> Status: **working simulation and tested components; challenge success remains unproven.** The JavaScript viewer and Python pipeline both run sensing, tracking, classification and scoring. Python also has optional per-node tracking and covariance-intersection fusion, link-health weighting and late-reading replay. These are distinct implementations: the simulation viewer does not run the Python pipeline, but its COP replay page (`ui/viewer/cop.html`) displays a saved run of either engine (`python -m pipeline.export_run` writes the Python one). See the [03-Rai challenge audit](docs/challenge-audit.md) for current requirement evidence, failures and priorities.

Run the tests (Python 3.11+): `python -m pip install pytest`, then `python -m pytest` from the repo root.

## Documents

| Document | Contents |
|----------|----------|
| [docs/challenge-audit.md](docs/challenge-audit.md) | Current 03-Rai requirement audit and validation; component completion is separate from operational success |
| [docs/concept.md](docs/concept.md) | Problem statement, scenario, success criteria, our approach, components, metrics |
| [docs/system-design.md](docs/system-design.md) | Architecture, module responsibilities, conventions (time, coordinates, uncertainty), message schemas, module design, repo layout, open decisions |
| [docs/seeder-config.md](docs/seeder-config.md) | Scenario config (one JSON + seed), degradation switches, presets, open questions for the mentor |
| [docs/data-formats.md](docs/data-formats.md) | The JSON the seeder produces (scenario, truth, catalog, saved runs) and how to read it; start here if you build another module |
| [docs/seeder-plan.md](docs/seeder-plan.md) | What is left on the seeder, in order, with the plan, test and risks of each task |
| [docs/team-plan.md](docs/team-plan.md) | Work split between 3 people, interfaces between them, per-phase tasks, working agreements |

## Repository layout

| Folder | Purpose |
|--------|---------|
| [docs/](docs/) | Concept and system design |
| [common/](common/) | Shared message schemas, time/frame helpers, bus interface |
| [scenarios/](scenarios/) | Scenario presets (configs) |
| [seeder/](seeder/) | Platform/sensor catalog (PostgreSQL) and the scenario generator |
| [simulation/](simulation/) | 2D world, ground truth, network channel emulator |
| [sensors/](sensors/) | Camera, acoustic, RF, radar models incl. weather effects |
| [tracker/](tracker/) | Multi-target tracker (central default; optional per-node trackers in `pipeline/nodes.py`) |
| [pipeline/](pipeline/) | The whole chain on one scenario: sensors, lossy network, tracker, friend/foe, scoring |
| [friend_foe/](friend_foe/) | Friendly beacon matching and drone behaviour pattern |
| [drone_behavior/](drone_behavior/drone_behavior.md) | Automatic observed-motion evidence, policy configuration and reference tests |
| [fusion/](fusion/) | Cross-node track merge, global IDs, COP |
| [predictor/](predictor/) | Optional short-horizon prediction |
| [scoring/](scoring/) | Metrics harness |
| [ui/](ui/) | Operator view and simulation viewer (first version in `ui/viewer`, run with `python serve.py` there) |

## Architecture in one paragraph

Modules run in one codebase and exchange timestamped messages through a simulated channel. A seeder builds scenarios; sensor models emit noisy native readings, and the channel applies configured communication impairments. The Python pipeline and JavaScript viewer each use a central tracker by default. Python's optional distributed mode runs local trackers and shares tracks and bearing reports with one covariance-intersection merger; merger failover and peer-link topology are not implemented. Optional identity predictors exist but have not demonstrated a reduction in crossing swaps. Scoring compares estimates with ground truth. See [system design](docs/system-design.md) for the proposed architecture and the [challenge audit](docs/challenge-audit.md) for implementation limits.

---

## Project plan

Phased, starting from the optimistic case. Status legend: ⬜ not started · 🟨 in progress · ✅ done.

**A completed component tick means implemented and tested, not that the 03-Rai success criteria are met.** Accurate counts, stable crossing identities and zero friendly threats must be demonstrated together on the challenge scenario and across message-loss levels; see the [current audit](docs/challenge-audit.md).

### Phase 0 - Foundation

| Status | Task |
|--------|------|
| ✅ | Folder structure and docs (concept, system design) |
| ✅ | Decide fusion topology and module boundaries: hybrid. Each node runs its own tracker and shares compact `local_track` messages (and short `bearing_report`s) over the lossy channel to one merger that merges with covariance intersection and keeps global IDs (`fusion/`, `pipeline/nodes.py`); the central tracker stays the default and the reference. See [fusion.md](fusion/fusion.md) |
| 🟨 | Define shared message schema (observation, track, uncertainty, timestamp, source ID): header, beacon, `local_track` (with the optional `friend_id`), `bearing_report`, `c2_ack`, `node_status`, investigation and drone-command messages drafted in `docs/data-formats.md`; observation and final COP track not frozen |
| 🟨 | Choose stack, simulation framework and message bus: Python, JSON Lines and PostgreSQL chosen; bus and the real simulation framework still open (a JavaScript mock simulation runs in the viewer) |
| ✅ | Define scoring metrics and ground-truth format: `truth.json` format, metrics and the scoring module defined and done |
| 🟨 | Set up environment, tooling, CI: Python environment, pytest and unittest suites, node tests, `.env` and PostgreSQL done; CI runs the Python and viewer tests on every push and pull request (`.github/workflows/tests.yml`, the commands were run locally, the workflow itself has not run on GitHub yet); no formatter yet |

### Phase 1 - Optimistic pipeline (clean data)

| Status | Task |
|--------|------|
| ✅ | Seeder: sensor and platform catalog, PostgreSQL storage, scenario generator (friendly patrols, ground sensors, hostile and non-allied benign paths, planned close crossing, eight presets including `outage`, tuning and test seeds) done; also clutter objects (birds, vehicles), weather combinations, weather events and a seasonal sky, jamming zones and bandwidth limits in the config, and scenario sweeps (`python seeder/generate.py scenarios/hard.json --sweep tuning`, one folder per seed); a worksheet for verifying the catalog numbers (`python seeder/unverified.py`); terrain and moving ground units wait for the mentor and are not part of this row |
| ✅ | Mock simulation: the viewer runs a JavaScript simulation (2D map with terrain/height display, crossing, commanded drone motion, clutter objects, per-detection weather with a sky control, jamming zones, per-node link bandwidth caps; the Sensor limits table and coverage follow the weather at the sensor) |
| ✅ | Simulation pipeline in Python: `pipeline/` runs sensors, the channel emulator, tracker, friend/foe and scoring on a seeder scenario. The channel now also applies jamming zones, per-node link caps and node dropout, ported from the mock (`common/jamming.py`, `common/linkcap.py`) with shared cases that both implementations must answer the same (`python -m common.golden`, `node ui/viewer/test-channel-port.js`). Sensor faults (`dropout`, `link_outage`, `delay_burst`) are applied too. Store-and-forward is there too (`--storefwd`). Not in Python yet: RF noise inside a zone; the viewer's mock has it. Neither models peer-link topology or merger failover |
| ✅ | Network channel (`common/channel.py`): loss (independent or bursty, per sender), delay, jamming zones, link caps, node dropout and sensor faults. Its `Clock` helper supplies beacon offset/drift, and readings carry the node's clock too with `--clocks`; otherwise they use ideal timestamps. `Channel.send_to` carries C2's acks over a node's own link for store-and-forward. Topology is not modelled |
| ✅ | Sensor observation models (`sensors/observe.py`, `native.py`, `beacons.py`): range window, field of view, detection probability, signatures, weather per detection, native fields with honest noise; the viewer's mock simulation has its own JavaScript version |
| ✅ | Baseline tracker (`tracker/`): central Kalman tracker on native readings, gated association, radar or two-bearing start, support rules, friendly beacon tracks; tested. The drones' own positions are smoothed from their beacons and their uncertainty goes into the sensor noise; sensor readings of a drone with fresh beacons are absorbed, not applied. Weak spot: a hostile is tracked about 71 % of the time at 0 % message loss on `challenge` (limited by what the sensors see), see [tracker.md](tracker/tracker.md) |
| ✅ | Friend/Foe estimator: beacon matching, delivery-rate-weighted silence, `peaceful` class and behaviour hook (`threat_llr`), tested on synthetic data and seeder scenarios through a test adapter (`friend_foe/`) |
| ✅ | Friend/foe estimator fed from the real tracker and delivered beacons (`pipeline/`); the test adapter remains for quick experiments |
| ✅ | Scoring of one run (`scoring/`): optimal matching to `truth.json`, count error, position/velocity/heading error, OSPA, ID swaps, friendly and clutter false alarms; tested |
| ✅ | Message-loss sweep for the whole pipeline (`python -m pipeline.sweep`, results in [tracker.md](tracker/tracker.md#results)); every cell is printed with its standard error, and `--paired investigate|identity|distributed|cueing|trust` compares with and without a feature on the same seeds (other flags: `--behaviour`, `--cue`, `--distributed`, `--trust`, `--swaps`) |
| ✅ | Reader for the viewer's result JSON in `scoring/` (`python -m scoring.run --viewer run.json`, `scoring/viewer_run.py`): the truth comes from the run's own frames; the count error agrees with the mock's per-frame record |

**Exit criteria:** correct hostile count, no ID swaps through the crossing, zero friendlies flagged, on clean data.

**Where it stands (`challenge` preset, 10 tuning seeds, 0 % message loss; the reserved test seeds have not been run):** the exit criteria are **partly met**. A hostile is tracked 71 % of the time (measured again on 6 tuning seeds: 16 % of the time only an RF receiver hears it, 9 % one node's camera or microphone bearing, about 1 % nothing, see [tracker.md](tracker/tracker.md#where-hostile-time-and-false-tracks-go-coverage-diagnosis-challenge-tuning-seeds-0--loss)), the count is off by about 0.6 hostiles, IDs swap 0.3 times per run (it was 1.8; the crossing is now solved with the radar's radial speed, see [tracker.md](tracker/tracker.md)), and no friendly is flagged up to 70 % loss and 0.3 of 5 at 90 % (it was 4 to 5). Every track that is not a confirmed friendly still counts as hostile; nothing is called `hostile` from evidence. The numbers with the whole degradation curve are in [tracker.md](tracker/tracker.md#support-window-5-s-and-6-s-was-3-s-and-4-s) and in [docs/project-summary.md](docs/project-summary.md).

### Phase 2 - Distributed fusion and behaviour

| Status | Task |
|--------|------|
| ✅ | Per-node local trackers sharing compact tracks: `python -m pipeline.sweep --distributed` runs a tracker per node on its own readings and sends `local_track` messages through the lossy channel (`pipeline/nodes.py`). Not the default |
| ✅ | Track merge with covariance intersection and global IDs (`fusion/`): tested. Nodes forward their bearings in compact reports to a bearing hub at the merger. Against the central tracker (5 tuning seeds, 0 % loss) hostiles are tracked 7 points less, with fewer ghost tracks (-0.29 per step) and the same position error; at 50 % loss 4 points less and more ID swaps; see [fusion.md](fusion/fusion.md) |
| ✅ | Drone Behaviour module (`drone_behavior/`, Emkata): automatic five-class assessment from observed history, separate verified identity, uncertainty gates, safe transit/orbit and responsive pursuit with intercept risk. No protected-zone rule; GUI identity/risk percentages, Python/JS parity and mixed-traffic tests. Also runs on the Python pipeline's tracks; see [pipeline.md](pipeline/pipeline.md) for integration and tracker limitations |
| ✅ | Weather model (`sensors/`): several anomalies at once, anomalies that start, end and cover a zone, seasonal sun for day and night, per-module quality and sensor hierarchy from the catalog's `weather_effects`, shared golden cases for the JS port; tested |
| ✅ | Data loss and trust, phase 1 (seeder task 10, [plan](docs/seeder-plan.md#10-data-loss-faults-acks-store-and-forward-link-health-and-trust)): sensor faults (`dropout`, `link_outage`, `delay_burst`), store-and-forward (nodes keep unacknowledged messages and resend after a 1 Hz `c2_ack`), per-node link health (ok, degraded, offline, presumed dead) and a Node health table in the viewer, preset `outage`, in the mock simulation. The Python channel applies the faults too. Late data in the viewer: delayed and resent readings are kept and corrected into the history, the timeline shows each burst, a node silent for 30 s or more is `isolated` and what it saw can be opened (the live tracker still ignores late readings) |
| ✅ | Data loss and trust, phase 2, the health module (`health/`, [health.md](health/health.md)): a Bayesian layer (two-state link) and a frequentist layer (Wilson interval, CUSUM) over `seq` gaps and silence, per-message trust, readings weighted by trust, the friend/foe silence discounted per sender (`--trust`), the JS port `ui/viewer/health.js` checked against shared cases (`node ui/viewer/test-health.js`), and the link model fitted to the Python channel. On the `outage` preset: friendlies flagged 1.62 to 0.24 of 5, false tracks -0.72, ID swaps -1.5, at a cost of 5 points of hostiles tracked (late readings are dropped); with no faults it costs about 1 point. At 70 to 95 % loss (`challenge` preset, 6 tuning seeds) it does **not** stop friendlies being flagged: 4.0 of 5 at 90 % and 5.0 of 5 at 95 % without it, no change with it (the links are degraded, not silent, so the silence rule does not apply). The two layers are not told apart by any run, and the viewer's simulation does not use `health.js` yet |
| ⬜ | Data loss and trust, phase 3: a drone that moves to regain its link (for Emkata), integrity faults (stuck, bias, spike, replay), learned trust calibration; only if phase 2 pays off |
| ✅ | Weather applied to simulated observations: the Python observation models and the viewer's mock simulation both look up sensor quality per detection from the weather at the sensor and at the target (combinations, events and sky are accepted by the seeder and the viewer); standoff uses the catalog's `sim.ident_range_m` |
| ✅ | Suspicious class, investigation trigger and weather-based standoff per catalog module; reads drone acks through `DroneStatusMapper`; tested |
| ✅ | Trigger connected to the real tracker in Python: `python -m pipeline.sweep --investigate` sends a stand-in drone (`pipeline/fleet.py`, `dispatch.py`) at suspicious tracks and scores against the trajectories flown. Result (measured before the latest tracker fixes, so treat it as approximate): hostile tracked a few points more at low loss, with more false tracks; the dispatch rules and the beacon-track fix since then are not yet re-measured with `--paired investigate`, see [pipeline.md](pipeline/pipeline.md) |
| ✅ | Cueing (`pipeline/cueing.py`, `--cue`): a new non-friend track, or repeated bearings no track explains, are handed at once to the closest free drone (the one that saw it included) instead of waiting for a `suspicious` classification. Scored with a new identification-coverage metric (`scoring/identification.py`, a drone within `ident_range_m` of a hostile): on 15 tuning seeds the first drone is in range 4 to 6 s sooner (about 2 standard errors, from about 28 s), the share of time in range does not change. **It does raise the false tracks**: on 10 tuning seeds at 0 % loss false tracks +0.42 (the baseline is 0.45), OSPA +5.7 m, ID swaps +1.6, count bias +0.5 (re-measured by the project audit; an earlier statement here that the tracking metrics do not change was wrong). A radar fix beside a friendly's track with the friendly's radial speed now starts no track (`friend_spawn_clearance_m`, default on): with cueing on, false tracks -0.30±0.08 and count error -0.23±0.06 at 0 % loss on fresh test seeds 1040-1059, the identification gain unchanged. Off by default; see [pipeline.md](pipeline/pipeline.md) |
| ✅ | Behaviour module on the Python pipeline's tracks, merged with the hand-off (`pipeline/behaviour.py`, `--behaviour safe|raw`): raw, it cost 28 points of hostiles counted because steady hostile flights read as safe transit and the Python hostiles never pursue; the safe setting (motion alone never makes a track peaceful) leaves the baseline unchanged, so the merge adds nothing over the hand-off. Its value needs the viewer's pursuing actors; also made its encounter code about 15 % faster with identical outputs. See [pipeline.md](pipeline/pipeline.md) |
| ✅ | Sensor faults in the Python channel (`common/channel.py`, Orlin's `sensor_faults[]` and `dropout[]`: dropout, link outage, delay burst). Measured on the `outage` preset: about 1.75 of the 2 drones hit by a fault are flagged as threats (their identity fades when beacons stop), and the distributed mode loses 10 points of hostiles; since then the friendly beacon track is kept for 60 s and called friendly while the tracker keeps it (see [tracker.md](tracker/tracker.md)), which removes the flagged friendlies, and store-and-forward is modelled (`--storefwd`). See [pipeline.md](pipeline/pipeline.md) |
| ✅ | ID-swap log (`scoring/swaps.py`, `--swaps`): swaps are mostly duplicate tracks on one hostile (55 %) and two hostiles trading tracks (31 %), not re-acquisitions (9 %). Merging duplicate tracks in the tracker (default on) cut false tracks by 0.31±0.05 and OSPA by 4.4 m on 30 tuning seeds; ID swaps did not change. Later, on the `challenge` preset, nearly all swaps turned out to be the crossing itself and are fixed by using the radar's radial speed in the association (swaps 1.8 to 0.3 per run, see [tracker.md](tracker/tracker.md)). See [pipeline.md](pipeline/pipeline.md) |
| ✅ | Closest-drone investigation of suspicious tracks in the viewer's mock simulation (Emkata, `ui/viewer/investigations.js`): closest drone with a feasible sensor, standoff from `ident_range_m` and weather, commanded motion with ack and retry, release on a final class, cooldown |

### Phase 3 - Prediction

| Status | Task |
|--------|------|
| ✅ | Predictor: a constant-velocity identity keeper (`predictor/identity.py`) and a learned motion model for its gate (`predictor/motion.py`, trained on the tracker's own tracks by `predictor.train`, no truth), built and tested, off by default (`--keep-identity`, `--keep-identity learned`). **Measured on 5 tuning seeds: neither changes ID swaps** (0.00 at 0 % loss, -0.20±0.20 at 50 %), so this is done as a tested option, not as an improvement; see [predictor.md](predictor/predictor.md) |
| 🟨 | **Required: stable identity and count through the close-range crossing.** Improve and validate tracker/fusion association on the challenge scenario; prediction is one possible technique. The later swap log attributes 20 of 65 swaps to hostile crossings (`pipeline/pipeline.md`, 20 tuning seeds), so the earlier small-sample rationale for deferring this work is insufficient. A tested predictor option does not satisfy this criterion. **Fixed in the tracker:** the association now counts a radar return's radial speed (Doppler), so two hostiles that pass within 10 m are not mixed up. On the `challenge` preset (10 tuning seeds) ID swaps fell from 1.80 to 0.30 at 0 % loss, from 1.30 to 0.50 at 30 % and from 2.00 to 0.30 at 70 %, and every swap within 4 s of the crossing is gone; on `medium` from 2.6 to 1.1. See [tracker.md](tracker/tracker.md). Not yet checked on the test seeds |

### Phase 4 - Realism

| Status | Task |
|--------|------|
| 🟨 | Noise and bias on sensors: honest per-field noise, scaled by weather, is in the observation models; bias is not modelled |
| ✅ | Clock drift and time-sync handling: node clocks (offset, drift) stamp beacons and, with `--clocks`, readings; `tracker/timesync.py` (`--timesync`) estimates each node's clock from arrival times, within 3 ms on `hard`. Measured: no effect on the default tracker (it applies readings at their arrival time, so clock error and its correction change nothing at 100 to 200 ms), see [tracker.md](tracker/tracker.md#readings-applied-at-the-time-they-were-taken---oosm-age-and-time-sync) |
| 🟨 | Position uncertainty (GNSS-denied): pose error is added to beacons and the tracker takes node poses from them; the viewer's mock now applies it to every reading too (`gnss_denied` preset, `ui/viewer/test-pose.js`). 6 seeds: position error 6.9 to 25.5 m, ID swaps 0.2 to 7.5 per run; clock error alone barely matters (swaps 0.8). The viewer has a navigation estimator (`ui/viewer/navigation.js`, `test-navigation.js`): each node learns its own pose error from friendlies with fresh beacons and corrects its readings; same 6 seeds: position error 22.4 to 8.0 m, ID swaps 8.8 to 3.2 (no pose error: 7.1 m, 0.8). Beacons are assumed unbiased, so this is an upper bound. The Python pipeline does not apply pose error or estimate it |
| 🟨 | Missing data, delay, out-of-order messages: loss, delay and delay bursts are in the channel; the tracker has an optional replay of late readings at the time they were taken (`--oosm`, `tracker/oosm.py`): it removes the ghost tracks late readings start, but did not win back the hostiles that `--trust` loses; `--oosm --oosm-age 0.2` also replays fresh readings at the time they were taken (every reading arrives 50 to 400 ms late on `hard`): false tracks -0.3 and ID swaps -1 to -2.6 per run, hostiles and position error unchanged; store-and-forward is in the Python pipeline (`--storefwd`, `pipeline/storefwd.py`, rules checked against the viewer's with shared cases): it works, but an outage's backlog is mostly beacons and holds little a track can use, so tracking does not improve (hostiles 0.00±0.01 with `--oosm`); the viewer's live tracker still ignores late readings |
| ✅ | Message-loss sweep for the friend/foe estimator, with weather and clutter (`python -m friend_foe.sweep`, results in `friend_foe/friend_foe.md`) |
| ✅ | Message-loss sweep for the whole pipeline (`python -m pipeline.sweep`, see Phase 1) |

### Phase 5 - Evaluation and delivery

| Status | Task |
|--------|------|
| 🟨 | Run full scenario sweeps and collect metrics: the seeder generates every seed of a set (`python seeder/generate.py scenarios/hard.json --sweep tuning`); collecting metrics over them is the next step |
| ⬜ | Compare centralized / decentralized / hybrid if time allows |
| 🟨 | Operator view / COP visualisation: the JavaScript simulation has a map, track list, uncertainty, headings, assessments and playback. Python can read and score exported viewer JSON (`scoring/viewer_run.py`); the Python pipeline's COP can be exported (`python -m pipeline.export_run`) and replayed on `ui/viewer/cop.html` (map, tracks, counts, playback; the exported run has no sensors, missions or node health), but it is a replay of a finished run, not a live feed, and the main simulation viewer still runs only the JavaScript engine |
| ⬜ | Demo, write-up, final presentation |

---

## Risks

| Risk | Mitigation |
|------|------------|
| Identity swaps at the crossing | Classical association baseline first; prediction as an add-on; test the crossing first |
| Central design breaks under link loss | Hybrid topology and channel emulator from Phase 1 |
| Friendlies flagged as hostile | Friendly beacon matching + behaviour pattern; friendly false alarms scored as their own metric |
| Scope too large | Optimistic case first; each phase has its own exit criteria |
| Integration overhead | Modules in one codebase; fix message schema early (Phase 0) |

## Team and ownership

Detailed split and per-phase tasks: [docs/team-plan.md](docs/team-plan.md).

| Person | Area | Name |
|--------|------|------|
| A | Platform and world: `common`, `scenarios`, `seeder`, `simulation` (incl. channel emulator), the viewer's mock simulation | Orlin |
| Drone behaviour | Drone selection and flight, the behaviour module that feeds `threat_llr` | Emkata |
| C | Sensing, classification, evaluation: `sensors`, `friend_foe`, `scoring`, `pipeline`, `ui` | Kristiyan |
| B | Tracking and fusion: `tracker`, `fusion`, `predictor` | **nobody: the team is three people.** The baseline tracker and the pipeline were built by C. Per-node trackers, fusion and the predictor are unowned |

## Decisions log

| Date | Decision |
|------|----------|
| 2026-10-16 | Start with the most optimistic case; add realism in later phases |
| 2026-10-16 | Initial layout: Seeder, Simulation, Drone Behaviour, Meteorologic, Estimator, Degradation/time-sync (later) |
| 2026-10-16 | Revised: classical tracker is the core and AI only does prediction; hybrid fusion proposed; channel emulator in the simulation from the start; modules in one codebase instead of separate microservices; weather folded into sensor models; friendlies identified by broadcast first and behaviour second; metrics defined up front |
| 2026-10-16 | Repo split into per-module folders; concept and system design moved to separate docs |
| 2026-10-16 | Work split into 3 roles (A platform/world, B tracking/fusion, C sensing/evaluation) with agreed interfaces in `common/` |
| 2026-10-17 | Seeder catalog: 5 real UAS models + 2 ground sensors with different sensor loadouts and per-weather effects; stored in PostgreSQL, simulations saved as plain JSONB; seeder in Python |
| 2026-10-17 | Adopted team notes: scenarios are one JSON config + seed with a separate ground-truth file and separate tuning/test seeds; per-degradation switches; presets; radar resolution cell; sensor set switchable per scenario; catalog numbers moved to the more conservative values |
| 2026-10-17 | Viewer runs the seed with a platform chosen per node from the catalog; weather now includes night; map fills its panel |
| 2026-10-17 | Sensor limits enforced (range window, field of view, pointing, falling detection probability, rate, latency); sensors report native data only (cameras bearing+elevation, no range) and the tracker consumes it with EKF updates |
| 2026-10-17 | Scenario generator in the seeder: one config + seed gives a scenario and a separate ground-truth file; four presets (easy, medium, hard, challenge); tuning and test seed sets; viewer runs generated scenarios through serve.py |
| 2026-10-18 | Fusion and predictor built by C (they have no owner). Fusion: a tracker per node, `local_track` messages over the lossy channel, covariance-intersection merge with global IDs; kept optional (`--distributed`) because hostiles are tracked 16 points less than by the central tracker, though with fewer ghost tracks and a better position. Predictor: constant-velocity identity keeper, no measurable gain, off by default |
| 2026-10-17 | Tracks get a `suspicious` class. Suspicious tracks are investigated by sending the closest suitable drone. The drone-behaviour owner picks and flies the drone; the weather/estimator owner provides the trigger and the weather-based standoff distance (`required_standoff`). Messages `InvestigationRequest` and `InvestigationStatus` added to the draft schemas |
| 2026-10-17 | First standalone code: `sensors/weather.py` and `sensors/quality.py`, `friend_foe/estimator.py` and `friend_foe/investigation.py`, `common/codec.py` (`encode`/`decode` plus message size log). Placeholder numbers throughout, to be tuned |
| 2026-10-17 | Weather standoff now built on the seeder catalog (`sim.range_m`, `sim.min_range_m`, `weather_effects`) instead of a separate table; the request lists a standoff per catalog module (`standoff_by_module`) so the drone-behaviour side picks the modules of the drone it chooses. The one missing number, how much of a module's range is good enough to identify, is a placeholder (`IDENT_FRACTION`) until the catalog gets a field for it. Track and investigation message formats added to `docs/data-formats.md` |
| 2026-10-17 | Agreed with the seeder/simulation owner: standard header `msg_id`, `source_id`, `t_sent`, `seq`, `schema_version` plus a top-level `type`; `seq` starts at 1 and counts every message a node sends (`Sequencer`); optional float rounding at encode (`precision`) so message sizes are realistic; corruption is treated as loss by the channel emulator, no CRC; delivery time and destination live in an envelope around the bytes |
| 2026-10-17 | Drone commands go over the same lossy channel as everything else with ack and retry (every 1.5 s, at most 5 tries, assumed); `goto` and `hold` can set a heading or face a target so a forward camera points at the object; flight limits per UAS are in the catalog and marked assumed; `drone_state` doubles as `investigation_status` (mapping in `docs/data-formats.md`) |
| 2026-10-17 | Friend/foe estimator weighs silence by the measured beacon delivery rate, and decays per second instead of per update. A loss and weather sweep (`friend_foe/sweep.py`, `evaluate.py`) on seeder-generated scenarios with bursty loss, delay, clock offset and pose error showed it holds up to about 70 % beacon loss and degrades at 90 %, with a hostile never called friendly; a silent intruder is flagged later as loss rises (4 s at 0 %, about 10 s at 70 %). Tuned on the tuning seeds, reported on the test seeds |
| 2026-10-18 | Combined meteorological anomalies: weather can be several anomalies at once (`fog+wind`), each with a strength (`rain:0.6`), and anomalies can start, end and cover a zone (`weather_events`); effects multiply, a worst-case assumption. The catalog check only tests single weathers; in combination platforms lose every working detection module (fog+wind leaves `mini4pro` and `gs_eo_acoustic` with none, fog+rain+wind at night leaves 4 of 7 platforms), see `python -m sensors.report`. The scenario format is a proposal; the seeder and viewer accept one weather only until the seeder owner agrees a plan |
| 2026-10-18 | Day and night follow the season: darkness comes from the sun's height above the horizon, computed from `environment.sky` = date, clock time, latitude and longitude (`sensors/daylight.py`), not from fixed hours, because the length of the day depends on the season and the latitude. The night effect gets a strength from 0 to 1 through twilight. The viewer shows night only as one of five exclusive weather buttons and the seeder's `time_of_day` is not read by it; a day/night switch or hour slider in the viewer would need the date and place too (proposed to the seeder owner) |
| 2026-10-18 | Estimator gets the `peaceful` class and a second evidence axis. Beacon evidence (friendly or not) and behaviour evidence (hostile-like or peaceful-like, `threat_llr` hook for the drone-behaviour module) are kept apart; hostile and peaceful both need positive behaviour evidence, silence alone only gives suspicious; a beacon match stays friendly whatever the behaviour looks like. The hook changed from `behaviour_llr` (beacon scale) to `threat_llr` (own scale, positive = hostile-like). Measured on clutter: with no behaviour module, 54 % of investigation requests go to birds and vehicles with 2+2 clutter objects and 74 % with 5+5, so the behaviour module is what saves the drones (`friend_foe/friend_foe.md`) |
| 2026-10-18 | The team is three people (Orlin: platform and world; Emkata: drone behaviour; Kristian: sensing, classification, evaluation), so role B had no owner. Built the missing chain in Python without waiting: a shared channel with loss, delay and clocks (`common/channel.py`), sensor observation models and a beacon source (`sensors/`), a central baseline tracker (`tracker/`), the pipeline that connects them to the estimator and to scoring (`pipeline/`), and a scoring module (`scoring/`). First end-to-end numbers on the test seeds: a hostile is tracked 57 % of the time at 0 % message loss and 23 % at 90 %, no friendly is flagged up to 50 % loss (`tracker/tracker.md`) |
| 2026-10-18 | Closed the investigation loop in the Python pipeline with a stand-in fleet and dispatcher (`pipeline/fleet.py`, `dispatch.py`). Scoring now takes friendly trajectories recorded during the run (`scoring.truth.with_recorded_samples`), because `truth.json` holds only the scripted patrol. A reviewed finding on the behaviour module's evaluation: pre-registering friendly ids as verified made friendlies look confirmed at t = 0 because the test adapter names tracks with the true ids; with a real tracker it has no effect, and beacons-only results are the honest ones |
| 2026-10-18 | Tracker fixes on our side after a review of the results: a drone's own position is smoothed from its beacons and its uncertainty widens the noise of its sensors' readings (the biggest source of ghost tracks and ID swaps); sensor readings of a drone with fresh beacons are only absorbed, not applied, so a duplicate "intruder" track no longer starts on a friendly; dispatch only sends a drone at an old, recently updated, well localised, moving track; the pipeline passes each track's freshness to the behaviour module. Test seeds, 0 % loss: false tracks 1.28 to 0.75, ID swaps 5.6 to 3.9, count error 1.59 to 1.31, hostile tracked 57 to 58 % (the tracked share is limited by sensor coverage). Sweeps print standard errors. Not yet re-measured: the investigation comparison after these fixes |
| 2026-10-17 | JSON (JSON Lines) for messages while building the pipeline. `encode`/`decode` pair at the channel boundary so a compact binary format (Protobuf/CBOR) can replace it later without touching modules |
| 2026-10-17 | Shared message header on the mock's messages (`observation`, `friendly_beacon`, drone commands and states), one `messages.js`, matching `common/codec.py`; the mock tracker still reads an internal record that is not part of the format |
| 2026-10-17 | Clutter objects (birds, vehicles): real objects the sensors see that are not threats, generated from their own random stream so hostile paths do not move; a hostile track on one counts as a clutter false alarm (`cfa`) in the mock. Signatures are assumptions |
| 2026-10-17 | Track class `peaceful` added: not identified, probably not an enemy, the mirror of `suspicious`. Needs positive behaviour evidence, never silence alone; the estimator has to produce it (not built yet) |
| 2026-10-17 | Weather combinations, events and sky supported by the seeder validator and the viewer: JS port (`ui/viewer/weather.js`) checked against the shared cases generated from the Python reference (relative tolerance 1e-9); sensor quality is looked up per detection from the weather at the sensor and at the target; the combined-weather table is information only in the catalog check; `sim.ident_range_m` added to the catalog (assumed) |
| 2026-10-17 | Jamming zones (`degradations.network.jamming_zones`): messages sent by or to a node inside an active zone use the higher loss, RF receivers there get more noise; the sender's true position and the true time decide; Realistic mode only. Beacons are lost too, which friend/foe must survive |
| 2026-10-18 | Bandwidth limits (`degradations.network.bandwidth_kbps`): one cap per node link to C2; a message occupies the link for its size divided by the rate, in order, and when more than 2 s of data wait the oldest are dropped; loss and jamming are decided when a message leaves the link, so lost messages still used airtime; message size is the JSON length without the mock-only fields; Realistic mode only. The 2 s queue is an assumption. The channel emulator should copy the rule (spec in `docs/data-formats.md`) |
| 2026-10-18 | Scenario sweeps in the seeder: `generate.py --sweep tuning` or `test` writes one folder per seed (`scenario.json`, `truth.json`, `run.json`) and an `index.json`; benign drones are counted apart from hostiles; the test set is run once, at the end. The layout is a proposal until scoring confirms it |
| 2026-10-18 | Two new presets, `dusk` (a sunset across the run, a fog patch, clutter) and `jammed` (two jamming zones, a 32 kbit/s cap); the older presets are unchanged. Their numbers are assumptions chosen to show the effects |
| 2026-10-18 | The viewer's Sensor limits table and coverage wedges now use each sensor's range in the weather at its own position and the time on screen, so fog patches and dusk show up; `seeder/unverified.py` prints a worksheet of the unverified catalog numbers (9 of 12 modules, all 7 platforms) for task 8 |
| 2026-10-19 | Data loss, phase 1 (task 10): `degradations.sensor_faults` and `store_forward`; nodes keep what C2 has not acknowledged and resend it, C2 drops duplicates and keeps late messages out of the live picture; per-node health with assumed thresholds (offline 4 s, presumed dead 15 s, degraded at 30 % loss). A dead node and a jammed one look the same from C2, hence "presumed". Mock only; off unless the scenario asks, old presets unchanged |
| 2026-10-19 | Late data in the viewer: every sensor reading is logged with the time it was taken and when C2 got it; readings that arrive more than 3 s late or never are listed in the result and corrected into the recorded history (retrodiction on the track states, capped at 60 m, assumed); a timeline bar per burst, a "Late data loaded" switch, and a new `isolated` state for a node silent 30 s or more that is alive; what it saw can be opened on the map. The live tracker still ignores late readings. The `outage` preset's F2 cut is now 20 to 65 s |
| 2026-10-19 | Python channel gets jamming zones, link caps and node dropout, ported from the mock with shared golden cases; the `hard` preset's dropout now silences that node in the Python pipeline too (earlier Python results ignored it). The scoring module can read a run exported from the viewer |
