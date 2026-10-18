// The radar's return tells size: birds read small, vehicles large, drones neither, and a hostile is not called on a bird or a vehicle.
// Run: node ui/viewer/test-size.js
const assert = require('assert');
const Sim = require('./sim.js');
const SCENARIOS = require('./scenarios.js');

const s = SCENARIOS.mixed, role = {};
s.targets.forEach((t) => { role[t.id] = t.role; });
s.clutter.forEach((o) => { role[o.id] = o.type; });
const res = Sim.run({ seed: s.seed, mode: 'realistic', weather: 'clear', loss: 30, delayMs: 0, driftMs: 0, scenario: s, assign: {}, emitterHostile: true, learnIntent: true, objectClass: true });
const n = {};
res.frames.forEach((f) => f.truth.forEach((o) => {
  if (!role[o.id]) return;
  const t = f.tracks.find((q) => !q.id.startsWith('F') && (q.st !== 'tentative' || q.once) && Math.hypot(q.x - o.x, q.y - o.y) < 40);
  if (!t) return;
  const r = n[role[o.id]] || (n[role[o.id]] = { n: 0, small: 0, large: 0, hostile: 0, object: 0 });
  r.n++; if (t.size === 'small') r.small++; if (t.size === 'large') r.large++; if (t.cls === 'hostile') r.hostile++; if (t.cls === 'object') r.object++;
}));
const share = (r, k) => n[r][k] / n[r].n;
const droneFrames = n.hostile.n + n.benign.n, misread = n.hostile.small + n.hostile.large + n.benign.small + n.benign.large;
assert.ok(misread / droneFrames < 0.01, 'a drone is almost never read as small or large (' + misread + ' of ' + droneFrames + ' frames)');
assert.ok(share('bird', 'small') > 0.3, 'birds read small');
assert.ok(share('vehicle', 'large') > 0.3, 'vehicles read large');
assert.ok(share('bird', 'hostile') < 0.5, 'a bird is not mostly called hostile');
assert.ok(share('bird', 'object') > 0.3 && share('vehicle', 'object') > 0.3, 'birds and vehicles are mostly objects');
assert.ok((n.hostile.object + n.benign.object) / droneFrames < 0.01, 'a drone is almost never called an object');
console.log('ok   birds called object ' + (100 * share('bird', 'object')).toFixed(0) + ' %, vehicles ' + (100 * share('vehicle', 'object')).toFixed(0) + ' %');
console.log('ok   mixed: birds small ' + (100 * share('bird', 'small')).toFixed(0) + ' %, vehicles large ' + (100 * share('vehicle', 'large')).toFixed(0) + ' %, drones misread in ' + (100 * misread / droneFrames).toFixed(1) + ' % of frames; birds called hostile ' + (100 * share('bird', 'hostile')).toFixed(0) + ' %');
console.log('all passed');
