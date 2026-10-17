# sensors module

Sensor models (camera bearing, acoustic, RF, radar) including weather effects. Each outputs observations with honest covariances.

Status: weather conditions (single, combined and changing over time and place), sensor quality, required standoff and a weather report done, built on the seeder catalog; observation models not started. See [system design](../docs/system-design.md).

## What exists

| File | Contents |
|------|----------|
| [weather.py](weather.py) | `Conditions` (`weather` text such as `fog+wind` or `rain:0.6+wind`, plus `time_of_day`), presets (clear, fog, rain, wind, night, fog_night, storm, fog_rain, fog_wind, storm_night, worst), `UniformWeather`, `WeatherEvent` and `EventWeather` (anomalies that start, end and cover a zone), `SkyWeather` (adds the darkness from the sky), `weather_from_scenario` |
| [daylight.py](daylight.py) | `Sky` (date, clock time, latitude, longitude, time scale), `sun_elevation_deg`, `night_strength`, `daylight_hours`: how dark it is, following the season and the place |
| [quality.py](quality.py) | `load_modules`, `load_platforms`, `sensor_quality`, `modules_that_still_work`, `sensor_hierarchy`, `required_standoff`, `standoff_by_module`, `best_standoff`, `modules_in_scenario` |
| [golden.py](golden.py), [testdata/weather_cases.json](testdata/weather_cases.json) | Shared test cases (parsing, sensor quality, sun and night strength, events, per-detection weather) generated from this Python code, so a second implementation (the viewer's JavaScript) can be checked against it: `python -m sensors.golden` rewrites the file, `test_golden.py` fails if it is out of date. It depends on the catalog's `weather_effects`, so regenerate it when those change |
| [report.py](report.py) | `python -m sensors.report`: which modules and platforms survive each weather combination, and the best identification distance per platform |
| `test_quality.py`, `test_weather.py`, `test_daylight.py`, `test_golden.py` | Tests |

## How weather works

The numbers are not in this module. Each catalog sensor module has `sim.range_m`, `sim.min_range_m` and `weather_effects` (range, noise and detection-probability multipliers for fog, rain, wind and night). `Conditions.active_effects()` says which apply and how strongly. An anomaly at strength `s` moves its multiplier a share `s` of the way towards 1. Several anomalies **multiply**: a worst-case assumption for range, so a combination is never better than its worst member. Night counts once however it is set. `sensor_quality` returns the combined scales, so weather reaches fusion through honest noise. `sensor_hierarchy` ranks detection modules by effective range weighted by detection probability. `required_standoff` gives how close a drone carrying a module must get to identify an object (system design 5.8; message in [data-formats.md](../docs/data-formats.md)).

Day and night follow the season. A fixed night from, say, 21:00 to 05:00 is wrong, because the length of the day depends on the date and the latitude. `Sky(date, hour, lat, lon)` computes the sun's height above the horizon (the standard NOAA approximation, checked against known values) and turns it into a night strength from 0 to 1: 0 with the sun up, rising linearly through twilight to 1 at 12 degrees below the horizon (a placeholder mapping, since the catalog only has one full-night multiplier). The same 21:00 is night in December and dusk in June, and near 60 N a June night never gets fully dark. `SkyWeather` adds that strength as the `night` effect on top of any weather, so dusk and fog combine. Moon and cloud cover are ignored.

Anomalies that come and go: `EventWeather(base, events)` answers for a position and time, so `required_standoff` uses the weather at the object when the request is made. The scenario format for combinations and events is a proposal that the seeder and viewer do not support yet; see "Weather combinations" in [data-formats.md](../docs/data-formats.md).

**Finding:** the catalog check only tests single weathers. In combination, platforms lose every working detection module: fog and rain leave `anafi_thermal` with none, fog and wind (or rain, wind and night) leave `mini4pro` and `gs_eo_acoustic` with none (camera hurt by fog, microphone by wind), and fog, rain and wind at night leave 4 of 7 platforms without one. The radar and RF platforms survive everything.

The one number the catalog lacks is how much of a module's detection range is good enough to identify an object. `IDENT_FRACTION` in `quality.py` is a **placeholder** per module kind; the clean fix is a field such as `sim.ident_range_m` in the catalog, after which the placeholder goes away. Like the catalog numbers, it is an assumption.

## Not done yet

- Observation models that produce sensor messages from the scenario (needs the simulation).
- Applying `sensor_quality` to the noise and detection probability of those observations.
- Seeder and viewer support for combined weather and weather events (proposed to the seeder owner).
- Weather that changes a sensor's own position over time (a drone flying out of a fog bank): standoff uses the weather at the object only.
