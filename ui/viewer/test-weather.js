// Weather port check: every case of sensors/testdata/weather_cases.json (made by `python -m sensors.golden`
// from the Python reference) must give the same answer here. Run: node ui/viewer/test-weather.js
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const W = require('./weather.js');
const CAT = require('./catalog.js');

const cases = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', 'sensors', 'testdata', 'weather_cases.json'), 'utf8'));
const modules = {};
CAT.modules.forEach((m) => { modules[m.id] = m; });
let failed = 0;

function close(a, b, what) { // relative tolerance 1e-9, as agreed
  assert.ok(Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a), Math.abs(b)), what + ': ' + a + ' vs ' + b);
}
function sameEffects(got, want, what) {
  assert.deepStrictEqual(Object.keys(got).sort(), Object.keys(want).sort(), what + ' effects');
  Object.keys(want).forEach((k) => close(got[k], want[k], what + ' ' + k));
}
function test(name, fn) {
  try { fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + e.message); }
}

test('weather text: valid forms parse, invalid forms throw', () => {
  cases.parse.valid.forEach((c) => sameEffects(W.parseWeather(c.text), c.effects, c.text));
  cases.parse.invalid.forEach((t) => assert.throws(() => W.parseWeather(t), Error, 'accepted ' + JSON.stringify(t)));
});
test('sensor quality: effects multiply, strength moves the multiplier towards 1', () => {
  cases.quality.forEach((c) => {
    const q = W.sensorQuality(modules[c.module], W.activeEffects(W.conditions(c.weather, c.time_of_day)));
    const what = c.module + ' ' + c.weather + ' ' + c.time_of_day;
    close(q.range, c.range_scale, what + ' range'); close(q.noise, c.noise_scale, what + ' noise'); close(q.pd, c.pd_scale, what + ' pd');
  });
});
test('sky: sun height, night strength and day length', () => {
  cases.sky.forEach((c) => {
    const sky = W.makeSky({ date: c.date, hour: c.hour, lat: c.lat, lon: c.lon, utc_offset_h: c.utc_offset_h === null ? undefined : c.utc_offset_h, time_scale: c.time_scale });
    const what = c.date + ' ' + c.hour + ' ' + c.lat + ' t=' + c.t;
    close(W.skyElevationDeg(sky, c.t), c.elevation_deg, what + ' elevation');
    close(W.skyNightStrength(sky, c.t), c.night_strength, what + ' night');
    close(W.skyDaylightHours(sky), c.daylight_hours, what + ' daylight');
  });
});
test('events: strongest strength of each effect, by time and zone', () => {
  cases.event_weather.forEach((c) => {
    const w = W.eventWeather(W.conditions(c.base), cases.events);
    sameEffects(W.activeEffects(w.at([c.x, c.y, 0], c.t)), c.effects, c.base + ' ' + [c.x, c.y, c.t]);
  });
});
test('a detection sees the strongest strength at the sensor and at the target', () => {
  const w = W.eventWeather(W.conditions('rain:0.3'), [cases.events[0]]);
  cases.link_weather.forEach((c) => sameEffects(W.activeEffects(W.conditionsBetween(w, c.sensor, c.target, c.t)), c.effects, JSON.stringify(c)));
});
test('providerFor: a single weather is static; events or a sky are not', () => {
  assert.ok(W.providerFor({}, 'fog', null).isStatic);
  assert.ok(!W.providerFor({ weather_events: [cases.events[0]] }, 'fog', null).isStatic);
  assert.ok(!W.providerFor({}, 'fog', { date: '2026-06-21', hour: 20, lat: 45, lon: 0 }).isStatic);
  assert.throws(() => W.providerFor({}, 'snow', null), Error);
  assert.throws(() => W.makeSky({ date: '2026-06-21', hour: 20, lat: 45 }), /lon/);
});
test('sky replaces a fixed time_of_day; a fixed night counts once', () => {
  const noon = { date: '2026-06-21', hour: 12, lat: 45, lon: 0, utc_offset_h: 0 };
  const dayWithSky = W.providerFor({ time_of_day: 'night' }, 'clear', noon).provider.at([0, 0], 0);
  assert.deepStrictEqual(W.activeEffects(dayWithSky), {});
  assert.deepStrictEqual(W.activeEffects(W.providerFor({ time_of_day: 'night' }, 'night', null).provider.at([0, 0], 0)), { night: 1 });
});

// ---- the mock simulation: weather that varies is looked up per detection
const Sim = require('./sim.js');
const SCENARIOS = require('./scenarios.js');
const withEnv = (env) => {
  const sc = JSON.parse(JSON.stringify(SCENARIOS.challenge));
  sc.environment = Object.assign(sc.environment, env);
  return sc;
};
// Fix the sensor platforms in place to isolate weather physics. Autonomous
// coverage and investigation routes also respond to weather and change detections.
const sim = (weather, env, sky) => {
  const scenario = withEnv(env || {});
  const commands = scenario.friendlies.map((f) => ({ t: 0, drone_id: f.id, command: 'hold' }));
  return Sim.run({ seed: 5, mode: 'optimistic', weather, sky, loss: 0, delayMs: 0, driftMs: 0, scenario, commands });
};
const measOf = (res, from, to) => JSON.stringify(res.frames.slice(from, to).map((f) => f.meas));
const WHOLE = { weather: 'fog' }; // an event with no time or zone covers everything

test('an event over everything all run gives the same detections as that weather all run', () => {
  assert.strictEqual(measOf(sim('clear', { weather_events: [WHOLE] })), measOf(sim('fog')));
});
test('an event that starts at 60 s leaves the first minute as in clear weather', () => {
  const late = sim('clear', { weather_events: [{ weather: 'fog', t_start: 60 }] }), clear = sim('clear');
  assert.strictEqual(measOf(late, 0, 600), measOf(clear, 0, 600));
  assert.notStrictEqual(measOf(late, 600, 1200), measOf(clear, 600, 1200));
});
test('an event far from every sensor and target changes nothing', () => {
  const far = sim('clear', { weather_events: [{ weather: 'fog', zone: { x: 5000, y: 5000, radius_m: 100 } }] });
  assert.strictEqual(measOf(far), measOf(sim('clear')));
});
test('a sky at midday is like clear weather; at midnight like a fixed night', () => {
  const at = (hour) => ({ date: '2026-06-21', hour, lat: 45, lon: 0, utc_offset_h: 0, time_scale: 0 });
  assert.strictEqual(measOf(sim('clear', {}, at(12))), measOf(sim('clear')));
  assert.strictEqual(measOf(sim('clear', {}, at(0))), measOf(sim('night')));
});
test('sky overrides a scenario sky and null turns it off', () => {
  const env = { sky: { date: '2026-06-21', hour: 0, lat: 45, lon: 0, utc_offset_h: 0, time_scale: 0 } };
  assert.strictEqual(measOf(sim('clear', env)), measOf(sim('night')));
  assert.strictEqual(measOf(sim('clear', env, null)), measOf(sim('clear')));
});
test('fog and wind together are worse than either alone', () => {
  const count = (res) => res.frames.reduce((n, f) => n + f.meas.length, 0);
  assert.ok(count(sim('fog+wind')) < count(sim('fog')) && count(sim('fog+wind')) < count(sim('wind')));
});

if (failed) { console.log(failed + ' failed'); process.exit(1); }
