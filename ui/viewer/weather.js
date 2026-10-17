/*
 * Weather for the mock simulation: several anomalies at once, anomalies that come and go, and
 * a night strength from the sun's height. A port of sensors/weather.py, sensors/daylight.py and
 * sensors/quality.py (the Python code is the reference). test-weather.js checks every case in
 * sensors/testdata/weather_cases.json, which `python -m sensors.golden` generates from it.
 *
 * Conditions are { weather: 'fog:0.5+wind', timeOfDay: 'day' | 'night' }. A provider has
 * at(position, t) -> Conditions.
 */
(function (global) {
  const EFFECTS = ['fog', 'rain', 'wind', 'night']; // the catalog's weather_effects keys
  const MIN_NIGHT_STRENGTH = 0.01; // below this the sky counts as light
  const FULL_NIGHT_ELEVATION_DEG = -12; // placeholder, as in daylight.py
  const SUNRISE_ELEVATION_DEG = -0.833;
  const NO_EFFECT = { range_mult: 1, noise_mult: 1, pd_mult: 1 };

  // ------------------------------------------------------------------ the weather text
  function parseStrength(text, whole) {
    if (text === '') return 1;
    const v = Number(text);
    if (Number.isNaN(v)) throw new Error('strength must be a number in "' + whole + '"');
    if (!(v > 0 && v <= 1)) throw new Error('strength must be above 0 and at most 1 in "' + whole + '"');
    return v;
  }
  // 'fog:0.5+wind' -> { fog: 0.5, wind: 1 }; 'clear' -> {}
  function parseWeather(text) {
    if (text === 'clear') return {};
    const effects = {};
    text.split('+').forEach((part) => {
      const cut = part.indexOf(':'), name = cut < 0 ? part : part.slice(0, cut);
      if (EFFECTS.indexOf(name) < 0) throw new Error('weather must be clear or ' + EFFECTS.join('+') + ', got "' + part + '" in "' + text + '"');
      if (name in effects) throw new Error('"' + name + '" appears twice in "' + text + '"');
      effects[name] = parseStrength(cut < 0 ? '' : part.slice(cut + 1), text);
    });
    return effects;
  }
  // python's {s:g}: six significant digits
  const roundG = (s) => Number(s.toPrecision(6));
  function formatWeather(effects) {
    const names = Object.keys(effects).sort();
    if (!names.length) return 'clear';
    return names.map((n) => (effects[n] === 1 ? n : n + ':' + roundG(effects[n]))).join('+');
  }
  // the catalog effects that apply, with their strength; a fixed night counts once
  function activeEffects(cond) {
    const effects = parseWeather(cond.weather);
    if (cond.timeOfDay === 'night') effects.night = 1;
    return effects;
  }
  const conditions = (weather, timeOfDay) => ({ weather, timeOfDay: timeOfDay || 'day' });

  // ------------------------------------------------------------------ sensor quality
  const atStrength = (mult, s) => (s === 1 ? mult : 1 + s * (mult - 1));
  // combined effect of every active anomaly: they multiply (worst case)
  function sensorQuality(module, effects) {
    const q = { range: 1, noise: 1, pd: 1 };
    Object.keys(effects).forEach((name) => {
      const e = (module.weather_effects && module.weather_effects[name]) || NO_EFFECT, s = effects[name];
      q.range *= atStrength(e.range_mult, s);
      q.noise *= atStrength(e.noise_mult, s);
      q.pd *= atStrength(e.pd_mult, s);
    });
    return q;
  }

  // ------------------------------------------------------------------ the sun
  const rad = (d) => d * Math.PI / 180;
  const deg = (r) => r * 180 / Math.PI;
  const fractionalYear = (day, hour) => 2 * Math.PI / 365 * (day - 1 + (hour - 12) / 24);
  function declination(g) {
    return 0.006918 - 0.399912 * Math.cos(g) + 0.070257 * Math.sin(g) - 0.006758 * Math.cos(2 * g) +
      0.000907 * Math.sin(2 * g) - 0.002697 * Math.cos(3 * g) + 0.00148 * Math.sin(3 * g);
  }
  function equationOfTimeMin(g) {
    return 229.18 * (0.000075 + 0.001868 * Math.cos(g) - 0.032077 * Math.sin(g) - 0.014615 * Math.cos(2 * g) - 0.040849 * Math.sin(2 * g));
  }
  function sunElevationDeg(lat, lon, day, hour, utcOffset) {
    const g = fractionalYear(day, hour), dec = declination(g);
    const solarMinutes = hour * 60 + equationOfTimeMin(g) + 4 * lon - 60 * utcOffset;
    const ha = rad(solarMinutes / 4 - 180), la = rad(lat);
    const sinElev = Math.sin(la) * Math.sin(dec) + Math.cos(la) * Math.cos(dec) * Math.cos(ha);
    return deg(Math.asin(Math.max(-1, Math.min(1, sinElev))));
  }
  const nightStrengthAt = (elevation) => (elevation >= 0 ? 0 : Math.min(1, elevation / FULL_NIGHT_ELEVATION_DEG));
  function daylightHours(lat, day) {
    const dec = declination(fractionalYear(day, 12)), la = rad(lat);
    const cosH = (Math.sin(rad(SUNRISE_ELEVATION_DEG)) - Math.sin(la) * Math.sin(dec)) / (Math.cos(la) * Math.cos(dec));
    if (cosH >= 1) return 0;
    if (cosH <= -1) return 24;
    return 2 * deg(Math.acos(cosH)) / 15;
  }
  // day of the year of 'YYYY-MM-DD' (1 = 1 January)
  function dayOfYear(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
    if (!m) throw new Error('sky.date must be YYYY-MM-DD');
    const d = Date.UTC(+m[1], +m[2] - 1, +m[3]);
    if (new Date(d).getUTCDate() !== +m[3]) throw new Error('sky.date is not a real date');
    return Math.round((d - Date.UTC(+m[1], 0, 1)) / 86400000) + 1;
  }
  // python's round(): halves go to the even number
  function roundHalfEven(x) {
    const r = Math.round(x);
    return Math.abs(x % 1) === 0.5 && r % 2 !== 0 ? r - 1 : r;
  }

  // when and where: { date, hour, lat, lon, utc_offset_h?, time_scale? }
  function makeSky(d) {
    const missing = ['date', 'hour', 'lat', 'lon'].filter((k) => d[k] === undefined || d[k] === null);
    if (missing.length) throw new Error('sky needs ' + missing.join(', ') + ': the place and date decide how long the day is');
    const sky = { date: d.date, hour: d.hour, lat: d.lat, lon: d.lon, utcOffset: d.utc_offset_h === undefined ? null : d.utc_offset_h, timeScale: d.time_scale === undefined ? 1 : d.time_scale };
    dayOfYear(sky.date);
    if (!(sky.hour >= 0 && sky.hour < 24)) throw new Error('sky.hour must be from 0 up to 24');
    if (!(sky.lat >= -90 && sky.lat <= 90 && sky.lon >= -180 && sky.lon <= 180)) throw new Error('sky.lat must be within -90..90 and sky.lon within -180..180');
    if (!(sky.timeScale >= 0)) throw new Error('sky.time_scale must not be negative');
    return sky;
  }
  function skyElevationDeg(sky, t) {
    const total = sky.hour + t * sky.timeScale / 3600;
    const day = dayOfYear(sky.date) + Math.floor(total / 24), hour = ((total % 24) + 24) % 24;
    const offset = sky.utcOffset === null ? roundHalfEven(sky.lon / 15) : sky.utcOffset;
    return sunElevationDeg(sky.lat, sky.lon, day, hour, offset);
  }
  const skyNightStrength = (sky, t) => nightStrengthAt(skyElevationDeg(sky, t));
  const skyDaylightHours = (sky) => daylightHours(sky.lat, dayOfYear(sky.date));
  // clock hour at which the sun crosses the horizon on the sky's date, for the hour slider
  function sunTimes(sky) {
    const out = { sunrise: null, sunset: null }, step = 1 / 12;
    let prev = null;
    for (let h = 0; h <= 24 + 1e-9; h += step) {
      const e = sunElevationDeg(sky.lat, sky.lon, dayOfYear(sky.date), Math.min(h, 23.999), sky.utcOffset === null ? roundHalfEven(sky.lon / 15) : sky.utcOffset);
      if (prev !== null && prev < 0 && e >= 0 && out.sunrise === null) out.sunrise = h;
      if (prev !== null && prev >= 0 && e < 0 && out.sunset === null) out.sunset = h;
      prev = e;
    }
    return out;
  }

  // ------------------------------------------------------------------ providers
  const uniformWeather = (base) => ({ at: () => base });
  function eventCovers(e, pos, t) {
    if (!(t >= (e.t_start || 0) && t < (e.t_end === undefined ? Infinity : e.t_end))) return false;
    return !e.zone || Math.hypot(pos[0] - e.zone.x, pos[1] - e.zone.y) <= e.zone.radius_m;
  }
  // base conditions plus anomalies that come and go; overlapping ones all apply, the strongest strength of each wins
  function eventWeather(base, events) {
    return {
      at(pos, t) {
        const effects = parseWeather(base.weather);
        events.forEach((e) => {
          if (!eventCovers(e, pos, t)) return;
          const add = parseWeather(e.weather);
          Object.keys(add).forEach((n) => { effects[n] = Math.max(effects[n] || 0, add[n]); });
        });
        return conditions(formatWeather(effects), base.timeOfDay);
      },
    };
  }
  // another provider's weather plus how dark it is at that moment; the sky replaces time_of_day
  function skyWeather(inner, sky) {
    return {
      at(pos, t) {
        const c = inner.at(pos, t), strength = skyNightStrength(sky, t);
        if (strength < MIN_NIGHT_STRENGTH) return conditions(c.weather);
        const effects = parseWeather(c.weather);
        effects.night = Math.max(effects.night || 0, strength);
        return conditions(formatWeather(effects));
      },
    };
  }
  // the strongest strength of each effect at the sensor and at the target (looked up per detection)
  function conditionsBetween(provider, sensorPos, targetPos, t) {
    const effects = activeEffects(provider.at(sensorPos, t)), far = activeEffects(provider.at(targetPos, t));
    Object.keys(far).forEach((n) => { effects[n] = Math.max(effects[n] || 0, far[n]); });
    return conditions(formatWeather(effects));
  }
  // what a scenario's environment (plus the run's own weather text and sky) asks for
  function providerFor(env, weatherText, sky) {
    const skyObj = sky ? makeSky(sky) : null;
    const base = conditions(weatherText, skyObj ? 'day' : (env.time_of_day || 'day'));
    parseWeather(weatherText);
    const events = env.weather_events || [];
    const inner = events.length ? eventWeather(base, events) : uniformWeather(base);
    return { provider: skyObj ? skyWeather(inner, skyObj) : inner, isStatic: !events.length && !skyObj, base };
  }

  const api = {
    EFFECTS, parseWeather, formatWeather, activeEffects, conditions, sensorQuality, makeSky, skyElevationDeg, skyNightStrength,
    skyDaylightHours, sunTimes, eventWeather, skyWeather, uniformWeather, conditionsBetween, providerFor,
  };
  global.Weather = api;
  if (typeof module !== 'undefined') module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
