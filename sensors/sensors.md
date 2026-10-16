# sensors module

Sensor models (camera bearing, acoustic, RF, radar) including weather effects. Each outputs observations with honest covariances.

Status: weather and sensor quality done; observation models not started. See [system design](../docs/system-design.md).

## What exists

| File | Contents |
|------|----------|
| [weather.py](weather.py) | `WeatherState` (wind, visibility, rain, light), presets (clear, fog, rain, wind, night, storm), `UniformWeather` provider |
| [quality.py](quality.py) | Per-sensor clear-weather ranges and weather scaling, `sensor_quality`, `sensor_hierarchy`, `required_standoff`, `standoff_by_sensor`, `best_standoff` |
| [test_quality.py](test_quality.py) | Tests |

## How weather works

Each sensor type has a clear-weather detection and identification range. Weather scales that range (camera: fog, rain, low light; acoustic: wind, rain; radar: rain; RF: almost nothing). The same scale drives measurement noise and detection probability, so weather affects fusion through honest covariances. `sensor_hierarchy` ranks the sensors in the current weather, and `required_standoff` gives how close a drone must get to identify an object (see system design 5.8).

All ranges and coefficients are placeholders to tune.

## Not done yet

- Observation models that produce `Observation` messages from ground truth (needs the simulation).
- Applying `sensor_quality` to the noise and detection probability of those observations.
- Spatially or temporally varying weather (the `WeatherProvider` interface already allows it).
