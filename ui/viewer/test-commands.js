// Tests for commanded drone motion. Run: node ui/viewer/test-commands.js
const assert = require('assert');
const Sim = require('./sim.js');
const SCENARIOS = require('./scenarios.js');

const base = (extra) => Object.assign({ seed: 5, mode: 'optimistic', weather: 'clear', loss: 0, delayMs: 0, driftMs: 0, scenario: SCENARIOS.easy }, extra);
const run = (extra) => Sim.run(base(extra));
const trackOf = (res, id) => res.frames.map((f) => f.truth.find((o) => o.id === id));
const speed = (o) => Math.hypot(o.vx, o.vy);
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

const TASKS = [
  { t: 10, drone_id: 'F2', command: 'goto', target: [500, 500, 60], speed_mps: 10, face_target: [700, 700] },
  { t: 60, drone_id: 'F2', command: 'return_to_patrol' },
];

test('no commands: autonomous missions retain coverage and bounded sensor headings', () => {
  const res = run({});
  assert.strictEqual(res.commands, undefined);
  assert.ok(trackOf(res, 'F2').every((o) => Number.isFinite(o.heading)));
  assert.ok(res.frames.every((f) => f.missions.every((m) => ['patrol', 'follow', 'search'].includes(m.mode))));
  assert.ok(res.frames.at(-1).coverage.some((last) => last >= 0));
});

test('goto: acked, reaches the point, faces the target, respects the limits', () => {
  // Isolate arrival/facing from fleet congestion; conflicts are tested separately.
  const scenario = JSON.parse(JSON.stringify(SCENARIOS.easy));
  scenario.friendlies = scenario.friendlies.filter((f) => f.id === 'F2');
  scenario.friendlies[0].loop = { cx: 600, cy: 500, R: 100, v: 8, dir: 1, th0: 0 };
  const res = run({ scenario, commands: TASKS });
  const goto = res.commands[0];
  assert.strictEqual(goto.status, 'accepted'); assert.strictEqual(goto.attempts, 1);
  const states = goto.reports.map((r) => r.state);
  assert.deepStrictEqual(states, ['accepted', 'on_station'], 'each state is reported once even though milestones are repeated');
  const lim = Sim.PLATFORMS[res.params.assign.F2].spec.flight, f2 = trackOf(res, 'F2');
  f2.forEach((o, i) => {
    assert.ok(speed(o) <= Math.min(10, lim.max_speed_mps) + 0.01 || res.frames[i].t < 10 || res.frames[i].t >= 60, 'speed cap at t=' + res.frames[i].t);
    if (i > 0 && res.frames[i].t > 10.2 && res.frames[i].t < 60) {
      const a = Math.abs(speed(o) - speed(f2[i - 1])) / Sim.DT; // max_accel limits the change of speed; max_turn limits the change of course
      assert.ok(a <= lim.max_accel_mps2 * 1.01, 'accel ' + a.toFixed(2) + ' at t=' + res.frames[i].t);
      const course = (q) => Math.atan2(q.vy, q.vx), dc = Math.abs(Math.atan2(Math.sin(course(o) - course(f2[i - 1])), Math.cos(course(o) - course(f2[i - 1]))));
      assert.ok(dc <= lim.max_turn_dps * Math.PI / 180 * Sim.DT + 1e-6 || speed(o) < 0.5, 'turn at t=' + res.frames[i].t);
    }
  });
  const hold = f2[Math.round(55 / Sim.DT)];
  assert.ok(Math.hypot(hold.x - 500, hold.y - 500) < 3, 'holds at the point');
  const toTarget = Math.atan2(700 - hold.y, 700 - hold.x);
  assert.ok(Math.abs(Math.atan2(Math.sin(hold.heading - toTarget), Math.cos(hold.heading - toTarget))) < 0.09, 'camera faces the target');
});

test('return_to_patrol: resumes coordinated patrol without a position jump', () => {
  const res = run({ commands: TASKS });
  const ret = res.commands[1];
  assert.strictEqual(ret.status, 'accepted');
  assert.ok(ret.reports.some((r) => r.state === 'patrolling'), 'patrolling reported');
  const atReturn = res.frames[Math.round(60 / Sim.DT)];
  assert.strictEqual(atReturn.missions.find((m) => m.id === 'F2').mode, 'patrol');
  const last = trackOf(res, 'F2')[res.NF], previous = trackOf(res, 'F2')[Math.round(60 / Sim.DT) - 1];
  const current = atReturn.truth.find((d) => d.id === 'F2');
  assert.ok(Math.hypot(previous.x - current.x, previous.y - current.y) <= 10 * Sim.DT + 1e-6);
  assert.ok(last.x >= 0 && last.x <= 1000 && last.y >= 0 && last.y <= 1000);
});

test('a lossy channel makes the sender retry, deterministically', () => {
  const lossy = { mode: 'realistic', loss: 60, delayMs: 200, commands: TASKS };
  const a = run(lossy), b = run(lossy);
  assert.deepStrictEqual(a.commands, b.commands);
  assert.ok(a.commands.some((r) => r.attempts > 1), 'at least one command needed a retry');
  assert.ok(a.commands.every((r) => r.attempts <= 5));
});

test('a dead drone never acks: the command is reported lost after 5 tries', () => {
  const sc = JSON.parse(JSON.stringify(SCENARIOS.easy));
  sc.degradations.dropout = [{ node: 'F3', t: 5 }];
  const res = run({ scenario: sc, mode: 'realistic', commands: [{ t: 10, drone_id: 'F3', command: 'hold' }] });
  assert.strictEqual(res.commands[0].status, 'lost'); assert.strictEqual(res.commands[0].attempts, 5);
  assert.ok(res.alerts.some((a) => /No ack from F3/.test(a.text)));
});

test('a goto outside the area is rejected and the drone keeps patrolling', () => {
  const res = run({ commands: [{ t: 10, drone_id: 'F1', command: 'goto', target: [1500, 500] }] });
  assert.strictEqual(res.commands[0].status, 'rejected');
  assert.ok(trackOf(res, 'F1').every((o) => Number.isFinite(o.heading)));
  assert.ok(res.frames.every((f) => !['goto', 'hold'].includes(f.missions.find((m) => m.id === 'F1').mode)));
});

test('commanded and autonomous drones share separation, acceleration and yaw limits', () => {
  const res = run({ commands: TASKS });
  const wrap = (a) => Math.atan2(Math.sin(a), Math.cos(a));
  res.frames.forEach((f, k) => {
    const drones = f.truth.filter((d) => d.kind === 'friendly');
    const previous = k ? res.frames[k - 1].truth.filter((d) => d.kind === 'friendly') : drones;
    drones.forEach((d, i) => {
      assert.ok(Math.hypot(d.vx - previous[i].vx, d.vy - previous[i].vy) <= 2 * Sim.DT + 1e-7);
      assert.ok(Math.abs(wrap(d.heading - previous[i].heading)) <= 20 * Math.PI / 180 * Sim.DT + 1e-7);
      for (let j = 0; j < i; j++) assert.ok(Math.hypot(d.x - drones[j].x, d.y - drones[j].y) >= 100 - 1e-7);
    });
  });
});

let failed = 0;
tests.forEach(([name, fn]) => {
  try { fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + e.message); }
});
process.exit(failed ? 1 : 0);
