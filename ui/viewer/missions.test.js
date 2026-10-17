// Run with: node ui/viewer/missions.test.js
const test = require('node:test');
const assert = require('node:assert/strict');
const { Controller, closest, SEP, COMFORT, ACCEL, YAW_RATE } = require('./missions.js');
const Sim = require('./sim.js');
const dt = 0.1;
const f = (id, x, y, v = 10) => ({ id, x, y, v });
const sensor = (node, changes = {}) => ({ node, kind: 'EO', range: 150, minRange: 3,
  pointing: 'forward', fov: Math.PI / 2, every: 2, pd: 1, ...changes });
const track = (changes = {}) => ({ id: 'U1', kind: 'trk', status: 'confirmed', s: [700, 500, 10, 0],
  srcs: { 'F1 EO': 0 }, firstSources: { F1: 0 }, ...changes });

test('patrol selects unvisited before old cells; oldest before nearest; unique reservations', () => {
  const c = new Controller([f('F1', 100, 100), f('F2', 200, 100)], [], dt);
  c.cells.forEach((p) => { p.last = 4; });
  c.cells[1599].last = -1;
  c.cells[1240].last = 0;
  c.update(5, []);
  assert.equal(c.drones[0].cell, 1599);
  assert.equal(c.drones[1].cell, 1240);
  c.cells[1599].last = 5;
  c.cells[1240].last = 5;
  c.update(5.1, []);
  assert.equal(c.drones[0].cell, 1599); // a sensor sample cannot immediately reverse a patrol leg
  c.update(11.1, []);
  assert.notEqual(c.drones[0].cell, 1599);
  assert.notEqual(c.drones[0].cell, c.drones[1].cell);
});

test('sensor footprint respects heading, range window, cadence and drone-only coverage', () => {
  const c = new Controller([f('F1', 500, 500)], [sensor('F1', { minRange: 30 }), sensor('GS1', { range: 2000 })], dt);
  c.drones[0].heading = 0;
  c.observe(0, 1);
  assert.ok(c.cells.every((p) => p.last === -1));
  c.observe(0.2, 2);
  assert.equal(c.cells.find((p) => p.x === 562.5 && p.y === 512.5).last, 0.2);
  assert.equal(c.cells.find((p) => p.x === 512.5 && p.y === 512.5).last, -1); // blind spot
  assert.equal(c.cells.find((p) => p.x === 437.5 && p.y === 512.5).last, -1); // behind
  assert.equal(c.cells.find((p) => p.x === 662.5 && p.y === 512.5).last, -1); // too far
  c.sensors[0].range = 50; // weather-adjusted footprint
  c.drones[0].heading = Math.PI;
  c.observe(1, 10);
  assert.equal(c.cells.find((p) => p.x === 462.5 && p.y === 512.5).last, 1);
  assert.equal(c.cells.find((p) => p.x === 437.5 && p.y === 512.5).last, -1);
});

test('persistent detection gates following; first eligible detector wins, one per target', () => {
  const c = new Controller([f('F1', 500, 500), f('F2', 600, 500)], [sensor('F1'), sensor('F2')], dt);
  const tr = track({ status: 'tentative', srcs: { 'F1 EO': 0, 'F2 EO': 0 }, firstSources: { F1: 0, F2: 0 } });
  c.update(0, [tr]);
  assert.ok(c.drones.every((d) => d.mode === 'patrol'));
  tr.status = 'confirmed';
  c.update(0.1, [tr]);
  assert.equal(c.drones[0].mode, 'follow');
  assert.equal(c.drones[1].mode, 'patrol');
  const range = Math.hypot(c.drones[0].goal.x - tr.s[0], c.drones[0].goal.y - tr.s[1]);
  assert.ok(range > 3 && range < 150); // anticipate target motion while staying in observation range
  tr.id = 'H1';
  c.update(0.2, [tr]);
  assert.equal(c.snapshot()[0].target, 'H1');
  assert.equal(c.drones.filter((d) => d.target === tr).length, 1);
});

