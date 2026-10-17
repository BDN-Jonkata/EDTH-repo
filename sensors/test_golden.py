import json

import pytest

from sensors.golden import PATH, build_cases
from sensors.weather import Conditions, EventWeather, UniformWeather, WeatherEvent, conditions_between

POS = (0.0, 0.0, 0.0)


def test_the_shared_cases_file_matches_the_code():
    """Fails when the weather code changes without `python -m sensors.golden` being run."""
    def same(actual, expected):
        if isinstance(expected, float):
            assert actual == pytest.approx(expected, rel=1e-9, abs=1e-12)
        elif isinstance(expected, dict):
            assert actual.keys() == expected.keys()
            for key in expected:
                same(actual[key], expected[key])
        elif isinstance(expected, list):
            assert len(actual) == len(expected)
            for a, b in zip(actual, expected):
                same(a, b)
        else:
            assert actual == expected
    # libm implementations differ in their final bits; use the shared 1e-9
    # float tolerance already required of the JavaScript implementation.
    same(json.loads(PATH.read_text(encoding="utf-8")), json.loads(json.dumps(build_cases())))


def test_the_cases_cover_what_a_second_implementation_must_get_right():
    cases = build_cases()
    assert len(cases["quality"]) >= 60 and len(cases["sky"]) >= 10 and len(cases["event_weather"]) >= 100
    assert any(c["night_strength"] == 1.0 for c in cases["sky"]) and any(c["night_strength"] == 0.0 for c in cases["sky"])
    assert any(0.0 < c["night_strength"] < 1.0 for c in cases["sky"])   # twilight


# ---- the rule for a detection: the strongest of each effect at the sensor and at the target

def fog_bank():
    return EventWeather(Conditions(), (WeatherEvent("fog", zone=(500, 500, 100)),))


def test_fog_over_either_end_counts():
    w = fog_bank()
    assert conditions_between(w, (500, 500, 0), (900, 900, 0), 0).active_effects() == {"fog": 1.0}
    assert conditions_between(w, (900, 900, 0), (500, 500, 0), 0).active_effects() == {"fog": 1.0}
    assert conditions_between(w, (900, 900, 0), (800, 800, 0), 0).active_effects() == {}


def test_each_effect_takes_its_strongest_strength():
    w = EventWeather(Conditions("rain:0.3"), (WeatherEvent("rain:0.8+wind", zone=(0, 0, 50)),))
    assert conditions_between(w, (0, 0, 0), (900, 900, 0), 0).active_effects() == {"rain": 0.8, "wind": 1.0}


def test_night_from_time_of_day_is_kept():
    w = UniformWeather(Conditions("fog", "night"))
    assert conditions_between(w, POS, POS, 0).active_effects() == {"fog": 1.0, "night": 1.0}
