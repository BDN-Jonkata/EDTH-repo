// End-to-end decisions from native noisy sensors, beyond Python/JS parity.
// Run: node ui/viewer/test-assessments.js
const test = require('node:test');
const assert = require('node:assert/strict');
const Sim = require('./sim.js');
const { busy } = require('./scenarios.js');
const labels = ['friendly', 'hostile', 'peaceful', 'suspicious', 'unknown'];
const params = { seed: busy.seed, mode: 'optimistic', weather: 'clear', scenario: busy };
const demo = Sim.run(params);

// Evaluation only: unique nearest truth within the scorer's 40 m false-alarm
// gate. Neither this association nor the scenario roles enter the estimator.
function associated(frame, track) {
  const candidates = frame.truth.filter((o) => Math.hypot(o.x - track.x, o.y - track.y) < 40)
    .sort((a, b) => Math.hypot(a.x - track.x, a.y - track.y) - Math.hypot(b.x - track.x, b.y - track.y));
  return candidates[0];
}

test('mixed traffic demonstrates all five automatic labels from observed behavior', () => {
  assert.deepEqual([...new Set(demo.frames.flatMap((f) => f.tracks.map((tr) => tr.cls)))].sort(), labels.slice().sort());
  assert.ok(demo.frames.filter((f) => f.tracks.some((tr) => tr.cls === 'hostile')).length * demo.DT >= 3,
    'observable responsive pursuit should demonstrate a sustained hostile assessment');
  assert.ok(demo.frames[0].tracks.every((tr) => tr.cls === 'friendly'));
  const peacefulByObject = {};
  demo.frames.forEach((f) => f.tracks.forEach((tr) => {
    if (tr.cls !== 'peaceful') return;
    const o = associated(f, tr);
    if (o?.kind === 'benign') peacefulByObject[o.id] = (peacefulByObject[o.id] || 0) + 1;
    assert.ok(tr.behavior.observed_s >= 15, 'peaceful requires usable observed history');
  }));
  assert.ok(Object.values(peacefulByObject).reduce((a, b) => a+b, 0) >= 100,
    'safe traffic needs sustained peaceful observations');
  assert.equal(demo.summary.bfa, 0);
  assert.equal(demo.summary.ffa, 0);
});

test('dispatch requires sustained observed risk, rather than a scoring role or silence', () => {
  assert.ok(demo.investigations.requests.length > 0, 'actual suspicious contacts still cause dispatch');
  for (const req of demo.investigations.requests) {
    const f = demo.frames[Math.round(req.t_requested / demo.DT)];
    const track = f?.tracks.find((tr) => tr.id === req.track_id);
    assert.ok(track, 'request must refer to an observed track');
    assert.equal(track.cls, 'suspicious');
    assert.notEqual(track.st, 'tentative');
    assert.ok(track.pH >= demo.estimatorConfig.suspicious_threat_exit);
    assert.ok(track.behavior.features.reference_track_id || track.behavior.retained_risk?.features.reference_track_id);
    const preceding = demo.frames.slice(Math.round(req.t_requested / demo.DT)-29, Math.round(req.t_requested / demo.DT)+1);
    assert.ok(preceding.every((frame) => frame.tracks.find((tr) => tr.id === req.track_id)?.cls === 'suspicious'));
  }
});

test('changing truth roles cannot change observations, assessments or fleet decisions', () => {
  const swapped = JSON.parse(JSON.stringify(busy));
  swapped.targets.forEach((target) => { target.role = target.role === 'benign' ? 'hostile' : 'benign'; });
  const other = Sim.run({ ...params, scenario: swapped });
  assert.deepEqual(other.investigations, demo.investigations);
  other.frames.forEach((f, k) => {
    const original = demo.frames[k];
    // err is appended by the post-inference scorer and depends on truth role.
    const assessments = (tracks) => tracks.map(({ err, ...tr }) => tr);
    assert.deepEqual(assessments(f.tracks), assessments(original.tracks));
    assert.deepEqual(f.meas, original.meas);
    assert.deepEqual(f.missions, original.missions);
    assert.deepEqual(f.coverage, original.coverage);
  });
});

test('safe traffic remains distinguishable across independent sensor-noise seeds', () => {
  for (const seed of [1, 7, 83]) {
    const result = Sim.run({ ...params, seed });
    assert.equal(result.summary.bfa, 0, 'benign hostile false alarms, seed ' + seed);
    assert.equal(result.summary.ffa, 0, 'own-fleet hostile false alarms, seed ' + seed);
    let benignPeaceful = 0;
    result.frames.forEach((f) => f.tracks.forEach((tr) => {
      if (tr.id.startsWith('F')) return; // known own-fleet identity
      const o = associated(f, tr);
      if (tr.cls === 'peaceful' && o) {
        if (o.kind === 'benign') benignPeaceful++;
      }
    }));
    assert.ok(benignPeaceful >= 100, 'sustained benign peaceful observations, seed ' + seed);
  }
});

test('a hostile entry needs responsive pursuit and intercept risk, including noisy sensors', () => {
  const previous = new Map();
  demo.frames.forEach((f) => f.tracks.forEach((tr) => {
    if (tr.cls === 'hostile' && previous.get(tr.id) !== 'hostile') {
      const evidence = tr.behavior.retained_risk || tr.behavior;
      assert.ok(evidence.reasons.includes('pursuit_with_intercept_risk'));
      assert.ok(evidence.features.response_count >= 2);
      assert.ok(tr.pH >= demo.estimatorConfig.hostile_enter);
    }
    previous.set(tr.id, tr.cls);
  }));
});

test('a friendly dropout coasts and fades to unknown without suspicion or dispatch', () => {
  const scenario = require('./scenarios.js').hard;
  const r = Sim.run({ scenario, seed: scenario.seed, mode: 'realistic', weather: 'fog', loss: 40, delayMs: 225, driftMs: 200 });
  const before = r.frames[590].tracks.find((tr) => tr.id === 'F3');
  assert.equal(before.cls, 'friendly');
  const after = r.frames.filter((f) => f.t >= 64).map((f) => f.tracks.find((tr) => tr.id === 'F3'));
  assert.ok(after.every(Boolean), 'retain the known-fleet track with its stale observation age');
  after.forEach((tr) => {
    assert.equal(tr.st, 'coasting', 'loss of contact is a tracking status, not hostile evidence');
    assert.ok(['friendly', 'unknown', 'peaceful'].includes(tr.cls), 'silence alone must not accuse F3');
    assert.equal(tr.behavior.increment, 0, 'prediction cannot add observed behavior evidence');
  });
  assert.equal(after.at(-1).cls, 'unknown');
  assert.ok(after.at(-1).age > 50);
  assert.ok(!r.investigations.requests.some((q) => q.track_id === 'F3'));
});
