import math

import pytest

from sensors.quality import (
    detection_modules,
    load_modules,
    modules_that_still_work,
    required_standoff,
    sensor_hierarchy,
    sensor_quality,
)
from sensors.weather import (
    Conditions,
    EventWeather,
    PRESETS,
    UniformWeather,
    WeatherEvent,
    format_weather,
    parse_weather,
    weather_from_scenario,
)

MODULES = load_modules()
DETECTION = detection_modules(MODULES.values())
EO, MIC, RADAR = MODULES["eo_visible_mini4"], MODULES["mic_array_4ch"], MODULES["radar_mmwave_small"]
POS = (100.0, 100.0, 50.0)


# ---- the text form

def test_parse_one_several_and_weaker_anomalies():
    assert parse_weather("clear") == {}
    assert parse_weather("fog") == {"fog": 1.0}
    assert parse_weather("fog+wind") == {"fog": 1.0, "wind": 1.0}
    assert parse_weather("rain:0.6+wind") == {"rain": 0.6, "wind": 1.0}


@pytest.mark.parametrize("bad", ["snow", "fog+fog", "clear+fog", "fog:0", "fog:1.5", "fog:abc", "fog+", ""])
def test_bad_weather_text_is_rejected(bad):
    with pytest.raises(ValueError):
        parse_weather(bad)


def test_format_round_trips():
    for text in ("clear", "fog", "fog+wind", "fog:0.5+rain"):
        assert parse_weather(format_weather(parse_weather(text))) == parse_weather(text)


def test_night_joins_the_weather_and_counts_once():
    assert Conditions("fog", "night").active_effects() == {"fog": 1.0, "night": 1.0}
    assert Conditions("night", "night").active_effects() == {"night": 1.0}


# ---- combinations of anomalies

def test_strength_moves_the_multiplier_towards_one():
    fog = EO["weather_effects"]["fog"]
    half = sensor_quality(EO, Conditions("fog:0.5"))
    assert half.range_scale == pytest.approx(1 + 0.5 * (fog["range_mult"] - 1))
    assert half.noise_scale == pytest.approx(1 + 0.5 * (fog["noise_mult"] - 1))
    assert sensor_quality(EO, Conditions("fog:1")) == sensor_quality(EO, Conditions("fog"))


def test_combined_anomalies_multiply():
    fog, wind = EO["weather_effects"]["fog"], EO["weather_effects"]["wind"]
    q = sensor_quality(EO, Conditions("fog+wind"))
    assert q.range_scale == pytest.approx(fog["range_mult"] * wind["range_mult"])
    assert q.noise_scale == pytest.approx(fog["noise_mult"] * wind["noise_mult"])
    assert q.pd_scale == pytest.approx(fog["pd_mult"] * wind["pd_mult"])


def test_adding_an_anomaly_never_helps_any_module():
    for m in DETECTION:
        for base in ("clear", "fog", "rain", "wind", "fog+rain"):
            for extra in ("fog", "rain", "wind"):
                if extra in parse_weather(base):
                    continue
                before, after = sensor_quality(m, Conditions(base)), sensor_quality(m, Conditions(f"{base}+{extra}".replace("clear+", "")))
                assert after.range_scale <= before.range_scale + 1e-12
                assert after.pd_scale <= before.pd_scale + 1e-12
                assert after.noise_scale >= before.noise_scale - 1e-12


def test_a_combination_is_never_better_than_its_worst_member():
    for m in DETECTION:
        both = sensor_quality(m, Conditions("fog+wind")).range_scale
        assert both <= min(sensor_quality(m, Conditions("fog")).range_scale, sensor_quality(m, Conditions("wind")).range_scale) + 1e-12


def test_the_combination_that_beats_each_platform_alone_exists():
    # a camera is hurt by fog and a microphone by wind: either alone leaves the other, both leave nothing
    pair = [EO, MIC]
    assert modules_that_still_work(pair, Conditions("fog"))
    assert modules_that_still_work(pair, Conditions("wind"))
    assert not modules_that_still_work(pair, Conditions("fog+wind"))


def test_radar_and_rf_survive_the_worst_combination():
    worst = PRESETS["worst"]
    assert RADAR["id"] in modules_that_still_work(DETECTION, worst)
    assert len(modules_that_still_work(DETECTION, worst)) < len(modules_that_still_work(DETECTION, PRESETS["fog"]))