test('known friendly contacts and stale delayed detections cannot trigger following', () => {
  const c = new Controller([f('F1', 500, 500)], [sensor('F1')], dt);
  c.update(5, [track({ kind: 'frd', srcs: { 'F1 EO': 5 } }), track()]);
  assert.equal(c.drones[0].mode, 'patrol');
  const tr = track({ srcs: { 'F1 EO': 5 } });
  c.update(5, [tr]);
  assert.equal(c.drones[0].mode, 'follow');
  tr.cls = 'friendly';
  c.update(5.1, [tr]);
  assert.equal(c.drones[0].mode, 'patrol');
});

test('contact loss searches for ten seconds, supports reacquisition and removed tracks', () => {
  const c = new Controller([f('F1', 500, 500)], [sensor('F1')], dt);
  const tr = track();
  c.update(0, [tr]);
  c.update(1.1, [tr]);
  assert.equal(c.drones[0].mode, 'search');
  tr.srcs['F1 EO'] = 2;
  c.update(2, [tr]);
  assert.equal(c.drones[0].mode, 'follow');
  c.update(3.1, []);
  const start = c.drones[0].searchStart;
  c.update(start + 9.9, []);
  assert.equal(c.drones[0].mode, 'search');
  c.update(start + 10, []);
  assert.equal(c.drones[0].mode, 'patrol');
  assert.equal(c.drones[0].target, null);
});

test('handoff and tracker merge preserve single ownership', () => {
  const c = new Controller([f('F1', 500, 500), f('F2', 600, 500)], [sensor('F1'), sensor('F2')], dt);
  const a = track(), b = track({ id: 'H2', srcs: { 'F2 EO': 1.1 }, firstSources: { F2: 1.1 } });
  c.update(0, [a]);
  a.srcs['F2 EO'] = 1.1;
  c.update(1.1, [a]);
  assert.equal(c.drones[0].mode, 'patrol');
  assert.equal(c.drones[1].target, a);
  a.replacement = b;
  c.update(1.2, [b]);
  assert.equal(c.drones[1].target, b);
  assert.equal(c.drones.filter((d) => d.target === b).length, 1);
});

test('motion separates crossing routes, convergence, follow/search traffic and boundaries', () => {
  const c = new Controller([f('F1', 420, 500), f('F2', 580, 500), f('F3', 500, 420),
    f('F4', 500, 580), f('F5', 10, 10)], [], dt);
  c.drones.forEach((d) => { d.goal = { x: 500, y: 500 }; });
  c.drones[0].mode = 'follow'; c.drones[1].mode = 'search';
  for (let k = 0; k < 800; k++) {
    const prev = c.drones.map((d) => ({ ...d }));
    c.move(k * dt);
    c.drones.forEach((d, i) => {
      assert.ok(d.x >= 0 && d.x <= 1000 && d.y >= 0 && d.y <= 1000);
      assert.ok(Math.hypot(d.vx, d.vy) <= d.speed + 1e-8);
      for (let j = 0; j < i; j++) assert.ok(closest(prev[i], d, prev[j], c.drones[j], dt) >= SEP - 1e-7);
    });
  }
  c.drones[4].goal = { x: -500, y: -500 };
  for (let k = 0; k < 100; k++) c.move(k * dt);
  assert.ok(c.drones[4].x >= 0 && c.drones[4].y >= 0);
  assert.throws(() => new Controller([f('A', 0, 0), f('B', 10, 10)], [], dt), /start positions/);
});

test('position history interpolates actual flight, and snapshots do not change afterwards', () => {
  const c = new Controller([f('F1', 100, 100)], [], dt);
  c.record(0); c.update(0, []);
  const snapshot = c.snapshot();
  const original = JSON.stringify(snapshot);
  c.move(0); c.record(dt);
  const mid = c.state('F1', 0.05);
  assert.equal(mid.x, (100 + c.drones[0].x) / 2);
  assert.equal(mid.y, (100 + c.drones[0].y) / 2);
  c.update(1, []);
  assert.equal(JSON.stringify(snapshot), original);
});

