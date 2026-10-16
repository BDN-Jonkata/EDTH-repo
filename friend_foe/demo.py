"""Run the estimator and investigation trigger over test input.

    python -m friend_foe.demo                                    # hand-made data/local_tracks.jsonl
    python -m friend_foe.demo path/to/file.jsonl [weather]       # weather: clear fog rain wind night fog_night
    python -m friend_foe.demo out/hard-s3/scenario.json          # scenario made by seeder/generate.py
"""

import json
import sys
from pathlib import Path

from friend_foe.estimator import FriendFoeEstimator
from friend_foe.investigation import InvestigationTrigger
from friend_foe.jsonl_io import read_frames
from friend_foe.scenario_adapter import frames_from_scenario
from sensors.quality import modules_in_scenario
from sensors.weather import PRESETS, UniformWeather, weather_from_scenario

DEFAULT = Path(__file__).parent / "data" / "local_tracks.jsonl"


def setup(path: Path, weather_name: str):
    """Return (frames, trigger) for a .jsonl file or a scenario.json."""
    if path.name.endswith("scenario.json"):
        scenario = json.loads(path.read_text(encoding="utf-8"))
        weather = weather_from_scenario(scenario)
        return frames_from_scenario(scenario), InvestigationTrigger(weather, modules_in_scenario(scenario))
    return read_frames(path), InvestigationTrigger(UniformWeather(PRESETS[weather_name]))


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    frames, trigger = setup(path, sys.argv[2] if len(sys.argv) > 2 else "clear")
    est, last = FriendFoeEstimator(), {}
    for t, tracks, beacons in frames:
        classes = est.update(t, tracks, beacons)
        for c in classes:
            if last.get(c.track_id) != c.cls:
                print(f"t={t:6.1f}  {c.track_id:6s} -> {c.cls:10s} p_friendly={c.p_friendly:.2f}")
                last[c.track_id] = c.cls
        for r in trigger.update(t, classes, tracks):
            print(
                f"t={t:6.1f}  REQUEST investigate {r['track_id']}: standoff {r['standoff_m']:.0f} m, "
                f"weather confidence {r['weather_confidence']:.2f}, feasible={r['feasible']}"
            )


if __name__ == "__main__":
    main()
