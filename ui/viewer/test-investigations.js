const test = require('node:test');
const assert = require('node:assert/strict');
const { Controller: Investigator, standoff } = require('./investigations.js');
const { Controller: Missions } = require('./missions.js');
const W = require('./weather.js');
const CAT = require('./catalog.js');
const moduleEO = CAT.modules.find((m) => m.id === 'eo_visible_mini4');

function fixture(weather = 'clear') {
  const provider = W.providerFor({}, weather, null).provider;
  const sm = moduleEO.sim, effects = W.activeEffects(provider.at([0, 0], 0)), quality = W.sensorQuality(moduleEO, effects);
  const sensors = ['F1', 'F2'].map((node) => ({ node, mod: moduleEO, sm, module: moduleEO.id, kind: 'EO',
    range: sm.range_m * quality.range, minRange: sm.min_range_m, pointing: 'forward', fov: Math.PI / 2, pd: sm.pd * quality.pd }));
  const inv = new Investigator(sensors, ['F1', 'F2'], provider, (s) => s, () => {}, {}, (_, t) => t - 0.1);
  const missions = new Missions([{ id: 'F1', x: 100, y: 100, v: 10 }, { id: 'F2', x: 600, y: 100, v: 10 }], sensors, 0.1,
    () => {}, { requireInvestigation: true, geometry: (tr, d, t) => inv.geometry(tr, d, t) });
  const track = { id: 'U1', kind: 'trk', status: 'confirmed', cls: 'suspicious', s: [700, 100, 0, 0],
    P: [4, 0, 0, 0, 0, 4], lastUpd: 0, srcs: {}, firstSources: {}, classification: { class_prob: 0.82, p_friendly: 0.18 } };
  function step(t, tracks = [track]) {
    tracks.forEach((tr) => { tr.lastUpd = t; });
    inv.update(t, tracks); missions.update(t, tracks); inv.sync(t, missions.drones);
  }
  return { inv, missions, track, step };
}

test('suspicion is sustained for three seconds before dispatch, closest suitable drone wins', () => {
  const { inv, missions, step } = fixture();
  step(0); step(2.9);
  assert.equal(inv.requests.length, 0);
  step(3);
  assert.equal(inv.requests.length, 1);
  assert.equal(missions.drones[0].mode, 'patrol');
  assert.equal(missions.drones[1].mode, 'follow');
  assert.deepEqual(inv.statuses.map((m) => m.state), ['assigned', 'en_route']);
  assert.equal(inv.statuses[0].drone_id, 'F2');
  assert.equal(inv.statuses[0].header.t_sent, 2.9);
  for (let t = 3.1; t < 8; t += 0.1) step(t);
  assert.equal(inv.requests.length, 1);
  assert.equal(missions.drones.filter((d) => d.target).length, 1);
});

test('peaceful and hostile assessments finish an investigation and release the drone', () => {
  for (const cls of ['friendly', 'peaceful', 'hostile']) {
    const { inv, missions, track, step } = fixture();
    step(0); step(3);
    track.cls = cls; step(3.1);
    assert.ok(missions.drones.every((d) => d.mode === 'patrol'));
    assert.equal(inv.statuses.at(-1).state, 'done');
    assert.equal(inv.active.size, 0);
  }
});

test('an approached ally keeps its mission while a different drone investigates', () => {
  const { missions, track, step } = fixture();
  track.behavior = { features: { reference_track_id: 'F2' } };
  step(0); step(3);
  assert.equal(missions.drones[1].mode, 'patrol');
  assert.equal(missions.drones[0].mode, 'follow');
});

test('retained encounter evidence also excludes its approached ally', () => {
  const { missions, track, step } = fixture();
  track.behavior = { features: { reference_track_id: 'F1' }, retained_risk: { features: { reference_track_id: 'F2' } } };
  step(0); step(3);
  assert.ok(missions.drones.every((d) => d.mode === 'patrol'), 'wait for an uninvolved observer');
});

test('deleted tracks abort; reacquisition obeys cooldown', () => {
  const { inv, missions, track, step } = fixture();
  step(0); step(3); step(3.1, []);
  assert.equal(inv.statuses.at(-1).state, 'aborted');
  assert.ok(missions.drones.every((d) => d.mode === 'patrol'));
  step(4); step(8);
  assert.equal(inv.requests.length, 1);
  step(34);
  assert.equal(inv.requests.length, 2);
  assert.equal(missions.drones.filter((d) => d.target === track).length, 1);
});

test('weather can make identification infeasible; the fleet keeps patrolling', () => {
  const { inv, missions, step } = fixture('fog+rain+wind+night');
  step(0); step(3);
  assert.equal(inv.requests.length, 1);
  assert.equal(inv.requests[0].feasible, false);
  assert.ok(missions.drones.every((d) => d.mode === 'patrol'));
});

test('a commanded drone is unavailable and interrupts an active assignment', () => {
  const { inv, missions, step } = fixture();
  step(0); step(3);
  missions.command('F2', { command: 'hold' }, {});
  missions.command('F1', { command: 'hold' }, {});
  step(3.1);
  assert.equal(inv.statuses.at(-1).state, 'aborted');
  assert.ok(missions.drones.every((d) => d.mode === 'hold'));
});

test('the catalog identification range sets the standoff', () => {
  const altered = Object.assign({}, moduleEO, { sim: Object.assign({}, moduleEO.sim, { ident_range_m: 50 }) });
  const s = standoff(altered, {});
  assert.equal(s.max_range_m, 50);
  assert.equal(s.recommended_m, 35);
});

test('sensors with no feasible safe standoff cannot attract a drone', () => {
  const { inv, missions, step } = fixture();
  inv.sensors.forEach((s) => { s.sm = Object.assign({}, s.sm, { ident_range_m: 30 }); });
  step(0); step(3);
  assert.ok(missions.drones.every((d) => d.mode === 'patrol'));
});

test('an RF-only drone is suitable only after observed emitter evidence', () => {
  const { inv, missions, track, step } = fixture();
  const rf = CAT.modules.find((m) => m.id === 'rf_sdr_receiver');
  inv.sensors.forEach((s) => Object.assign(s, { kind: 'RF', module: rf.id, mod: rf, sm: rf.sim,
    range: rf.sim.range_m, pd: rf.sim.pd, minRange: rf.sim.min_range_m }));
  step(0); step(3);
  assert.ok(missions.drones.every((d) => d.mode === 'patrol'));
  track.srcs['GS2 RF'] = 4;
  step(4);
  assert.equal(missions.drones.filter((d) => d.mode === 'follow').length, 1);
});