test('head-on traffic brakes gradually while preserving the full separation margin', () => {
  const c = new Controller([f('A', 400, 500), f('B', 560, 500)], [], dt);
  c.drones[0].vx = 10; c.drones[1].vx = -10;
  c.drones[0].goal = { x: 800, y: 500 }; c.drones[1].goal = { x: 200, y: 500 };
  for (let k = 0; k < 200; k++) {
    const before = c.drones.map((d) => ({ ...d }));
    c.move(k * dt);
    assert.ok(closest(before[0], c.drones[0], before[1], c.drones[1], dt) >= 100 - 1e-7);
    c.drones.forEach((d, i) => assert.ok(Math.hypot(d.vx - before[i].vx, d.vy - before[i].vy) <= ACCEL * dt + 1e-9));
  }
});

test('sensor yaw is bounded through noisy detections, mission changes, and hovering', () => {
  const c = new Controller([f('F1', 500, 500)], [sensor('F1')], dt);
  const tr = track();
  c.drones[0].heading = Math.PI - 0.01;
  for (let k = 0; k < 350; k++) {
    const d = c.drones[0], heading = d.heading, vx = d.vx, vy = d.vy;
    const t = k * dt;
    tr.s[0] = k % 2 ? 100 : 900; // deliberately violent measurement/goal changes
    tr.srcs['F1 EO'] = t;
    c.update(t, k < 80 || k >= 250 ? [tr] : []);
    c.move(t);
    const turn = Math.abs(Math.atan2(Math.sin(d.heading - heading), Math.cos(d.heading - heading)));
    assert.ok(turn <= YAW_RATE * dt + 1e-9);
    assert.ok(Math.hypot(d.vx - vx, d.vy - vy) <= ACCEL * dt + 1e-9);
  }
  c.drones[0].mode = 'patrol'; c.drones[0].vx = 0; c.drones[0].vy = 0; c.drones[0].goal = null;
  const heading = c.drones[0].heading;
  c.move(40);
  assert.equal(c.drones[0].heading, heading);
});

test('heading interpolation follows the short arc across the angle boundary', () => {
  const c = new Controller([f('F1', 500, 500)], [], dt);
  c.drones[0].heading = Math.PI - 0.01; c.record(0);
  c.drones[0].heading = -Math.PI + 0.01; c.record(dt);
  assert.ok(Math.abs(Math.abs(c.state('F1', dt / 2).heading) - Math.PI) < 1e-9);
});

function assertFlight(r) {
  let minimum = Infinity, maxYaw = 0, maxAcceleration = 0;
  r.frames.forEach((fr, k) => {
    const ds = fr.truth.filter((o) => o.kind === 'friendly');
    const previous = k ? r.frames[k - 1].truth.filter((o) => o.kind === 'friendly') : ds;
    ds.forEach((d, i) => {
      const p = previous[i];
      const turn = Math.abs(Math.atan2(Math.sin(d.heading - p.heading), Math.cos(d.heading - p.heading)));
      maxYaw = Math.max(maxYaw, turn / dt * 180 / Math.PI);
      maxAcceleration = Math.max(maxAcceleration, Math.hypot(d.vx - p.vx, d.vy - p.vy) / dt);
      assert.ok(turn <= YAW_RATE * dt + 1e-8, 'sensor turns too fast at ' + fr.t);
      assert.ok(Math.hypot(d.vx - p.vx, d.vy - p.vy) <= ACCEL * dt + 1e-8, 'instant velocity change at ' + fr.t);
      assert.ok(d.x >= 0 && d.x <= 1000 && d.y >= 0 && d.y <= 1000);
      for (let j = 0; j < i; j++) {
        const separation = closest(p, d, previous[j], ds[j], dt);
        minimum = Math.min(minimum, separation);
        assert.ok(separation >= 100 - 1e-7, 'friendlies too close at ' + fr.t);
      }
    });
  });
  assert.ok(minimum >= 100 - 1e-7);
  return { minimum, maxYaw, maxAcceleration };
}

