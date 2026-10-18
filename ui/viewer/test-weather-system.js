// The whole system in bad weather: it runs, keeps tracking, and does not fall apart against clear weather.
// Run: node ui/viewer/test-weather-system.js   (the full table: node ui/viewer/weather-sweep.js)
const assert = require('assert');
const Sim = require('./sim.js');
const SCENARIOS = require('./scenarios.js');

const s = SCENARIOS.mixed;
const run = (weather) => Sim.run({ seed: s.seed, mode: 'realistic', weather, loss: 30, delayMs: 0, driftMs: 0, scenario: s, assign: {}, emitterHostile: true, learnIntent: true, objectClass: true, repeatObs: 'auto' }, { lite: true });
const clear = run('clear').summary;
for (const weather of ['rain+night', 'fog+night', 'fog+rain+wind+night']) {
  const r = run(weather).summary;
  assert.ok(Number.isFinite(r.rmse) && r.trackedFraction > 0.3, weather + ': some of the hostiles are still tracked (' + (r.trackedFraction || 0).toFixed(2) + ')');
  assert.ok(r.declare.declared >= 2, weather + ': most hostiles are still called hostile (' + r.declare.declared + ' of ' + r.declare.hostiles + ')');
  assert.ok(r.trackedFraction >= 0.4 * clear.trackedFraction, weather + ': tracking does not collapse against clear weather');
  console.log('ok   ' + weather + ': tracked ' + r.trackedFraction.toFixed(2) + ' (clear ' + clear.trackedFraction.toFixed(2) + '), declared ' + r.declare.declared + ' of ' + r.declare.hostiles);
}
console.log('all passed');
