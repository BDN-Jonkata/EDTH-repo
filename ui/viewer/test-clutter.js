// Tests for clutter objects (birds, vehicles) in the mock simulation. Run: node ui/viewer/test-clutter.js
const assert = require('assert');
const Sim = require('./sim.js');
const SCENARIOS = require('./scenarios.js');

const LOUD = { eo: 1.3, thermal: 1.5, acoustic: 1.5, rf: 0, radar: 1.5 };
const UNSEEN = { eo: 0, thermal: 0, acoustic: 0, rf: 0, radar: 0 };
// a vehicle driving east past the GS2 radar (655, 460), same shape as the generator's clutter objects
const vehicle = (signature) => ({
  id: 'V1', role: 'clutter', type: 'vehicle', motion: 'straight', altitude_m: 1.5, wobble_m: 0, phase: 0,
  waypoints: [[0, 100, 420], [120, 950, 420]], signature, emits: false,
});
const withClutter = (clutter) => Object.assign(JSON.parse(JSON.stringify(SCENARIOS.challenge)), { clutter });
const run = (scenario) => Sim.run({ seed: 5, mode: 'optimistic', weather: 'clear', loss: 0, delayMs: 0, driftMs: 0, scenario });
// radar detections (range and bearing) within 25 m of the object that no other object or false alarm explains
function radarHitsOn(res, id) {
  let n = 0;
  res.frames.forEach((f) => {
    const o = f.truth.find((q) => q.id === id);
    if (!o) return;
    f.meas.forEach((z) => {
      if (z.m !== 'rangeaz' || z.clutter) return;
      const x = z.sx + z.r * Math.cos(z.b), y = z.sy + z.r * Math.sin(z.b);
      const other = f.truth.some((q) => q.id !== id && Math.hypot(q.x - x, q.y - y) < 40);
      if (!other && Math.hypot(x - o.x, y - o.y) < 25) n++;
    });
  });
  return n;
}
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('clutter is in the run truth as kind clutter and the sensors see it', () => {
  const res = run(withClutter([vehicle(LOUD)]));
  const v1 = res.frames[600].truth.find((o) => o.id === 'V1');
  assert.ok(v1 && v1.kind === 'clutter' && v1.type === 'vehicle');
  assert.ok(radarHitsOn(res, 'V1') > 20, 'radar hits: ' + radarHitsOn(res, 'V1'));
  assert.strictEqual(res.frames[600].m.tru, run(SCENARIOS.challenge).frames[600].m.tru, 'clutter is not counted as a true hostile');
});

test('a signature of 0 is never detected', () => {
  assert.strictEqual(radarHitsOn(run(withClutter([vehicle(UNSEEN)])), 'V1'), 0);
});

test('a hostile track on clutter is counted as a clutter false alarm', () => {
  const res = run(withClutter([vehicle(LOUD)]));
  assert.ok(res.summary.cfa >= 1, 'cfa ' + res.summary.cfa);
  assert.ok(res.alerts.some((a) => /Clutter vehicle V1 tracked as hostile/.test(a.text)));
});

test('without clutter the summary has no cfa and the truth no clutter', () => {
  const res = run(SCENARIOS.challenge);
  assert.strictEqual(res.summary.cfa, undefined);
  assert.ok(res.frames.every((f) => f.truth.every((o) => o.kind !== 'clutter')));
});

test('same seed, same run', () => {
  const a = run(withClutter([vehicle(LOUD)])), b = run(withClutter([vehicle(LOUD)]));
  assert.deepStrictEqual(a.summary, b.summary);
  assert.deepStrictEqual(a.alerts, b.alerts);
});

let failed = 0;
tests.forEach(([name, fn]) => {
  try { fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + e.message); }
});
process.exit(failed ? 1 : 0);