test('patrol destinations reserve space around neighbouring drones and goals', () => {
  const c = new Controller(Sim.SCEN.friendlies, [], dt);
  c.update(0, []);
  c.drones.forEach((d, i) => {
    assert.ok(d.goal);
    c.drones.forEach((other, j) => {
      if (i === j) return;
      assert.ok(Math.hypot(d.goal.x - other.x, d.goal.y - other.y) >= COMFORT);
      assert.ok(Math.hypot(d.goal.x - other.goal.x, d.goal.y - other.goal.y) >= COMFORT);
    });
  });
});

test('seeded simulation is repeatable, lite agrees, actual routes remain separated', () => {
  const params = { seed: 5, mode: 'optimistic', weather: 'clear', scenario: require('./scenarios.js').busy };
  const world = Sim.prepare(params.scenario);
  const a = Sim.run(params), b = Sim.run(params), lite = Sim.run(params, { lite: true });
  assertFlight(a);
  assert.deepEqual(a, b);
  assert.deepEqual(a.summary, lite.summary);
  assert.deepEqual(a.alerts, lite.alerts);
  assert.deepEqual(a.timeline, lite.timeline);
  assert.ok(a.alerts.some((e) => / follow /.test(e.text)));
  // With two radars this preset can retain contact throughout an investigation.
  // Search/reacquisition is exercised explicitly in the contact-loss test above.
  assert.ok(a.investigations.statuses.some((s) => ['done', 'aborted'].includes(s.state)));
  assert.equal(a.summary.ffa, 0, 'a beacon-known friendly must not attract a follower as a hostile');
  assert.ok(a.frames.at(-1).coverage.filter((t) => t >= 0).length > a.frames[0].coverage.filter((t) => t >= 0).length);
  assert.ok(a.frames[0].coverage.some((t) => t === -1));
  a.frames.forEach((fr, k) => {
    const friends = fr.truth.filter((o) => o.kind === 'friendly');
    const targets = fr.missions.filter((m) => m.target).map((m) => m.target);
    assert.equal(new Set(targets).size, targets.length);
    friends.forEach((d, i) => {
      assert.ok(d.x >= 0 && d.x <= 1000 && d.y >= 0 && d.y <= 1000);
      if (k) {
        const prev = a.frames[k - 1].truth.filter((o) => o.kind === 'friendly');
        assert.ok(Math.hypot(d.x - prev[i].x, d.y - prev[i].y) <= world.friendlies[i].v * dt + 1e-8);
        for (let j = 0; j < i; j++) assert.ok(closest(prev[i], d, prev[j], friends[j], dt) >= SEP - 1e-7);
      }
    });
  });
});

test('weather and lossy delayed communications run with matching lite metrics', (t) => {
  const stats = [];
  for (const seed of [7, 4127, 83]) {
    for (const weather of ['clear', 'fog', 'rain', 'wind', 'night']) {
      const p = { seed, mode: 'realistic', weather, loss: 40, delayMs: 500, driftMs: 300 };
      const a = Sim.run(p);
      stats.push(assertFlight(a));
      if (seed === 7) {
        const b = Sim.run(p, { lite: true });
        assert.deepEqual(a.summary, b.summary);
        assert.deepEqual(a.alerts, b.alerts);
      }
      assert.ok(a.frames.every((fr) => fr.missions.length === 5));
    }
  }
  t.diagnostic(JSON.stringify({ runs: stats.length, minimumSeparation: Math.min(...stats.map((s) => s.minimum)),
    maxYawDegSec: Math.max(...stats.map((s) => s.maxYaw)), maxAcceleration: Math.max(...stats.map((s) => s.maxAcceleration)) }));
});
