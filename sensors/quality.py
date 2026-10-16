"""Sensor quality under weather: the sensor hierarchy and required standoff.

Every number in SENSOR_SPECS is a placeholder to be tuned; the structure is
what matters. Weather scales each sensor's range, and the same scale drives
its noise and detection probability, so weather influences fusion through
honest covariances instead of a hand-made trust list.
"""

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Sequence

from sensors.weather import WeatherProvider, WeatherState

MIN_USEFUL_RANGE_M = 20.0   # below this, identification is not worth attempting
STANDOFF_MARGIN = 0.7       # aim for this fraction of the maximum identification range


@dataclass(frozen=True)
class SensorSpec:
    detect_range_m: float   # clear-weather range at which a target is detected
    ident_range_m: float    # clear-weather range at which a target can be identified
    weather_scale: Callable[[WeatherState, float], float]  # (weather, base range) -> 0..1


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _camera_scale(w: WeatherState, base_range_m: float) -> float:
    # Fog caps range near the visibility distance; rain and low light reduce it further.
    fog = _clamp01(0.8 * w.visibility_m / base_range_m)
    rain = 1.0 / (1.0 + 0.04 * w.rain_mm_h)
    light = 1.0 - 0.7 * (1.0 - _clamp01(w.light))
    return _clamp01(fog * rain * light)


def _acoustic_scale(w: WeatherState, base_range_m: float) -> float:
    # Wind noise dominates; rain adds broadband noise. Fog and light do not matter.
    wind = 1.0 / (1.0 + 0.5 * (w.wind_mps / 5.0) ** 2)
    rain = 1.0 / (1.0 + 0.02 * w.rain_mm_h)
    return _clamp01(wind * rain)


def _rf_scale(w: WeatherState, base_range_m: float) -> float:
    # Largely weather independent; heavy rain adds slight attenuation.
    return _clamp01(1.0 / (1.0 + 0.005 * w.rain_mm_h))


def _radar_scale(w: WeatherState, base_range_m: float) -> float:
    # Rain attenuates and adds clutter; fog and light do not matter.
    return _clamp01(1.0 / (1.0 + 0.015 * w.rain_mm_h))


SENSOR_SPECS: Dict[str, SensorSpec] = {
    "camera":   SensorSpec(detect_range_m=1000.0, ident_range_m=400.0, weather_scale=_camera_scale),
    "acoustic": SensorSpec(detect_range_m=300.0,  ident_range_m=150.0, weather_scale=_acoustic_scale),
    "rf":       SensorSpec(detect_range_m=1500.0, ident_range_m=800.0, weather_scale=_rf_scale),
    "radar":    SensorSpec(detect_range_m=800.0,  ident_range_m=500.0, weather_scale=_radar_scale),
}


@dataclass(frozen=True)
class SensorQuality:
    range_scale: float   # 0..1 multiplier on clear-weather range
    noise_scale: float   # >= 1 multiplier on measurement standard deviation
    pd_scale: float      # 0..1 multiplier on detection probability


def sensor_quality(sensor_type: str, weather: WeatherState) -> SensorQuality:
    spec = SENSOR_SPECS[sensor_type]
    scale = spec.weather_scale(weather, spec.ident_range_m)
    # Placeholder couplings: worse weather means larger noise and fewer detections.
    noise = 1.0 / max(scale, 1e-3)
    return SensorQuality(range_scale=scale, noise_scale=noise, pd_scale=scale ** 0.5)


def sensor_hierarchy(weather: WeatherState, sensor_types: Iterable[str] = None) -> List[str]:
    """Sensors ordered best first by effective identification range in this weather."""
    names = list(sensor_types) if sensor_types is not None else list(SENSOR_SPECS)
    return sorted(
        names,
        key=lambda s: SENSOR_SPECS[s].ident_range_m * sensor_quality(s, weather).range_scale,
        reverse=True,
    )


@dataclass(frozen=True)
class Standoff:
    max_range_m: float      # farthest distance at which this sensor can still identify the object
    recommended_m: float    # distance to aim for, with a safety margin
    confidence: float       # 0..1, how much weather leaves of the clear-weather capability
    feasible: bool          # False if the sensor cannot identify the object right now


def required_standoff(
    sensor_type: str,
    target_position: Sequence[float],
    t: float,
    weather: WeatherProvider,
) -> Standoff:
    """How close a drone carrying `sensor_type` must get to identify the target."""
    spec = SENSOR_SPECS[sensor_type]
    scale = sensor_quality(sensor_type, weather.at(target_position, t)).range_scale
    max_range = spec.ident_range_m * scale
    return Standoff(
        max_range_m=max_range,
        recommended_m=STANDOFF_MARGIN * max_range,
        confidence=scale,
        feasible=max_range >= MIN_USEFUL_RANGE_M,
    )


def standoff_by_sensor(
    sensor_types: Iterable[str],
    target_position: Sequence[float],
    t: float,
    weather: WeatherProvider,
) -> Dict[str, Standoff]:
    return {s: required_standoff(s, target_position, t, weather) for s in sensor_types}


def best_standoff(by_sensor: Dict[str, Standoff]) -> Standoff:
    """The most capable sensor wins: the longest feasible maximum range."""
    return max(by_sensor.values(), key=lambda s: s.max_range_m)
