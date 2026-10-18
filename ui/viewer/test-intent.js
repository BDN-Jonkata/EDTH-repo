// Intent from motion: a physical prior that is corrected by what the run shows afterwards.
// Run: node ui/viewer/test-intent.js
const assert = require('assert');
const Intent = require('./intent.js');
const Sim = require('./sim.js');
const SCENARIOS = require('./scenarios.js');

const assets = [{ x: 500, y: 500 }];
const track = (id, x, y, vx, vy) => ({ id, kind: 'trk', s: [x, y, vx, vy] });
const watch = (learner, tracks, seconds) => {
  let verdicts;
  for (let t = 0; t < seconds; t += 0.1) verdicts = learner.update(t, 0.1, tracks, assets);
  return verdicts;
};

{
  const learner = new Intent.Learner();
  const v = watch(learner, [track('in', 100, 500, 10, 0), track('by', 100, 50, 10, 0)], 10);
  assert.ok(v.get('in').p > v.get('by').p + 0.3, 'a course through the defended point scores above one that passes far by');
  console.log('ok   prior: a course through the defended point scores above one that passes by');
}
{
  const learner = new Intent.Learner();
  const v = watch(learner, [track('by', 100, 50, 10, 0)], 24);
  assert.strictEqual(learner.verdict(v.get('by')), 'peaceful');
  assert.strictEqual(learner.verdict(watch(new Intent.Learner(), [track('in', 100, 500, 10, 0)], 24).get('in')), null, 'hostile is not decided from the course alone');
  console.log('ok   a course that passes far by is peaceful after 20 s; a course through the area is not called from the course alone');
}
{
  const learner = new Intent.Learner();
  const before = learner.score(Intent.features({ watched: 10, hovering: 0, turn: 0 }, track('x', 100, 500, 10, 0), assets));
  watch(learner, [track('in', 480, 500, 1, 0)], 10);             // comes within 60 m of the defended point
  assert.ok(learner.taught >= 1, 'a track that reached the defended point teaches a positive example');
  watch(learner, [track('by', 100, 50, 10, 0)], 30);
  learner.update(31, 0.1, [], assets);                            // it leaves without coming near: a negative example
  assert.ok(learner.taught >= 2, 'a track that left without coming near teaches a negative example');
  assert.notStrictEqual(learner.w.join(), Intent.PRIOR.join(), 'the weights moved');
  console.log('ok   the weights learn from outcomes (' + learner.taught + ' examples), before ' + before.toFixed(2));
}
{
  const s = SCENARIOS.mixed, benign = new Set(s.targets.filter((t) => t.role === 'benign').map((t) => t.id)), hostile = new Set(s.targets.filter((t) => t.role === 'hostile').map((t) => t.id));
  const res = Sim.run({ seed: s.seed, mode: 'optimistic', weather: 'clear', loss: 0, delayMs: 0, driftMs: 0, scenario: s, assign: {}, learnIntent: true });
  const n = { benign: [0, 0], hostile: [0, 0] };
  res.frames.forEach((f) => f.truth.forEach((o) => {
    const kind = benign.has(o.id) ? 'benign' : hostile.has(o.id) ? 'hostile' : null;
    const t = kind && f.tracks.find((q) => !q.id.startsWith('F') && (q.st !== 'tentative' || q.once) && Math.hypot(q.x - o.x, q.y - o.y) < 40);
    if (t) { n[kind][1]++; if (t.cls === 'peaceful') n[kind][0]++; }
  }));
  assert.ok(n.benign[0] / n.benign[1] > 0.05, 'some harmless drone time is called peaceful');
  assert.ok(n.hostile[0] / n.hostile[1] < 0.05, 'real hostiles are rarely called peaceful');
  console.log('ok   mixed: peaceful on ' + (100 * n.benign[0] / n.benign[1]).toFixed(0) + ' % of harmless drone time, ' + (100 * n.hostile[0] / n.hostile[1]).toFixed(0) + ' % of hostile time');
}
{
  const plans = new Intent.Plans([{ id: 'R1', waypoints: [[0, 0, 0], [100, 1000, 0]] }]);   // 10 m/s along y = 0
  let kept;
  for (let t = 0; t < 6; t += 0.1) kept = plans.update(t, 0.1, [track('on', 10 * t + 5, 0, 10, 0), track('off', 10 * t, 200, 10, 0)]);
  assert.strictEqual(kept.get('on'), 'R1', 'a track keeping to the plan is expected traffic');
  assert.ok(!kept.has('off'), 'a track 200 m off the plan is not');
  console.log('ok   a track that keeps to a known flight plan is expected traffic, one off it is not');
}
{
  const cfg = Intent.CFG;
  const toward = Intent.timeToReach(track('a', 250, 500, 10, 0), assets, cfg), by = Intent.timeToReach(track('b', 100, 50, 10, 0), assets, cfg), away = Intent.timeToReach(track('c', 100, 500, -10, 0), assets, cfg);
  assert.ok(toward < cfg.reach_s, 'a course through the defended point is reached soon');
  assert.strictEqual(by, Infinity);
  assert.strictEqual(away, Infinity);
  const learner = new Intent.Learner();
  assert.strictEqual(learner.verdict(watch(learner, [track('a', 250, 500, 10, 0)], 6).get('a')), 'hostile', 'unplanned and going for the defended area soon is a threat');
  console.log('ok   going for the defended area within ' + cfg.reach_s + ' s is a threat after ' + cfg.threat_after_s + ' s; passing by or leaving is not');
}
{
  const s = SCENARIOS.mixed, res = Sim.run({ seed: s.seed, mode: 'optimistic', weather: 'clear', loss: 0, delayMs: 0, driftMs: 0, scenario: s, assign: {}, learnIntent: true });
  const d = res.summary.declare;
  assert.strictEqual(d.hostiles, 3);
  assert.ok(d.declared >= 2, 'most hostiles are called hostile');
  console.log('ok   mixed: ' + d.declared + ' of ' + d.hostiles + ' hostiles declared, on average ' + Math.round(d.rangeM) + ' m from what is defended');
}
console.log('all 7 passed');
