// Navigation estimator on synthetic readings. Run: node ui/viewer/test-navigation.js
const assert = require('assert');
const Navigation = require('./navigation.js');

const D2R = Math.PI / 180, compass = (r) => ((90 - r / D2R) % 360 + 360) % 360;
const truth = { x: 300, y: 400 }, err = { dx: 12, dy: -8, dh: 4 * D2R };
const landmarks = [{ id: 'F1', x: 450, y: 420, sd: 3 }, { id: 'F2', x: 250, y: 600, sd: 3 }, { id: 'F3', x: 520, y: 250, sd: 3 }];
let seed = 1; const noise = (s) => { seed = (seed * 16807) % 2147483647; return (seed / 2147483647 - 0.5) * 2 * s; };

function reading(L, kind) {
  const dx = L.x - truth.x, dy = L.y - truth.y;
  const rec = { node: 'GS1', m: kind, sx: truth.x, sy: truth.y, b: Math.atan2(dy, dx) + noise(0.01), sigB: 0.01, rmax: 600, fields: { azimuth_deg: 0 } };
  if (kind === 'rangeaz') { rec.r = Math.hypot(dx, dy) + noise(2); rec.sigR = 2; }
  Navigation.shiftRecord(rec, err.dx, err.dy, err.dh, compass); // what the node reports with a wrong pose
  return rec;
}

const est = Navigation.create(['GS1']);
for (let i = 0; i < 60; i++) Navigation.observe(est, reading(landmarks[i % 3], 'rangeaz'), landmarks);
const e = est.GS1.e;
assert(Math.hypot(e[0] - err.dx, e[1] - err.dy) < 2, 'position offset learned within 2 m: ' + e);
assert(Math.abs(e[2] - err.dh) < 0.5 * D2R, 'heading offset learned within 0.5 degrees');

const rec = reading(landmarks[0], 'rangeaz');
Navigation.correct(est, rec, compass);
assert(Math.hypot(rec.sx - truth.x, rec.sy - truth.y) < 2, 'a corrected reading is back near the true pose');

const idle = Navigation.create(['GS1']), clean = { node: 'GS1', m: 'rangeaz', sx: 1, sy: 2, b: 0.5, r: 100, sigB: 0.01, sigR: 2, fields: {} };
Navigation.observe(idle, clean, []);
assert.deepStrictEqual([clean.sx, clean.sy, clean.b], [1, 2, 0.5], 'with no landmark nothing is learned or changed');
console.log('navigation ok: offset', e.slice(0, 2).map((v) => v.toFixed(1)), 'm, heading', (e[2] / D2R).toFixed(1), 'deg');
