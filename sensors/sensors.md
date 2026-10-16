# sensors module

Sensor models (camera bearing, acoustic, RF, radar) including weather effects. Each outputs observations with honest covariances.

Status: weather conditions, sensor quality and required standoff done, built on the seeder catalog; observation models not started. See [system design](../docs/system-design.md).

## What exists

| File | Contents |
|------|----------|
| [weather.py](weather.py) | `Conditions` (`weather` + `time_of_day`, as in `scenario.json`), presets (clear, fog, rain, wind, night, fog_night), `UniformWeather` provider, `weather_from_scenario` |
| [quality.py](quality.py) | `load_modules`, `sensor_quality`, `sensor_hierarchy`, `required_standoff`, `standoff_by_module`, `best_standoff`, `modules_in_scenario` |
| [test_quality.py](test_quality.py) | Tests |

## How weather works

The numbers are not in this module. Each catalog sensor module has `sim.range_m`, `sim.min_range_m` and `weather_effects` (range, noise and detection-probability multipliers for fog, rain, wind and night). `Conditions.active_effects()` says which apply; they multiply (fog at night = fog x night), and night counts once however it is set. `sensor_quality` returns the combined scales, so weather reaches fusion through honest noise. `sensor_hierarchy` ranks detection modules by effective range weighted by detection probability. `required_standoff` gives how close a drone carrying a module must get to identify an object (system design 5.8; message in [data-formats.md](../docs/data-formats.md)).

The one number the catalog lacks is how much of a module's detection range is good enough to identify an object. `IDENT_FRACTION` in `quality.py` is a **placeholder** per module kind; the clean fix is a field such as `sim.ident_range_m` in the catalog, after which the placeholder goes away. Like the catalog numbers, it is an assumption.

## Not done yet

- Observation models that produce sensor messages from the scenario (needs the simulation).
- Applying `sensor_quality` to the noise and detection probability of those observations.
- Spatially or temporally varying weather (the `WeatherProvider` interface already allows it).
