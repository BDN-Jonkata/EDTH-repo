import pytest

from sensors.quality import (
    IDENT_FRACTION,
    best_standoff,
    detection_modules,
    load_modules,
    modules_in_scenario,
    required_standoff,
    sensor_hierarchy,
    sensor_quality,
    standoff_by_module,
)
from sensors.weather import Conditions, PRESETS, UniformWeather, weather_from_scenario

POS = (100.0, 200.0, 50.0)
MODULES = load_modules()
DETECTION = detection_modules(MODULES.values())
EO = MODULES["eo_visible_mini4"]
MIC = MODULES["mic_array_4ch"]
RADAR = MODULES["radar_mmwave_small"]
RF = MODULES["rf_sdr_receiver"]


def standoff(module, name):
    return required_standoff(module, POS, 0.0, UniformWeather(PRESETS[name]))


def test_every_detection_kind_has_an_identification_fraction():
    assert {m["kind"] for m in DETECTION} <= set(IDENT_FRACTION)


def test_clear_day_is_full_capability():
    for m in DETECTION:
        q = sensor_quality(m, PRESETS["clear"])
        assert (q.range_scale, q.noise_scale, q.pd_scale) == (1.0, 1.0, 1.0)


def test_quality_comes_from_the_catalog():
    fog = EO["weather_effects"]["fog"]
    q = sensor_quality(EO, PRESETS["fog"])
    assert (q.range_scale, q.noise_scale, q.pd_scale) == (fog["range_mult"], fog["noise_mult"], fog["pd_mult"])


def test_night_counts_once_however_it_is_set():
    by_weather = sensor_quality(EO, Conditions(weather="night"))
    by_time = sensor_quality(EO, Conditions(time_of_day="night"))
    both = sensor_quality(EO, Conditions(weather="night", time_of_day="night"))
    assert by_weather == by_time == both


def test_fog_at_night_multiplies_both_effects():
    fog, night = EO["weather_effects"]["fog"], EO["weather_effects"]["night"]
    q = sensor_quality(EO, PRESETS["fog_night"])
    assert q.range_scale == pytest.approx(fog["range_mult"] * night["range_mult"])


def test_unknown_conditions_are_rejected():
    with pytest.raises(ValueError):
        Conditions(weather="hail")
    with pytest.raises(ValueError):
        Conditions(time_of_day="dusk")


def test_fog_hurts_the_camera_more_than_the_radar():
    assert sensor_quality(EO, PRESETS["fog"]).range_scale < sensor_quality(RADAR, PRESETS["fog"]).range_scale


def test_wind_hurts_the_microphone_more_than_the_camera():
    assert sensor_quality(MIC, PRESETS["wind"]).range_scale < sensor_quality(EO, PRESETS["wind"]).range_scale


def test_hierarchy_lists_detection_modules_only_and_changes_with_weather():
    clear = sensor_hierarchy(MODULES.values(), PRESETS["clear"])
    fog = sensor_hierarchy(MODULES.values(), PRESETS["fog"])
    assert set(clear) == {m["id"] for m in DETECTION}
    assert fog.index(EO["id"]) > clear.index(EO["id"])


def test_standoff_shrinks_in_fog_and_stays_inside_the_maximum():
    clear, fog = standoff(EO, "clear"), standoff(EO, "fog")
    assert fog.max_range_m < clear.max_range_m
    assert fog.confidence < clear.confidence
    assert fog.recommended_m <= fog.max_range_m


def test_standoff_never_goes_inside_the_minimum_range():
    for m in DETECTION:
        s = standoff(m, "clear")
        assert s.recommended_m >= min(m["sim"]["min_range_m"], s.max_range_m)


def test_fog_at_night_makes_a_basic_camera_infeasible_but_not_radar():
    basic = MODULES["eo_visible_basic"]
    assert not standoff(basic, "fog_night").feasible
    assert standoff(RADAR, "fog_night").feasible


def test_standoff_by_module_covers_detection_modules_and_best_prefers_feasible():
    by_module = standoff_by_module(MODULES.values(), POS, 0.0, UniformWeather(PRESETS["fog_night"]))
    assert set(by_module) == {m["id"] for m in DETECTION}
    best = best_standoff(by_module)
    assert best.feasible and best.max_range_m == max(s.max_range_m for s in by_module.values())


def test_weather_and_modules_from_a_scenario():
    scenario = {
        "environment": {"weather": "rain", "time_of_day": "night"},
        "friendlies": [
            {"sensors": [{"module": EO["id"]}, {"module": "gnss_basic"}]},
            {"sensors": [{"module": EO["id"]}, {"module": RF["id"]}]},
        ],
    }
    assert weather_from_scenario(scenario).conditions == Conditions("rain", "night")
    assert [m["id"] for m in modules_in_scenario(scenario)] == [EO["id"], RF["id"]]
