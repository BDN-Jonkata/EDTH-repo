"""Weather conditions as the scenario describes them.

`scenario.json` has `environment.weather` (clear, fog, rain, wind, night) and
`environment.time_of_day` (day, night). The catalog gives every sensor module a
multiplier for each of fog, rain, wind and night (`weather_effects`), so these
conditions only name which effects are active.

A provider answers "what are the conditions at this position and time", so
weather that varies by place or time can replace the uniform case later
without changing callers.
"""

from dataclasses import dataclass
from typing import Protocol, Sequence, Tuple

WEATHERS = ("clear", "fog", "rain", "wind", "night")
TIMES_OF_DAY = ("day", "night")


@dataclass(frozen=True)
class Conditions:
    weather: str = "clear"
    time_of_day: str = "day"

    def __post_init__(self):
        if self.weather not in WEATHERS:
            raise ValueError(f"weather must be one of {WEATHERS}, got {self.weather!r}")
        if self.time_of_day not in TIMES_OF_DAY:
            raise ValueError(f"time_of_day must be one of {TIMES_OF_DAY}, got {self.time_of_day!r}")

    def active_effects(self) -> Tuple[str, ...]:
        """Catalog `weather_effects` keys that apply. Night counts once, however it is set."""
        effects = [] if self.weather == "clear" else [self.weather]
        if self.time_of_day == "night" and "night" not in effects:
            effects.append("night")
        return tuple(effects)


PRESETS = {
    "clear": Conditions(),
    "fog": Conditions("fog"),
    "rain": Conditions("rain"),
    "wind": Conditions("wind"),
    "night": Conditions(time_of_day="night"),
    "fog_night": Conditions("fog", "night"),
}


class WeatherProvider(Protocol):
    def at(self, position: Sequence[float], t: float) -> Conditions: ...


@dataclass(frozen=True)
class UniformWeather:
    """Same conditions everywhere, all the time."""

    conditions: Conditions = Conditions()

    def at(self, position: Sequence[float], t: float) -> Conditions:
        return self.conditions


def weather_from_scenario(scenario: dict) -> UniformWeather:
    env = scenario["environment"]
    return UniformWeather(Conditions(env["weather"], env.get("time_of_day", "day")))