def test_combination_changes_the_hierarchy_and_the_standoff():
    clear, storm = sensor_hierarchy(DETECTION, PRESETS["clear"]), sensor_hierarchy(DETECTION, PRESETS["worst"])
    assert clear != storm
    alone = required_standoff(EO, POS, 0.0, UniformWeather(PRESETS["fog"])).max_range_m
    both = required_standoff(EO, POS, 0.0, UniformWeather(PRESETS["fog_rain"])).max_range_m
    assert both < alone


def test_report_lists_platforms_left_without_a_working_module():
    from sensors.report import survival_rows
    from sensors.quality import load_platforms
    rows = {r[0]: r for r in survival_rows(MODULES, load_platforms())}
    assert rows["clear"][2] == "-" and rows["fog"][2] == "-"
    assert "mini4pro" in rows["fog_wind"][2]
    assert int(rows["worst"][1].split("/")[0]) < int(rows["fog"][1].split("/")[0])


# ---- anomalies that come and go

def test_event_starts_and_ends_on_time():
    w = EventWeather(Conditions(), (WeatherEvent("fog", t_start=40, t_end=80),))
    assert w.at(POS, 39.9).weather == "clear"
    assert w.at(POS, 40).weather == "fog"
    assert w.at(POS, 79.9).weather == "fog"
    assert w.at(POS, 80).weather == "clear"


def test_zone_event_only_applies_inside_the_circle():
    w = EventWeather(Conditions(), (WeatherEvent("fog", zone=(500, 500, 100)),))
    assert w.at((550, 500, 0), 0).weather == "fog"
    assert w.at((700, 500, 0), 0).weather == "clear"


def test_events_stack_on_the_base_and_each_other_with_the_strongest_strength():
    w = EventWeather(Conditions("wind", "night"), (WeatherEvent("fog:0.4", 0, 100), WeatherEvent("fog:0.7+rain", 50, 100)))
    assert w.at(POS, 10).active_effects() == {"wind": 1.0, "fog": 0.4, "night": 1.0}
    assert w.at(POS, 60).active_effects() == {"wind": 1.0, "fog": 0.7, "rain": 1.0, "night": 1.0}


def test_standoff_follows_the_weather_at_the_target_and_the_time():
    w = EventWeather(Conditions(), (WeatherEvent("fog", 40, 80, zone=(500, 500, 100)),))
    clear = required_standoff(EO, (500, 500, 50), 10.0, w).max_range_m
    in_fog = required_standoff(EO, (500, 500, 50), 50.0, w).max_range_m
    elsewhere = required_standoff(EO, (50, 50, 50), 50.0, w).max_range_m
    assert in_fog < clear and elsewhere == clear


def test_event_validation():
    with pytest.raises(ValueError):
        WeatherEvent("fog", t_start=10, t_end=10)
    with pytest.raises(ValueError):
        WeatherEvent("snow")


def test_scenario_with_events_gives_event_weather_and_without_stays_uniform():
    scenario = {"environment": {"weather": "wind", "time_of_day": "day"}}
    assert isinstance(weather_from_scenario(scenario), UniformWeather)
    scenario["environment"]["weather_events"] = [
        {"weather": "fog", "t_start": 40, "t_end": 80, "zone": {"x": 500, "y": 500, "radius_m": 150}}]
    w = weather_from_scenario(scenario)
    assert isinstance(w, EventWeather)
    assert w.at((500, 500, 0), 50).active_effects() == {"wind": 1.0, "fog": 1.0}
    assert w.at((500, 500, 0), 10).active_effects() == {"wind": 1.0}


def test_scenario_may_carry_a_combination_directly():
    w = weather_from_scenario({"environment": {"weather": "fog+wind", "time_of_day": "night"}})
    assert w.conditions.active_effects() == {"fog": 1.0, "wind": 1.0, "night": 1.0}


def test_an_open_ended_event_lasts_to_the_end():
    w = EventWeather(Conditions(), (WeatherEvent("rain", t_start=5),))
    assert w.at(POS, 1e9).weather == "rain" and math.isinf(w.events[0].t_end)
