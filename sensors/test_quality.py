from sensors.quality import (
    SENSOR_SPECS,
    best_standoff,
    required_standoff,
    sensor_hierarchy,
    sensor_quality,
    standoff_by_sensor,
)
from sensors.weather import CLEAR, FOG, NIGHT, PRESETS, STORM, WIND, UniformWeather

POS = (100.0, 200.0, 50.0)


def test_clear_weather_is_full_capability():
    for name in SENSOR_SPECS:
        assert sensor_quality(name, CLEAR).range_scale == 1.0


def test_scales_stay_in_range():
    for weather in PRESETS.values():
        for name in SENSOR_SPECS:
            q = sensor_quality(name, weather)
            assert 0.0 <= q.range_scale <= 1.0
            assert q.noise_scale >= 1.0
            assert 0.0 <= q.pd_scale <= 1.0


def test_fog_hurts_camera_most():
    scales = {n: sensor_quality(n, FOG).range_scale for n in SENSOR_SPECS}
    assert min(scales, key=scales.get) == "camera"
    assert scales["rf"] == 1.0 and scales["radar"] == 1.0 and scales["acoustic"] > 0.9


def test_wind_hurts_acoustic_most():
    scales = {n: sensor_quality(n, WIND).range_scale for n in SENSOR_SPECS}
    assert min(scales, key=scales.get) == "acoustic"


def test_night_hurts_camera_only():
    assert sensor_quality("camera", NIGHT).range_scale < 0.5
    for name in ("acoustic", "rf", "radar"):
        assert sensor_quality(name, NIGHT).range_scale == 1.0


def test_hierarchy_changes_with_weather():
    assert sensor_hierarchy(CLEAR)[0] == "rf"
    assert sensor_hierarchy(FOG).index("camera") > sensor_hierarchy(CLEAR).index("camera")


def test_standoff_shrinks_in_fog():
    clear = required_standoff("camera", POS, 0.0, UniformWeather(CLEAR))
    fog = required_standoff("camera", POS, 0.0, UniformWeather(FOG))
    assert clear.max_range_m == SENSOR_SPECS["camera"].ident_range_m
    assert fog.max_range_m < clear.max_range_m
    assert fog.recommended_m < fog.max_range_m
    assert fog.confidence < clear.confidence


def test_standoff_infeasible_in_dense_fog_for_camera():
    from sensors.weather import WeatherState

    dense = UniformWeather(WeatherState(visibility_m=10.0))
    assert not required_standoff("camera", POS, 0.0, dense).feasible


def test_best_standoff_picks_longest_range():
    by_sensor = standoff_by_sensor(["camera", "acoustic"], POS, 0.0, UniformWeather(FOG))
    best = best_standoff(by_sensor)
    assert best.max_range_m == max(s.max_range_m for s in by_sensor.values())


def test_storm_is_worse_than_clear_for_every_sensor():
    for name in SENSOR_SPECS:
        assert sensor_quality(name, STORM).range_scale < 1.0
