"""Learn the motion model from the tracker's own confirmed tracks on the tuning seeds.

    python -m predictor.train --seeds 10 --losses 0,0.3

Only tracks that were really updated in the last second are sampled (a coasting track is extrapolation and would
make the straight line look perfect), one sample a second. Nothing here reads `truth.json`.
"""

import argparse
from typing import Dict, List

from friend_foe.sweep import Setup, load_preset, make_scenario_and_truth
from pipeline.run import run
from predictor.motion import MODEL_PATH, MotionModel, Sample, fit

FRESH_S = 1.0


def collect(setup: Setup, weather: str, loss: float, histories: Dict[str, List[Sample]]) -> None:
    for i in range(setup.seeds):
        scenario, _ = make_scenario_and_truth(setup, i, weather, loss, False)
        for frame in run(scenario, scenario["seed"]):
            if abs(frame.t - round(frame.t)) > 1e-6:
                continue
            for tr in frame.tracks:
                if tr.friend_id is None and frame.t - tr.last_update <= FRESH_S:
                    histories.setdefault(f"{i}:{loss}:{tr.track_id}", []).append((frame.t, *tr.state))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", default="medium")
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--losses", default="0,0.3")
    ap.add_argument("--weather", default="clear")
    args = ap.parse_args()
    setup = Setup(load_preset(args.preset), "tuning", args.seeds, None, 0, 0)
    histories: Dict[str, List[Sample]] = {}
    for loss in (float(x) for x in args.losses.split(",")):
        collect(setup, args.weather, loss, histories)
    model: MotionModel = fit(histories)
    model.save()
    print(f"saved {MODEL_PATH.name} from {len(histories)} tracks")
    for h, s, c in zip(model.horizons_s, model.spread_m, model.speed_change_mps):
        print(f"  {h:4.0f} s: spread {s:6.1f} m, speed change (95 %) {c:5.1f} m/s")


if __name__ == "__main__":
    main()
