// Tests for jamming zones in the mock simulation. Run: node ui/viewer/test-jamming.js
const assert = require('assert');
const Sim = require('./sim.js');
const SCENARIOS = require('./scenarios.js');
const Jamming = require('./jamming.js');

const ZONE = { x: 500, y: 500, radius_m: 200, loss: 0.9, t_start: 30, t_end: 90 };
const scenario = (zones) => {
  const sc = JSON.parse(JSON.stringify(SCENARIOS.challenge));
  sc.degradations.network = Object.assign({}, sc.degradations.network, { jamming_zones: zones });
  return sc;
};
const run = (zones, mode, extra, tap) => Sim.run(Object.assign({ seed: 5, mode: mode || 'realistic', weather: 'clear', loss: 10, delayMs: 0, driftMs: 0, scenario: scenario(zones) }, extra), tap ? { tap } : undefined);
// share of messages from `node` that got through (arr is set only on delivered ones), within [from, to)
// the tap sees a message before the channel decides its fate, so read `arr` after the run
function sentBy(zones, node, mode) {
  const all = [];
  run(zones, mode, undefined, (m) => {
    if (m.header.source_id === node && ['observation', 'friendly_beacon', 'drone_state'].includes(m.type)) all.push(m);
  });
  return all;
}
function delivered(zones, node, from, to, mode) {
  const msgs = sentBy(zones, node, mode).filter((m) => m.header.t_sent >= from && m.header.t_sent < to);
  return { sent: msgs.length, rate: msgs.filter((m) => m.arr !== undefined).length / msgs.length };
}
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('zone maths: inside, outside, in time, overlapping zones take the higher value', () => {
  const zones = [ZONE, { x: 500, y: 500, radius_m: 50, loss: 0.99, rf_noise_mult: 4 }];
  assert.strictEqual(Jamming.lossAt(zones, 0.1, { x: 500, y: 600 }, 40), 0.9);
  assert.strictEqual(Jamming.lossAt(zones, 0.1, { x: 500, y: 520 }, 40), 0.99);
  assert.strictEqual(Jamming.lossAt(zones, 0.1, { x: 900, y: 900 }, 40), 0.1);
  assert.strictEqual(Jamming.lossAt(zones, 0.1, { x: 500, y: 600 }, 29.9), 0.1);
  assert.strictEqual(Jamming.lossAt(zones, 0.1, { x: 500, y: 600 }, 90), 0.1);
  assert.strictEqual(Jamming.rfNoiseMult(zones, { x: 500, y: 520 }, 40), 4);
  assert.strictEqual(Jamming.rfNoiseMult(zones, { x: 500, y: 600 }, 40), 1);
  assert.strictEqual(Jamming.lossAt([{ x: 0, y: 0, radius_m: 10, loss: 0.5 }], 0, { x: 5, y: 0 }, 1e6), 0.5); // no times = whole run
});
test('a ground sensor inside the zone loses messages at the zone rate, one outside does not', () => {
  const inZone = delivered([ZONE], 'GS2', 30, 90), clear = delivered([], 'GS2', 30, 90);
  assert.ok(Math.abs(inZone.rate - 0.1) < 0.06, 'GS2 is at (655, 460), inside: ' + inZone.rate);
  assert.ok(clear.rate > 0.8, 'no zone: ' + clear.rate);
  const outside = delivered([ZONE], 'GS1', 30, 90), baseline = delivered([], 'GS1', 30, 90);
  // Loss changes investigations and later traffic, hence consumption of the
  // shared seeded network RNG. Both links must keep their unjammed delivery rate.
  assert.ok(outside.rate > 0.8 && baseline.rate > 0.8);
});
test('zone times are respected', () => {
  assert.strictEqual(delivered([ZONE], 'GS2', 0, 30).rate, delivered([], 'GS2', 0, 30).rate);
  assert.ok(delivered([ZONE], 'GS2', 90, 120).rate > 0.8);
});
test('a drone that flies through the zone loses messages only while inside', () => {
  const here = run([]).frames[600].truth.find((o) => o.id === 'F1');
  const zone = { x: here.x, y: here.y, radius_m: 60, loss: 1 };
  let inside = 0, outside = 0, insideGot = 0, outsideGot = 0;
  const messages = [];
  const res = run([zone], 'realistic', undefined, (m) => {
    if (m.header.source_id === 'F1' && ['observation', 'friendly_beacon', 'drone_state'].includes(m.type)) messages.push(m);
  });
  messages.forEach((m) => {
    const f = res.frames[Math.round(m.header.t_sent / Sim.DT)].truth.find((o) => o.id === 'F1');
    const d = Math.hypot(f.x - here.x, f.y - here.y);
    if (d <= 55) { inside++; if (m.arr !== undefined) insideGot++; } else if (d >= 65) { outside++; if (m.arr !== undefined) outsideGot++; }
  });
  assert.ok(inside > 10 && outside > 10);
  assert.strictEqual(insideGot, 0, 'a loss of 1 inside the zone');
  assert.ok(outsideGot / outside > 0.5, 'normal outside: ' + outsideGot / outside);
});
test('RF receivers inside a zone are noisier', () => {
  const sd = (zones) => { const v = []; run(zones, 'realistic', undefined, (m) => { if (m.type === 'observation' && m.sensor_type === 'rf_receiver' && m.header.source_id === 'GS2') v.push(m.covariance[0][0]); }); return v; };
  const noisy = sd([{ x: 655, y: 460, radius_m: 80, loss: 0, rf_noise_mult: 3 }]), plain = sd([]);
  assert.ok(noisy.length && plain.length);
  assert.ok(Math.max.apply(null, noisy) > 4 * Math.max.apply(null, plain), 'bearing variance grows with the noise multiplier squared');
});
test('zones only apply in Realistic mode (they are a comms degradation)', () => {
  assert.strictEqual(delivered([ZONE], 'GS2', 30, 90, 'optimistic').rate, 1);
});
test('no zones: the run is identical to one with an empty list', () => {
  const key = (r) => JSON.stringify(r.frames.map((f) => [f.m, f.tracks.length]));
  assert.strictEqual(key(run([])), key(run(undefined)));
});

let failed = 0;
tests.forEach(([name, fn]) => { try { fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + e.message); } });
if (failed) process.exit(1);
