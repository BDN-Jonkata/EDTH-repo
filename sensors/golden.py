"""Shared test cases for the weather and sun maths, so a second implementation can be checked.

The reference is the Python code in `weather.py`, `daylight.py` and `quality.py`. The viewer
(JavaScript) has to give the same answers; its test reads `testdata/weather_cases.json` and
compares. The file is generated, do not edit it:

    python -m sensors.golden            # rewrite the file
    python -m pytest sensors/test_golden.py   # fails if the file no longer matches the code

Compare floats with a tolerance (relative 1e-9); the cases are plain data.
"""

import json
import math
from pathlib import Path
from typing import List

from sensors.daylight import Sky
from sensors.quality import load_modules, sensor_quality
from sensors.weather import (Conditions, EventWeather, SkyWeather, UniformWeather, WeatherEvent, conditions_between,
                             parse_weather)

PATH = Path(__file__).parent / "testdata" / "weather_cases.json"
MODULES = ("eo_visible_mini4", "mic_array_4ch", "radar_mmwave_small", "thermal_boson_plus_640")
WEATHERS = ("clear", "fog", "fog:0.5", "wind", "fog+wind", "rain:0.6+wind", "fog+rain+wind", "night")
VALID_TEXTS = ("clear", "fog", "night", "fog+wind", "rain:0.6+wind", "fog:0.25+rain+wind:0.5")
INVALID_TEXTS = ("snow", "fog+fog", "clear+fog", "fog:0", "fog:1.5", "fog:abc", "fog+", "")
SKIES = (
    dict(date="2026-06-21", hour=12.0, lat=45.0, lon=0.0, utc_offset_h=0.0, time_scale=1.0, t=0.0),
    dict(date="2026-12-21", hour=12.0, lat=45.0, lon=0.0, utc_offset_h=0.0, time_scale=1.0, t=0.0),
    dict(date="2026-06-21", hour=21.0, lat=55.0, lon=0.0, utc_offset_h=0.0, time_scale=1.0, t=0.0),
    dict(date="2026-12-21", hour=21.0, lat=55.0, lon=0.0, utc_offset_h=0.0, time_scale=1.0, t=0.0),
    dict(date="2026-12-21", hour=17.0, lat=55.0, lon=0.0, utc_offset_h=0.0, time_scale=1.0, t=0.0),
    dict(date="2026-06-21", hour=0.0, lat=60.0, lon=0.0, utc_offset_h=0.0, time_scale=1.0, t=0.0),
    dict(date="2026-03-20", hour=12.1, lat=0.0, lon=0.0, utc_offset_h=0.0, time_scale=1.0, t=0.0),
    dict(date="2026-06-21", hour=12.0, lat=-45.0, lon=0.0, utc_offset_h=0.0, time_scale=1.0, t=0.0),
    dict(date="2026-06-21", hour=9.0, lat=45.0, lon=30.0, utc_offset_h=None, time_scale=1.0, t=0.0),
    dict(date="2026-06-21", hour=20.0, lat=45.0, lon=0.0, utc_offset_h=0.0, time_scale=60.0, t=0.0),
    dict(date="2026-06-21", hour=20.0, lat=45.0, lon=0.0, utc_offset_h=0.0, time_scale=60.0, t=120.0),
    dict(date="2026-06-21", hour=20.0, lat=45.0, lon=0.0, utc_offset_h=0.0, time_scale=60.0, t=300.0),
    dict(date="2026-06-21", hour=23.0, lat=45.0, lon=0.0, utc_offset_h=0.0, time_scale=3600.0, t=1.0),
    dict(date="2026-12-31", hour=23.0, lat=45.0, lon=0.0, utc_offset_h=0.0, time_scale=3600.0, t=2.0),
)
EVENTS = [
    {"weather": "fog", "t_start": 40.0, "t_end": 80.0, "zone": {"x": 500.0, "y": 500.0, "radius_m": 100.0}},
    {"weather": "fog:0.4+rain", "t_start": 0.0, "t_end": 100.0},
    {"weather": "wind", "t_start": 60.0},
]
EVENT_BASES = ("clear", "wind", "rain:0.8")
EVENT_POINTS = ((500.0, 500.0), (550.0, 500.0), (700.0, 500.0), (50.0, 50.0))
EVENT_TIMES = (0.0, 40.0, 59.9, 60.0, 79.9, 80.0, 99.9, 100.0, 1000.0)


def _event(e: dict) -> WeatherEvent:
    z = e.get("zone")
    return WeatherEvent(e["weather"], e.get("t_start", 0.0), e.get("t_end", math.inf),
                        (z["x"], z["y"], z["radius_m"]) if z else None)


def _parse_cases() -> dict:
    invalid = []
    for text in INVALID_TEXTS:
        try:
            parse_weather(text)
        except ValueError:
            invalid.append(text)
    return {"valid": [{"text": t, "effects": parse_weather(t)} for t in VALID_TEXTS], "invalid": invalid}


def _quality_cases() -> List[dict]:
    modules, cases = load_modules(), []
    for module_id in MODULES:
        for weather in WEATHERS:
            for tod in ("day", "night"):
                q = sensor_quality(modules[module_id], Conditions(weather, tod))
                cases.append({"module": module_id, "weather": weather, "time_of_day": tod,
                              "range_scale": q.range_scale, "noise_scale": q.noise_scale, "pd_scale": q.pd_scale})
    return cases


def _sky_cases() -> List[dict]:
    cases = []
    for s in SKIES:
        sky = Sky(s["date"], s["hour"], s["lat"], s["lon"], s["utc_offset_h"], s["time_scale"])
        cases.append({**s, "elevation_deg": sky.elevation_deg(s["t"]), "night_strength": sky.night_strength(s["t"]),
                      "daylight_hours": sky.daylight_hours()})
    return cases


def _event_cases() -> List[dict]:
    events, cases = tuple(_event(e) for e in EVENTS), []
    for base in EVENT_BASES:
        provider = EventWeather(Conditions(base), events)
        for x, y in EVENT_POINTS:
            for t in EVENT_TIMES:
                cases.append({"base": base, "x": x, "y": y, "t": t, "effects": provider.at((x, y, 0.0), t).active_effects()})
    return cases


def _link_cases() -> List[dict]:
    provider = EventWeather(Conditions("rain:0.3"), (_event(EVENTS[0]),))
    cases = []
    for a, b in (((500.0, 500.0), (900.0, 900.0)), ((900.0, 900.0), (500.0, 500.0)), ((900.0, 900.0), (50.0, 50.0))):
        for t in (10.0, 50.0):
            cases.append({"sensor": list(a), "target": list(b), "t": t,
                          "effects": conditions_between(provider, (*a, 0.0), (*b, 0.0), t).active_effects()})
    return cases


def build_cases() -> dict:
    return {
        "_comment": "Generated by python -m sensors.golden from the Python reference. Do not edit. Compare floats with relative tolerance 1e-9.",
        "events": EVENTS, "event_bases": list(EVENT_BASES),
        "parse": _parse_cases(), "quality": _quality_cases(), "sky": _sky_cases(),
        "event_weather": _event_cases(), "link_weather": _link_cases(),
    }


def main() -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(build_cases(), indent=1) + "\n", encoding="utf-8")
    print(f"wrote {PATH}")


if __name__ == "__main__":
    main()
