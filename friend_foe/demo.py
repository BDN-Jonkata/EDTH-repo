"""Run the estimator and investigation trigger over a JSON Lines file.

Run: python -m friend_foe.demo [path] [weather preset]
"""

import sys
from pathlib import Path

from friend_foe.estimator import FriendFoeEstimator
from friend_foe.investigation import InvestigationTrigger
from friend_foe.jsonl_io import read_frames
from sensors.weather import PRESETS, UniformWeather

DEFAULT = Path(__file__).parent / "data" / "local_tracks.jsonl"


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    weather = UniformWeather(PRESETS[sys.argv[2] if len(sys.argv) > 2 else "clear"])
    est, trigger = FriendFoeEstimator(), InvestigationTrigger(weather)
    last = {}
    for t, tracks, beacons in read_frames(path):
        classes = est.update(t, tracks, beacons)
        for c in classes:
            if last.get(c.track_id) != c.cls:
                print(f"t={t:5.1f}  {c.track_id:6s} -> {c.cls:10s} p_friendly={c.p_friendly:.2f}")
                last[c.track_id] = c.cls
        for r in trigger.update(t, classes, tracks):
            print(
                f"t={t:5.1f}  REQUEST investigate {r['track_id']}: standoff {r['standoff_m']:.0f} m, "
                f"weather confidence {r['weather_confidence']:.2f}, feasible={r['feasible']}"
            )


if __name__ == "__main__":
    main()
