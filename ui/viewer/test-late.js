// Tests for late data, the isolated state and their viewer panel. Run: node ui/viewer/test-late.js
const assert = require('assert');
const Sim = require('./sim.js');
const StoreFwd = require('./storefwd.js');
const LateData = require('./latedata.js');
const SCENARIOS = require('./scenarios.js');

global.StoreFwd = StoreFwd;
global.LateData = LateData;
const els = {};
const el = (id) => els[id] || (els[id] = { id, innerHTML: '', checked: false, listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; } });
global.document = { getElementById: el };
require('./late-ui.js');

const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const run = (scenario, extra) => Sim.run(Object.assign({ seed: 7, mode: 'realistic', weather: 'clear', loss: 10, delayMs: 100, driftMs: 0, scenario }, extra));
let outage = null;
function outageScenario() {
  const sc=JSON.parse(JSON.stringify(SCENARIOS.outage));
  // The transport fixture must actually observe during its outage, independent
  // of which way a coverage patrol points a forward camera. Use native omni
  // RF/acoustics here; the production preset and controller remain unchanged.
  const f2=sc.friendlies.find(f=>f.id==='F2'),passive=sc.friendlies.find(f=>f.platform==='px4_quad_passive');
  f2.platform='px4_quad_passive';f2.sensors=JSON.parse(JSON.stringify(passive.sensors));
  return sc;
}
const outageRun = () => outage || (outage = run(outageScenario()));

// ------------------------------------------------------------ the log and the corrections
test('a reading is late when it arrives long after it was taken, or never', () => {
  const log = LateData.createLog();
  const z = { k: 'RAD', module: 'r1', m: 'rangeaz', sx: 0, sy: 0, rmax: 400, b: 0.5, r: 100, sigB: 0.01, sigR: 3 };
  [1, 2, 3].forEach((seq) => LateData.logSent(log, 'F1', seq, seq, z));
  LateData.logArrived(log, 'F1', 1, 1.2);
  LateData.logArrived(log, 'F1', 2, 9);
  assert.strictEqual(LateData.logArrived(log, 'F1', 2, 10), null, 'a duplicate does not change the arrival');
  assert.deepStrictEqual(LateData.lateReadings(log, 3).map((r) => [r.seq, r.arr]), [[2, 9], [3, null]]);
});
const track = (id, x, y, cls) => ({ id, cls: cls || 'hostile', x, y, pxx: 25, pyy: 25, pxy: 0 });
const radarFix = (x, y) => ({ x, y, R: [4, 0, 4] });
test('a late reading moves the track it fits towards the reading, weighted by the uncertainties', () => {
  const reading = { m: 'rangeaz', node: 'F1', t: 5, arr: 20, sx: 0, sy: 0, r: 110, b: 0, sigR: 2, sigB: 0.001 };
  const rev = LateData.revise([reading], [{ tracks: [track('T1', 100, 0)] }], 5, () => radarFix(110, 0));
  assert.strictEqual(rev.length, 1);
  assert.strictEqual(rev[0].track, 'T1');
  assert.ok(rev[0].dx > 7 && rev[0].dx < 10, 'about 25/29 of 10 m, got ' + rev[0].dx);
});
test('it is left alone when it does not fit any track, when it is a friendly, or when it never arrived', () => {
  const reading = { m: 'rangeaz', node: 'F1', t: 0, arr: 9, sx: 0, sy: 0, r: 100, b: 0, sigR: 2, sigB: 0.001 };
  const far = () => radarFix(400, 0);
  assert.strictEqual(LateData.revise([reading], [{ tracks: [track('T1', 100, 0)] }], 1, far).length, 0);
  assert.strictEqual(LateData.revise([reading], [{ tracks: [track('F2', 100, 0, 'friendly')] }], 1, () => radarFix(110, 0)).length, 0);
  assert.strictEqual(LateData.revise([Object.assign({}, reading, { arr: null })], [{ tracks: [track('T1', 100, 0)] }], 1, () => radarFix(110, 0)).length, 0);
});
test('corrections are averaged, not added, and fade once nothing new comes', () => {
  const revs = [{ track: 'T1', t: 10, dx: 8, dy: 0 }, { track: 'T1', t: 10.1, dx: 8, dy: 0 }];
  assert.ok(Math.abs(LateData.shiftAt(revs, 'T1', 10.1).dx - 8) < 0.5, 'two of the same size stay about 8 m');
  assert.ok(LateData.shiftAt(revs, 'T1', 60).dx < 0.1, 'faded after 50 s');
  assert.strictEqual(LateData.shiftAt(revs, 'T1', 5).dx, 0, 'not before the reading was taken');
  assert.strictEqual(LateData.shiftAt(revs, 'T2', 10.1).dx, 0);
});

