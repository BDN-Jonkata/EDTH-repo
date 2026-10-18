// Pose error in the mock simulation, checked on the ground sensors (drones fly differently once their tracks differ). Run: node ui/viewer/test-pose.js
const assert = require('assert');
const Sim = require('./sim.js');
const SCENARIOS = require('./scenarios.js');

const run = (sc) => Sim.run({ seed: 5, mode: 'realistic', weather: 'clear', loss: 0, delayMs: 0, driftMs: 0, scenario: sc });
const clone = () => JSON.parse(JSON.stringify(SCENARIOS.gnss_denied));
const records = (res) => res.frames.flatMap((f) => f.meas);

const off = clone(); off.degradations.pose.enabled = false;
const on = clone();
const a = records(run(off)), b = records(run(on));
const moved = {};
b.forEach((r, i) => { if (r.node.startsWith('GS') && a[i] && a[i].node === r.node && a[i].t === r.t) moved[r.node] = Math.hypot(r.sx - a[i].sx, r.sy - a[i].sy); });

assert(Object.keys(moved).length > 0, 'compared some readings');
assert(Object.values(moved).every((d) => d > 0 && d <= on.degradations.pose.position_err_m + 1e-6), 'offset within position_err_m');
console.log('pose error ok:', Object.entries(moved).map(([n, d]) => n + ' ' + d.toFixed(1) + ' m').join(', '));
