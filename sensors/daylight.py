"""How dark it is, from the date, the place and the clock time.

A fixed "night from 21:00 to 05:00" is wrong: the length of the day depends on the
season and the latitude (a December evening at 50 N is dark at 17:00, a June one
is light until 22:00, and above 60 N it never gets fully dark in June). So the
input is the sun's height above the horizon, from the standard NOAA approximation
of the sun's position (accurate to a fraction of a degree, enough here).

The catalog has one `night` multiplier per sensor, for full darkness. Darkness
here is a strength from 0 to 1: 0 with the sun above the horizon, rising
linearly through twilight to 1 once the sun is `FULL_NIGHT_ELEVATION_DEG`
below it. That mapping is a placeholder; the catalog gives no twilight data.
"""

import math
from dataclasses import dataclass
from datetime import date
from typing import Optional, Tuple

FULL_NIGHT_ELEVATION_DEG = -12.0   # placeholder: the end of nautical twilight
SUNRISE_ELEVATION_DEG = -0.833     # centre of the sun on the horizon, with refraction


def _fractional_year(day_of_year: float, hour: float) -> float:
    return 2.0 * math.pi / 365.0 * (day_of_year - 1.0 + (hour - 12.0) / 24.0)


def _declination_rad(gamma: float) -> float:
    return (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
            - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
            - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))


def _equation_of_time_min(gamma: float) -> float:
    return 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                     - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))


def sun_elevation_deg(lat_deg: float, lon_deg: float, day_of_year: float, hour_local: float,
                      utc_offset_h: float) -> float:
    """Height of the sun above the horizon in degrees (negative = below it)."""
    gamma = _fractional_year(day_of_year, hour_local)
    declination = _declination_rad(gamma)
    solar_minutes = hour_local * 60.0 + _equation_of_time_min(gamma) + 4.0 * lon_deg - 60.0 * utc_offset_h
    hour_angle = math.radians(solar_minutes / 4.0 - 180.0)
    lat = math.radians(lat_deg)
    sin_elev = math.sin(lat) * math.sin(declination) + math.cos(lat) * math.cos(declination) * math.cos(hour_angle)
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_elev))))


def night_strength(elevation_deg: float) -> float:
    """0 with the sun up, 1 in full night, linear through twilight in between."""
    if elevation_deg >= 0.0:
        return 0.0
    return min(1.0, elevation_deg / FULL_NIGHT_ELEVATION_DEG)


def daylight_hours(lat_deg: float, day_of_year: float) -> float:
    """Hours from sunrise to sunset (0 in polar night, 24 in polar day)."""
    declination = _declination_rad(_fractional_year(day_of_year, 12.0))
    lat = math.radians(lat_deg)
    cos_h = ((math.sin(math.radians(SUNRISE_ELEVATION_DEG)) - math.sin(lat) * math.sin(declination))
             / (math.cos(lat) * math.cos(declination)))
    if cos_h >= 1.0:
        return 0.0
    if cos_h <= -1.0:
        return 24.0
    return 2.0 * math.degrees(math.acos(cos_h)) / 15.0


@dataclass(frozen=True)
class Sky:
    """When and where the run takes place. `hour` is the local clock time at t = 0 and
    `time_scale` how many clock seconds pass per simulated second (1 = real time), so a
    short run can still cross sunset."""

    date: str                              # "YYYY-MM-DD"
    hour: float                            # 0 <= hour < 24
    lat: float
    lon: float
    utc_offset_h: Optional[float] = None   # default: the offset that matches the longitude
    time_scale: float = 1.0

    def __post_init__(self):
        date.fromisoformat(self.date)
        if not 0.0 <= self.hour < 24.0:
            raise ValueError("hour must be from 0 up to 24")
        if not -90.0 <= self.lat <= 90.0 or not -180.0 <= self.lon <= 180.0:
            raise ValueError("lat must be within -90..90 and lon within -180..180")
        if self.time_scale < 0:
            raise ValueError("time_scale must not be negative")

    def _clock(self, t: float) -> Tuple[float, float]:
        """(day of year, hour of day) after t simulated seconds."""
        total = self.hour + t * self.time_scale / 3600.0
        day = date.fromisoformat(self.date).timetuple().tm_yday + math.floor(total / 24.0)
        return day, total % 24.0

    def elevation_deg(self, t: float = 0.0) -> float:
        day, hour = self._clock(t)
        offset = round(self.lon / 15.0) if self.utc_offset_h is None else self.utc_offset_h
        return sun_elevation_deg(self.lat, self.lon, day, hour, offset)

    def night_strength(self, t: float = 0.0) -> float:
        return night_strength(self.elevation_deg(t))

    def daylight_hours(self) -> float:
        return daylight_hours(self.lat, date.fromisoformat(self.date).timetuple().tm_yday)


def sky_from_dict(d: dict) -> Sky:
    missing = [k for k in ("date", "hour", "lat", "lon") if k not in d]
    if missing:
        raise ValueError(f"sky needs {', '.join(missing)}: the place and date decide how long the day is")
    return Sky(d["date"], d["hour"], d["lat"], d["lon"], d.get("utc_offset_h"), d.get("time_scale", 1.0))
