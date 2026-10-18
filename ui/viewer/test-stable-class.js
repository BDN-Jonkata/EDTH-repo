// holdHostile and tentativeNotHostile: a hostile does not flicker to suspicious, a tentative track is not called hostile.
// Both are run parameters (the viewer sets them with ?stable=1); the tests and the default run leave them off.
// node ui/viewer/test-stable-class.js
const test = require('node:test');
const assert = require('node:assert/strict');
const Sim = require('./sim.js');
const mixed = require('./scenarios.js').mixed;

const options = (flags) => Object.assign({ scenario: mixed, emitterHostile: true, learnIntent: true, objectClass: true, repeatObs: 'auto',
  seed: mixed.seed, mode: 'optimistic', weather: mixed.environment.weather, loss: 0, delayMs: 0, driftMs: 0 }, flags);
const base = Sim.run(options({}));
const held = Sim.run(options({ holdHostile: true }));
const stable = Sim.run(options({ holdHostile: true, tentativeNotHostile: true }));

function flickers(run) {
  const last = {}; let n = 0;
  run.frames.forEach((f) => f.tracks.forEach((tr) => {
    const p = last[tr.id];
    if (p && ((p === 'hostile' && tr.cls === 'suspicious') || (p === 'suspicious' && tr.cls === 'hostile'))) n += 1;
    last[tr.id] = tr.cls;
  }));
  return n;
}
const tentativeHostile = (run) => run.frames.reduce((n, f) => n + f.tracks.filter((tr) => tr.st === 'tentative' && tr.cls === 'hostile').length, 0);

test('without the flags a hostile does flicker and a tentative track is called hostile (so the other tests mean something)', () => {
  assert.ok(flickers(base) >= 5, 'flickers: ' + flickers(base));
  assert.ok(tentativeHostile(base) > 0);
});

test('holdHostile removes most of the flicker between hostile and suspicious', () => {
  assert.ok(flickers(held) <= flickers(base) / 3, flickers(held) + ' against ' + flickers(base));
});

test('tentativeNotHostile means no tentative track is ever shown as hostile', () => {
  assert.equal(tentativeHostile(stable), 0);
});

test('with both, more of the hostile tracks sit on a real hostile than without', () => {
  const share = (run) => {
    let hostile = 0, right = 0;
    run.frames.filter((f) => f.t >= 10).forEach((f) => f.tracks.filter((tr) => tr.cls === 'hostile').forEach((tr) => {
      hostile += 1;
      if (f.truth.some((o) => o.kind === 'hostile' && Math.hypot(o.x - tr.x, o.y - tr.y) <= 60)) right += 1;
    }));
    return right / hostile;
  };
  assert.ok(share(stable) > share(base), share(stable).toFixed(2) + ' against ' + share(base).toFixed(2));
});

test('the flags are off by default: leaving them out equals setting them false', () => {
  const off = Sim.run(options({ holdHostile: false, tentativeNotHostile: false }));
  assert.deepEqual(off.summary, base.summary);
  assert.equal(off.frames.length, base.frames.length);
});
