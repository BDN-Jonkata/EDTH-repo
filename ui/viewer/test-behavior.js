// node ui/viewer/test-behavior.js — Python reference, then integration assertions.
const test = require('node:test');
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const path = require('node:path');
const { AutomaticEstimator, DEFAULTS } = require('./friend-foe.js');
const Sim = require('./sim.js');
const root = path.resolve(__dirname, '../..');
const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const reference = JSON.parse(execFileSync(python, ['-m', 'drone_behavior.golden'], { cwd: root, maxBuffer: 8 * 1024 * 1024 }));

function same(a, b, what) {
  if (typeof b === 'number') assert.ok(Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(b)), what + ': ' + a + ' vs ' + b);
  else if (b && typeof b === 'object') {
    assert.deepEqual(Object.keys(a).sort(), Object.keys(b).sort(), what + ' keys');
    Object.keys(b).forEach((k) => same(a[k], b[k], what + '.' + k));
  } else assert.equal(a, b, what);
}

test('agreed estimator configuration matches Python exactly', () => assert.deepEqual(DEFAULTS, reference.estimator_config));
reference.cases.forEach((c) => test('Python/JS flags, scores and explanations: ' + c.name, () => {
  const est = new AutomaticEstimator(c.policy, c.config || {}, c.verified_ids);
  c.frames.forEach((f) => {
    same(est.update(f.t, f.tracks, f.beacons), f.expected, c.name + ' t=' + f.t);
    f.tracks.forEach((tr) => same(est.explain(tr.track_id), f.evidence[tr.track_id], c.name + ' ' + tr.track_id + ' t=' + f.t));
  });
}));

test('confirmed tracker contacts stay unidentified until there is behavior evidence', () => {
  const res = Sim.run({ seed: 5, mode: 'optimistic', weather: 'clear' });
  const contacts = res.frames.flatMap((f) => f.tracks.filter((t) => !t.id.startsWith('F') && t.st === 'confirmed'));
  assert.ok(contacts.some((t) => t.cls === 'suspicious' || t.cls === 'unknown'));
  assert.ok(res.frames[0].tracks.every((t) => t.cls === 'friendly'));
  assert.ok(!res.alerts.some((a) => /confirmed hostile/.test(a.text)));
  res.frames.forEach((f) => f.tracks.forEach((t) => {
    if (t.cls === 'hostile') {
      assert.ok(t.behavior.reasons.includes('responsive_pursuit') || t.behavior.retained_risk?.reasons.includes('responsive_pursuit'));
      assert.ok(t.pH >= DEFAULTS.hostile_exit);
    }
    assert.ok(Number.isFinite(t.pF) && Number.isFinite(t.pH));
  }));
});

test('offline or predicted-only measurements cannot accumulate evidence', () => {
  const est = new AutomaticEstimator();
  const tr = { track_id: 'a', t: 0, position: [1, 2, 3], velocity: [0, 0, 0], pos_sigma: 1, existence_prob: 1 };
  const first = est.update(0, [tr], []);
  for (let i = 0; i < 20; i++) assert.deepEqual(est.update(0, [tr], []), first);
  for (let i = 1; i < 100; i++) est.update(i / 10, [tr], []);
  assert.equal(est.explain('a').increment, 0);
  assert.equal(est.explain('a').observed_s, 0);
});
