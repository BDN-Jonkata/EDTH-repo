# Hostile from evidence (task 2): what was found and done

Owner: Krischo. Replaces the first draft of this plan, which proposed a new RF-emission hook and an `evidence` field on `local_track`. Both were dropped.

## What changed from the draft

- `pipeline/identify.py` already labelled a non-friend track `hostile` when two RF receivers keep hearing it, and it is on by default. The held-out run of the `challenge` test seeds 1000-1019 already used it, so its 0.17 strict hostile recall was that rule's recall. A second emission mechanism would have duplicated it.
- The `threat_llr` hook cannot give hostile evidence on `challenge`: the behaviour module only produces it from pursuit or intercept of an ally, and these hostiles only cross (steady flight scores as peaceful transit). The task text asked to use it; it is not the right channel here.
- No data format changed. `Measurement` (an internal tracker type, not a message) got an optional `freq_mhz`; the observation message already carried `center_freq_mhz` (`bearing_rssi` in `data-formats.md`).

## The cause of the low recall

Two RF receivers exist in the scenario: ground sensor GS2 (about 1000 bearings per run) and drone F3 (100 to 400). A hostile was labelled only from a fix of both within 0.3 s. Five friendlies are always tracked and the bearing noise is 12 degrees, so most single bearings also gate to a friendly and were useless.

## What was done

`IdentifyConfig.single_receiver` (on by default): a bearing counts for a track when it is off the friendlies' band and exactly one non-friend track can explain it; ten in 6 s make the track `hostile`. Details, numbers and limits are in [pipeline.md](../pipeline/pipeline.md#identifying-a-hostile-from-what-the-sensors-hear-pipelineidentifypy---no-identify). Tests are in `pipeline/test_identify.py`; the full Python suite passes (464 passed, 1 skipped).

## Result

Strict hostile detected on `challenge`, 0 % loss: 0.17 to 0.24 (tuning seeds 1-8), 0.16 to 0.20 (fresh test seeds 1020-1039, run once). No friendly or clutter object gets flagged by the change. At 90 % loss it is 0.00 either way. **The strict hostile count is still far from correct; this task did not meet the challenge.**

## Still open

- A hostile on the friendlies' band, or one that does not transmit, is not found this way (assumption stated in the code and docs).
- Raising recall needs better bearings, a third RF receiver or better placement of F3 (Orlin's 3a), not a lower threshold: a threshold of 4 flagged friendlies at 90 % loss.
- The team still has to agree that an unknown transmitter in the defended area is a hostile (also noted in `pipeline.md`).
- The viewer's JavaScript has its own emitter rule (`noteEmitters` in `ui/viewer/sim.js`) and was not changed.
