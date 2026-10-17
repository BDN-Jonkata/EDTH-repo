// End-to-end decisions from native noisy sensors, beyond Python/JS parity.
// Run: node ui/viewer/test-assessments.js
const test = require('node:test');
const assert = require('node:assert/strict');
const Sim = require('./sim.js');
const { AutomaticEstimator } = require('./friend-foe.js');
const { busy } = require('./scenarios.js');
const labels = ['friendly', 'hostile', 'peaceful', 'suspicious', 'unknown'];
// motionPeaceful: these tests show the behaviour module's own labels, including peaceful from steady benign motion;
// the simulation's default is the safe mode (see the test at the end of this file)
const params = { seed: busy.seed, mode: 'optimistic', weather: 'clear', scenario: busy, motionPeaceful: true };
const demo = Sim.run(params);

// Evaluation only: unique nearest truth within the scorer's 40 m false-alarm
// gate. Neither this association nor the scenario roles enter the estimator.
function associated(frame, track) {
  const candidates = frame.truth.filter((o) => Math.hypot(o.x - track.x, o.y - track.y) < 40)
    .sort((a, b) => Math.hypot(a.x - track.x, a.y - track.y) - Math.hypot(b.x - track.x, b.y - track.y));
  return candidates[0];
}

test('compact patrols retain distinct safe, suspicious and unidentified traffic assessments', () => {
  const observed=new Set(demo.frames.flatMap((f)=>f.tracks.map(tr=>tr.cls)));
  for(const cls of ['friendly','peaceful','suspicious','unknown'])assert.ok(observed.has(cls),cls);
  assert.ok([...observed].every(cls=>labels.includes(cls)));
  // Compact patrols need not generate the repeated ally maneuvers required for
  // pursuit evidence. The positive hostile case is exercised explicitly below.
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

test('dispatch uses sustained risk or timely cooperative review of unknown contacts', () => {
  assert.ok(demo.investigations.requests.length > 0, 'actual suspicious contacts still cause dispatch');
  for (const req of demo.investigations.requests) {
    const f = demo.frames[Math.round(req.t_requested / demo.DT)];
    const track = f?.tracks.find((tr) => tr.id === req.track_id);
    assert.ok(track, 'request must refer to an observed track');
    assert.notEqual(track.st, 'tentative');
    if(track.cls==='unknown') {
      assert.ok(track.assessment.needs_observer);
      assert.ok(track.assessment.inbound || f.t-track.born>=5);
      continue;
    }
    assert.equal(track.cls,'suspicious');
    if(track.behavior.reasons.some(reason=>['corroborated_inbound_course','recent_corroborated_approach'].includes(reason)))continue;
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
  // A separately observed encounter ensures this remains a positive test even
  // when the coverage controller holds its patrols instead of maneuvering.
  const model=new AutomaticEstimator({}, {}, ['ally']);let hostileSamples=0;
  const wave=t=>({x:200+8*t,y:400+35*Math.sin(.55*t),vx:8,vy:19.25*Math.cos(.55*t)});
  for(let k=0;k<=80;k++) {
    const t=k/2,a=wave(t),b=wave(t-2);
    const state=(id,p)=>({track_id:id,t,observed_t:t,position:[p.x,p.y,0],velocity:[p.vx,p.vy,0],pos_sigma:2,existence_prob:.95});
    const ally=state('ally',a),contact=state('contact',{x:b.x-80+3*t+.2*Math.sin(t),y:b.y+.2*Math.cos(t),vx:b.vx+3,vy:b.vy});
    const found=model.update(t,[ally,contact],[{friend_id:'trusted',t,position:ally.position,velocity:ally.velocity,pos_sigma:2}]);
    if(found.find(c=>c.track_id==='contact').cls==='hostile') {
      hostileSamples++;const evidence=model.explain('contact');
      const actual=evidence.retained_risk||evidence;
      assert.ok(actual.reasons.includes('pursuit_with_intercept_risk'));assert.ok(actual.features.response_count>=2);
    }
  }
  assert.ok(hostileSamples>0,'positive observed pursuit must still be classified hostile');
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

test('by default a track on a real hostile is never called peaceful from steady motion alone', () => {
  const { challenge } = require('./scenarios.js');
  const run = (extra) => Sim.run({ seed: challenge.seed, mode: 'optimistic', weather: 'clear', scenario: challenge, ...extra });
  const peacefulOnHostile = (res) => res.frames.reduce((n, f) => n + f.truth.filter((q) => q.id.startsWith('H')).reduce((m, h) =>
    m + f.tracks.filter((t) => !t.id.startsWith('F') && Math.hypot(t.x - h.x, t.y - h.y) < 40 && t.cls === 'peaceful').length, 0), 0);
  assert.equal(peacefulOnHostile(run({})), 0);
  assert.ok(peacefulOnHostile(run({ motionPeaceful: true })) > 100, 'the module on its own does call them peaceful');
});
