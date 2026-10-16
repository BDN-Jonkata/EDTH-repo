"""Weather state and providers.

Weather is described by a few physical quantities. A provider answers
"what is the weather at this position and time", so spatially or
temporally varying weather can replace the uniform case later without
changing callers.
"""

from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True)
class WeatherState:
    wind_mps: float = 0.0            # wind speed, m/s
    visibility_m: float = 10_000.0   # meteorological visibility (fog/haze), m
    rain_mm_h: float = 0.0           # rain rate, mm/h
    light: float = 1.0               # 1 = full daylight, 0 = night


CLEAR = WeatherState()
FOG = WeatherState(wind_mps=1.0, visibility_m=80.0, light=0.7)
RAIN = WeatherState(wind_mps=6.0, visibility_m=2_000.0, rain_mm_h=12.0, light=0.6)
WIND = WeatherState(wind_mps=14.0)
NIGHT = WeatherState(light=0.05)
STORM = WeatherState(wind_mps=18.0, visibility_m=500.0, rain_mm_h=30.0, light=0.3)

PRESETS = {
    "clear": CLEAR,
    "fog": FOG,
    "rain": RAIN,
    "wind": WIND,
    "night": NIGHT,
    "storm": STORM,
}


class WeatherProvider(Protocol):
    def at(self, position: Sequence[float], t: float) -> WeatherState: ...


@dataclass(frozen=True)
class UniformWeather:
    """Same weather everywhere, all the time."""

    state: WeatherState = CLEAR

    def at(self, position: Sequence[float], t: float) -> WeatherState:
        return self.state