// ------------------------------------------------------------------- the simulation
test('a node cut off for 30 s or more, yet alive, is isolated; a node that died is not', () => {
  const res = outageRun();
  const stateAt = (t, n) => res.frames[Math.round(t * 10)].health[n].state;
  assert.strictEqual(stateAt(40, 'F2'), 'presumed_dead');
  assert.strictEqual(stateAt(55, 'F2'), 'isolated');
  assert.strictEqual(stateAt(75, 'F2'), 'ok');
  assert.strictEqual(stateAt(119, 'F4'), 'presumed_dead', 'F4 went down for good: dead, not isolated');
  assert.ok(res.alerts.some((a) => a.text === 'F2 link presumed dead to isolated'));
});
test('what the cut-off node saw is kept, with when it was taken and when C2 got it', () => {
  const sf = outageRun().storeForward, f2 = sf.readings.filter((r) => r.node === 'F2' && r.t >= 20 && r.t <= 65);
  assert.ok(f2.length > 20, f2.length + ' readings');
  const arrived = f2.filter((r) => r.arr !== null);
  assert.ok(arrived.length > 0.8 * f2.length, 'most of it is resent when the link returns');
  assert.ok(arrived.every((r) => r.arr >= 65 && r.arr - r.t > sf.late_s), 'it reached C2 only after the outage');
  assert.ok(f2.every((r) => ['bearing', 'rangeaz', 'range'].includes(r.m) && r.sx !== undefined));
});
test('a delay burst shows up as late readings that arrive about extra_ms after they were taken', () => {
  const gs2 = outageRun().storeForward.readings.filter((r) => r.node === 'GS2' && r.t >= 71 && r.t <= 84 && r.arr !== null);
  assert.ok(gs2.length > 20, gs2.length + ' readings');
  const mean = gs2.reduce((a, r) => a + r.arr - r.t, 0) / gs2.length;
  assert.ok(mean > 3.8 && mean < 6, 'mean age ' + mean);
});
test('late readings give corrections on tracks that exist, in the time the readings were taken', () => {
  const res = outageRun(), revs = res.storeForward.revisions;
  assert.ok(revs.length > 10, revs.length + ' revisions');
  revs.forEach((v) => {
    const f = res.frames[Math.round(v.t / res.DT)];
    assert.ok(f.tracks.some((t) => t.id === v.track), v.track + ' exists at ' + v.t);
    assert.ok(Math.hypot(v.dx, v.dy) <= 60.2, 'a correction of ' + Math.hypot(v.dx, v.dy) + ' m is not a correction');
  });
});
test('the live picture is unchanged by the log: no store-and-forward, no readings; lite runs have no revisions', () => {
  const plain = run(SCENARIOS.challenge);
  assert.strictEqual(plain.storeForward, undefined);
  const lite = Sim.run({ seed: 7, mode: 'realistic', weather: 'clear', loss: 10, delayMs: 100, driftMs: 0, scenario: outageScenario() }, { lite: true });
  assert.deepStrictEqual(lite.storeForward.revisions, []);
  assert.strictEqual(lite.summary.rmse, outageRun().summary.rmse, 'logging changes nothing the tracker sees');
});

// ------------------------------------------------------------------------ the panel
function startPanel() {
  const res = outageRun(), state = { res, revised: true, localNode: null, layers: {} };
  let redraws = 0;
  const ctx = { state, kcol: { EO: '#aaa', RAD: '#0cf', IR: '#e85', MIC: '#fa3', RF: '#b8f' }, Y: (y) => 1000 - y,
    nodeXY: (f, id) => ({ x: 100, y: 200, id }), redraw: () => { redraws++; }, jump: (t) => { ctx.jumped = t; } };
  LateUI.init(ctx);
  LateUI.reset();
  return { res, state, ctx, redraws: () => redraws };
}
test('bursts are listed with the node, when taken and when they reached C2', () => {
  const { res } = startPanel();
  const f2 = LateUI.bursts().find((b) => b.node === 'F2');
  assert.ok(f2 && f2.n > 20 && f2.arrFirst >= 65);
  LateUI.render(res.frames[800]);
  assert.ok(els.lateBody.innerHTML.includes('data-jump="' + f2.from + '"'));
});
test('an isolated node gets a violet ring and a card that opens what it saw', () => {
  const { res, state, redraws } = startPanel();
  const f = res.frames[550];
  assert.ok(LateUI.mapSvg(f).includes('F2 ISOLATED'));
  LateUI.render(f);
  assert.ok(els.lateBody.innerHTML.includes('data-local="F2"') && els.lateBody.innerHTML.includes('isolated'));
  els.lateBody.listeners.click({ target: { closest: (s) => (s === '[data-local]' ? { dataset: { local: 'F2' } } : null) } });
  assert.strictEqual(state.localNode, 'F2');
  assert.strictEqual(redraws(), 1);
  LateUI.render(f);
  assert.ok(els.lateBody.innerHTML.includes('F2 saw, not yet at C2'));
  assert.ok(LateUI.mapSvg(f).includes('#9B7BFF'), 'what it saw is drawn in violet');
});
test('jumping to a burst turns the late data on and moves the playhead', () => {
  const { state, ctx } = startPanel();
  state.revised = false;
  els.lateBody.listeners.click({ target: { closest: (s) => (s === '[data-jump]' ? { dataset: { jump: '72.5' } } : null) } });
  assert.strictEqual(state.revised, true);
  assert.strictEqual(ctx.jumped, 72.5);
});
test('the revised frame moves tracks that were corrected; the as-C2-had-it frame does not', () => {
  const { res, state } = startPanel();
  const v = res.storeForward.revisions[0], f = res.frames[Math.round(v.t / res.DT)];
  const shownTrack = LateUI.frameAt(f).tracks.find((t) => t.id === v.track), raw = f.tracks.find((t) => t.id === v.track);
  assert.ok(Math.hypot(shownTrack.x - raw.x, shownTrack.y - raw.y) > 0.1 && shownTrack.revised);
  state.revised = false;
  assert.strictEqual(LateUI.frameAt(f), f);
});
test('the timeline gets one bar per burst', () => {
  startPanel();
  const svg = LateUI.timelineSvg((t) => t * 8);
  assert.strictEqual(svg.split('<rect').length - 1, LateUI.bursts().length);
  assert.ok(svg.includes('F2: '));
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + e.message); }
}
console.log(failed ? failed + ' failed' : 'all ' + tests.length + ' passed');
process.exit(failed ? 1 : 0);
