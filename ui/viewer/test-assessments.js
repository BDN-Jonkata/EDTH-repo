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

test('mixed traffic produces all five automatic labels together after observation', () => {
  const together = demo.frames.filter((f) => labels.every((cls) => f.tracks.some((tr) => tr.cls === cls)));
  assert.ok(together.length * demo.DT >= 3, 'all five flags should coexist for at least three seconds');
  assert.ok(demo.frames[0].tracks.every((tr) => tr.cls === 'friendly'));
  const peacefulByObject = {};
  demo.frames.forEach((f) => f.tracks.forEach((tr) => {
    if (tr.cls !== 'peaceful') return;
    const o = associated(f, tr);
    if (o?.kind === 'benign') peacefulByObject[o.id] = (peacefulByObject[o.id] || 0) + 1;
    assert.ok(tr.behavior.observed_s >= 15, 'peaceful requires usable observed history');
  }));
  for (const id of ['N1', 'N2', 'N3'])
    assert.ok(peacefulByObject[id] >= 100, id + ' transit/orbit needs sustained peaceful time');
  assert.equal(demo.summary.bfa, 0);
  assert.equal(demo.summary.ffa, 0);
});

test('benign and unknown contacts do not consume automatic identification drones', () => {
  assert.ok(demo.investigations.requests.length > 0, 'actual suspicious contacts still cause dispatch');
  for (const req of demo.investigations.requests) {
    const f = demo.frames[Math.round(req.t_requested / demo.DT)];
    const track = f?.tracks.find((tr) => tr.id === req.track_id);
    assert.ok(track, 'request must refer to an observed track');
    assert.equal(track.cls, 'suspicious');
    const o = associated(f, track);
    assert.notEqual(o?.kind, 'benign', 'benign traffic should leave patrol drones available in this demonstration');
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
        assert.notEqual(o.kind, 'hostile', 'observed threat pattern must not be cleared, seed ' + seed);
        if (o.kind === 'benign') benignPeaceful++;
      }
    }));
    assert.ok(benignPeaceful >= 100, 'sustained benign peaceful observations, seed ' + seed);
  }
});
