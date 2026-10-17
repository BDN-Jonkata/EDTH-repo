"""Weather conditions: one anomaly, several at once, and anomalies that come and go.

The catalog gives every sensor module a multiplier for each of fog, rain, wind
and night (`weather_effects`). Conditions only name which of those are active
and how strongly:

    "clear"            nothing
    "fog"              one anomaly at full strength
    "fog:0.5"          half strength: the multiplier moves half way towards 1
    "fog+wind"         several at once (their effects multiply, see quality.py)
    "rain:0.6+wind"    several, with their own strengths

`environment.time_of_day` = night adds the night effect at full strength; the better
input is `environment.sky` (date, clock time, latitude, longitude), which gives a
darkness from 0 to 1 that follows the season and the twilight. A provider answers
"what are the conditions at this position and time", so a fog bank that rolls
in at t = 40 s over one part of the map is a `WeatherEvent` on top of the base
weather. `scenario.json` today holds a single value in `environment.weather`;
combinations and `environment.weather_events` are proposed (docs/data-formats.md).
"""

import math
from dataclasses import dataclass
from typing import Dict, Optional, Protocol, Sequence, Tuple

from sensors.daylight import Sky, sky_from_dict

EFFECTS = ("fog", "rain", "wind", "night")   # the catalog's `weather_effects` keys
TIMES_OF_DAY = ("day", "night")


def parse_weather(text: str) -> Dict[str, float]:
    """'fog:0.5+wind' -> {'fog': 0.5, 'wind': 1.0}. 'clear' -> {}."""
    if text == "clear":
        return {}
    effects: Dict[str, float] = {}
    for part in text.split("+"):
        name, _, strength = part.partition(":")
        if name not in EFFECTS:
            raise ValueError(f"weather must be clear or {'+'.join(EFFECTS)}, got {part!r} in {text!r}")
        if name in effects:
            raise ValueError(f"{name!r} appears twice in {text!r}")
        effects[name] = _strength(strength, text)
    return effects


def _strength(text: str, whole: str) -> float:
    if not text:
        return 1.0
    try:
        value = float(text)
    except ValueError:
        raise ValueError(f"strength must be a number in {whole!r}") from None
    if not 0.0 < value <= 1.0:
        raise ValueError(f"strength must be above 0 and at most 1 in {whole!r}")
    return value


def format_weather(effects: Dict[str, float]) -> str:
    if not effects:
        return "clear"
    return "+".join(n if s == 1.0 else f"{n}:{s:g}" for n, s in sorted(effects.items()))


@dataclass(frozen=True)
class Conditions:
    weather: str = "clear"
    time_of_day: str = "day"

    def __post_init__(self):
        parse_weather(self.weather)
        if self.time_of_day not in TIMES_OF_DAY:
            raise ValueError(f"time_of_day must be one of {TIMES_OF_DAY}, got {self.time_of_day!r}")

    def active_effects(self) -> Dict[str, float]:
        """Catalog `weather_effects` keys that apply, with their strength. Night counts once."""
        effects = parse_weather(self.weather)
        if self.time_of_day == "night":
            effects["night"] = 1.0
        return effects


PRESETS = {
    "clear": Conditions(),
    "fog": Conditions("fog"),
    "rain": Conditions("rain"),
    "wind": Conditions("wind"),
    "night": Conditions(time_of_day="night"),
    "fog_night": Conditions("fog", "night"),
    "storm": Conditions("rain+wind"),
    "fog_rain": Conditions("fog+rain"),
    "fog_wind": Conditions("fog+wind"),
    "storm_night": Conditions("rain+wind", "night"),
    "worst": Conditions("fog+rain+wind", "night"),
}


class WeatherProvider(Protocol):
    def at(self, position: Sequence[float], t: float) -> Conditions: ...


@dataclass(frozen=True)
class UniformWeather:
    """Same conditions everywhere, all the time."""

    conditions: Conditions = Conditions()

    def at(self, position: Sequence[float], t: float) -> Conditions:
        return self.conditions


@dataclass(frozen=True)
class WeatherEvent:
    """An anomaly that starts, ends, and optionally covers only a circle of the map."""

    weather: str
    t_start: float = 0.0
    t_end: float = math.inf
    zone: Optional[Tuple[float, float, float]] = None   # x, y, radius in metres

    def __post_init__(self):
        parse_weather(self.weather)
        if self.t_end <= self.t_start:
            raise ValueError("a weather event must end after it starts")

    def covers(self, position: Sequence[float], t: float) -> bool:
        if not self.t_start <= t < self.t_end:
            return False
        if self.zone is None:
            return True
        x, y, radius = self.zone
        return math.hypot(position[0] - x, position[1] - y) <= radius


@dataclass(frozen=True)
class EventWeather:
    """Base conditions plus anomalies that come and go. Overlapping ones all apply, the
    strongest strength of each effect wins."""

    base: Conditions = Conditions()
    events: Tuple[WeatherEvent, ...] = ()

    def at(self, position: Sequence[float], t: float) -> Conditions:
        effects = parse_weather(self.base.weather)
        for event in self.events:
            if event.covers(position, t):
                for name, strength in parse_weather(event.weather).items():
                    effects[name] = max(effects.get(name, 0.0), strength)
        return Conditions(format_weather(effects), self.base.time_of_day)


MIN_NIGHT_STRENGTH = 0.01   # below this the sky counts as light


@dataclass(frozen=True)
class SkyWeather:
    """Another provider's weather plus how dark it is at that moment, from the date, place and clock
    time (sensors/daylight.py). The sky replaces `time_of_day`, so twilight and the season count."""

    inner: WeatherProvider
    sky: Sky

    def at(self, position: Sequence[float], t: float) -> Conditions:
        conditions = self.inner.at(position, t)
        strength = self.sky.night_strength(t)
        if strength < MIN_NIGHT_STRENGTH:
            return Conditions(conditions.weather, "day")
        effects = parse_weather(conditions.weather)
        effects["night"] = max(effects.get("night", 0.0), strength)
        return Conditions(format_weather(effects), "day")


def _event_from_dict(e: dict) -> WeatherEvent:
    zone = e.get("zone")
    return WeatherEvent(
        e["weather"],
        e.get("t_start", 0.0),
        e.get("t_end", math.inf),
        (zone["x"], zone["y"], zone["radius_m"]) if zone else None,
    )


def weather_from_scenario(scenario: dict):
    """`environment.weather` / `time_of_day`, plus the proposed `environment.weather_events` and
    `environment.sky` (date, hour, place). When there is a sky, it decides how dark it is and
    `time_of_day` is ignored."""
    env = scenario["environment"]
    sky = sky_from_dict(env["sky"]) if "sky" in env else None
    base = Conditions(env["weather"], "day" if sky else env.get("time_of_day", "day"))
    events = tuple(_event_from_dict(e) for e in env.get("weather_events", []))
    provider = EventWeather(base, events) if events else UniformWeather(base)
    return SkyWeather(provider, sky) if sky else provider
