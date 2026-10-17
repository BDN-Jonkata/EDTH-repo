// An object that two RF receivers keep hearing is a transmitter, and is called hostile when the run asks for it.
// Run: node ui/viewer/test-emitters.js
const assert = require('assert');
const Sim = require('./sim.js');
const SCENARIOS = require('./scenarios.js');

const run = (scenario, extra) => Sim.run({ seed: 5, mode: 'optimistic', weather: 'clear', loss: 0, delayMs: 0, driftMs: 0, scenario, assign: {}, ...extra });
const near = (f, o) => f.tracks.filter((t) => !t.id.startsWith('F') && Math.hypot(t.x - o.x, t.y - o.y) < 40);
const frames = (res, kind) => res.frames.flatMap((f) => f.truth.filter((o) => o.kind === kind).map((o) => ({ f, o })));
const share = (res, kind, cls) => {
  const all = frames(res, kind).filter(({ f, o }) => near(f, o).length);
  return all.filter(({ f, o }) => near(f, o).some((t) => t.cls === cls)).length / Math.max(1, all.length);
};

assert.strictEqual(share(run(SCENARIOS.challenge), 'hostile', 'hostile'), 0, 'by default nothing is called hostile from an emitter alone');
console.log('ok   off by default: no hostile label from RF alone');

const on = run(SCENARIOS.medium, { emitterHostile: true });
assert.ok(share(on, 'hostile', 'hostile') > 0.3, 'most tracked hostile time is called hostile');
console.log('ok   on: tracks on real hostiles are called hostile ' + (100 * share(on, 'hostile', 'hostile')).toFixed(0) + ' % of the time');

const dusk = run(SCENARIOS.dusk, { emitterHostile: true });
assert.ok(share(dusk, 'clutter', 'hostile') < 0.15, 'birds and vehicles are rarely called hostile');
console.log('ok   on: birds and vehicles called hostile ' + (100 * share(dusk, 'clutter', 'hostile')).toFixed(0) + ' % of the time');
console.log('all 3 passed');
