import datetime

import pytest

from sensors.daylight import (
    FULL_NIGHT_ELEVATION_DEG,
    Sky,
    daylight_hours,
    night_strength,
    sky_from_dict,
    sun_elevation_deg,
)
from sensors.quality import load_modules, required_standoff
from sensors.weather import Conditions, EventWeather, SkyWeather, UniformWeather, WeatherEvent, weather_from_scenario

JUNE, DECEMBER, MARCH = "2026-06-21", "2026-12-21", "2026-03-20"
EO = load_modules()["eo_visible_mini4"]
POS = (100.0, 100.0, 50.0)


def doy(day: str) -> int:
    return datetime.date.fromisoformat(day).timetuple().tm_yday


# ---- the sun, against well-known values

def test_noon_sun_height_at_45_north_in_summer_and_winter():
    assert sun_elevation_deg(45, 0, doy(JUNE), 12.03, 0) == pytest.approx(68.4, abs=0.7)
    assert sun_elevation_deg(45, 0, doy(DECEMBER), 11.97, 0) == pytest.approx(21.6, abs=0.7)


def test_sun_is_overhead_at_the_equator_at_the_equinox():
    assert sun_elevation_deg(0, 0, doy(MARCH), 12.1, 0) > 88.0


def test_day_length_changes_with_the_season_and_the_latitude():
    assert daylight_hours(45, doy(JUNE)) == pytest.approx(15.5, abs=0.4)
    assert daylight_hours(45, doy(DECEMBER)) == pytest.approx(8.7, abs=0.4)
    assert daylight_hours(60, doy(JUNE)) > 18 and daylight_hours(60, doy(DECEMBER)) < 6.5
    assert daylight_hours(0, doy(JUNE)) == pytest.approx(12.0, abs=0.3)
    assert daylight_hours(0, doy(DECEMBER)) == pytest.approx(12.0, abs=0.3)


def test_the_southern_hemisphere_is_the_other_way_round():
    assert daylight_hours(-45, doy(JUNE)) < 9 < 15 < daylight_hours(-45, doy(DECEMBER))


def test_polar_day_and_polar_night():
    assert daylight_hours(80, doy(JUNE)) == 24.0
    assert daylight_hours(80, doy(DECEMBER)) == 0.0


# ---- darkness

def test_night_strength_is_zero_in_daylight_full_in_night_and_linear_between():
    assert night_strength(30) == 0.0 and night_strength(0) == 0.0
    assert night_strength(FULL_NIGHT_ELEVATION_DEG) == 1.0 and night_strength(-40) == 1.0
    assert night_strength(FULL_NIGHT_ELEVATION_DEG / 2) == pytest.approx(0.5)


def test_the_same_clock_time_is_night_in_winter_and_dusk_in_summer():
    winter, summer = Sky(DECEMBER, 21.0, 55, 0, 0), Sky(JUNE, 21.0, 55, 0, 0)
    assert winter.night_strength() == 1.0
    assert summer.night_strength() < 0.4


def test_white_nights_never_get_fully_dark_at_60_north():
    sky = Sky(JUNE, 0.0, 60, 0, 0)
    assert 0.2 < sky.night_strength() < 0.9


def test_noon_is_light_everywhere_in_the_year():
    for day in (JUNE, DECEMBER):
        assert Sky(day, 12.0, 50, 10, 0).night_strength() == 0.0


def test_the_default_clock_offset_follows_the_longitude():
    assert Sky(JUNE, 9.0, 45, 30).elevation_deg() == pytest.approx(Sky(JUNE, 9.0, 45, 30, 2).elevation_deg())


def test_the_clock_advances_with_the_time_scale_and_rolls_over_midnight():
    sky = Sky(JUNE, 20.0, 45, 0, 0, time_scale=60.0)       # one simulated minute = one clock hour
    assert sky.night_strength(0) < sky.night_strength(120) <= sky.night_strength(300)
    morning = Sky(JUNE, 23.0, 45, 0, 0, time_scale=3600.0)  # crosses midnight after one second
    assert morning.night_strength(1.0) > 0 and morning.night_strength(10.0) < morning.night_strength(1.0)


def test_sky_input_is_validated():
    for bad in (dict(date="21-06-2026"), dict(hour=24.0), dict(lat=91.0), dict(lon=181.0), dict(time_scale=-1.0)):
        args = dict(date=JUNE, hour=12.0, lat=45.0, lon=0.0) | bad
        with pytest.raises(ValueError):
            Sky(**args)
    with pytest.raises(ValueError, match="lat"):
        sky_from_dict({"date": JUNE, "hour": 12})


# ---- as weather

def test_sky_weather_adds_the_strength_of_the_night_effect():
    w = SkyWeather(UniformWeather(Conditions("fog")), Sky(DECEMBER, 21.0, 55, 0, 0))
    assert w.at(POS, 0).active_effects() == {"fog": 1.0, "night": 1.0}
    day = SkyWeather(UniformWeather(Conditions("fog")), Sky(JUNE, 12.0, 55, 0, 0))
    assert day.at(POS, 0).active_effects() == {"fog": 1.0}


def test_twilight_gives_a_partial_night_effect():
    effects = SkyWeather(UniformWeather(), Sky(JUNE, 21.0, 55, 0, 0)).at(POS, 0).active_effects()
    assert 0.01 < effects["night"] < 0.5


def test_the_sky_overrides_time_of_day_and_wraps_events():
    scenario = {"environment": {"weather": "clear", "time_of_day": "night",
                                "sky": {"date": JUNE, "hour": 12.0, "lat": 50.0, "lon": 10.0},
                                "weather_events": [{"weather": "fog", "t_start": 10, "t_end": 20}]}}
    w = weather_from_scenario(scenario)
    assert isinstance(w, SkyWeather) and isinstance(w.inner, EventWeather)
    assert w.at(POS, 0).active_effects() == {}              # noon in June: light, `night` is ignored
    assert w.at(POS, 15).active_effects() == {"fog": 1.0}


def test_without_a_sky_time_of_day_still_works():
    w = weather_from_scenario({"environment": {"weather": "clear", "time_of_day": "night"}})
    assert w.at(POS, 0).active_effects() == {"night": 1.0}


def test_season_changes_how_far_a_camera_must_go_at_the_same_hour():
    def standoff(day):
        w = SkyWeather(UniformWeather(), Sky(day, 18.0, 55, 0, 0))
        return required_standoff(EO, POS, 0.0, w).max_range_m
    assert standoff(DECEMBER) < standoff(JUNE)


def test_an_event_keeps_a_stronger_night_than_the_sky():
    inner = EventWeather(Conditions(), (WeatherEvent("night", 0, 100),))
    assert SkyWeather(inner, Sky(JUNE, 12.0, 50, 0, 0)).at(POS, 0).active_effects() == {"night": 1.0}
