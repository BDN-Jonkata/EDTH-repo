// Tests for store-and-forward and link health in the mock channel. Run: node ui/viewer/test-storefwd.js
const assert = require('assert');
const Sim = require('./sim.js');
const StoreFwd = require('./storefwd.js');
const SCENARIOS = require('./scenarios.js');

const OUTAGE = [{ node: 'F2', kind: 'link_outage', t_start: 30, t_end: 60 }];
function scenario(deg) {
  const s = JSON.parse(JSON.stringify(SCENARIOS.challenge));
  s.degradations = Object.assign({}, s.degradations, deg);
  return s;
}
const run = (deg, extra) => Sim.run(Object.assign({ seed: 4127, mode: 'realistic', weather: 'clear', loss: 10, delayMs: 100, driftMs: 0, scenario: scenario(deg) }, extra));
const sent = (seq, t) => ({ type: 'observation', header: { seq, source_id: 'F1' }, arr: t + 0.1 });
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('a seq that already arrived is a duplicate', () => {
  const r = StoreFwd.createReceiver();
  assert.strictEqual(StoreFwd.receive(r, 1, 0), true);
  assert.strictEqual(StoreFwd.receive(r, 1, 0.1), false);
  assert.strictEqual(r.upto, 1);
});
test('the ack lists what is missing as ranges, and stops waiting below what the node still holds', () => {
  const r = StoreFwd.createReceiver();
  [1, 2, 5, 6, 9].forEach((s) => StoreFwd.receive(r, s, 0));
  assert.deepStrictEqual(StoreFwd.ackEntry(r), { upto: 2, max: 9, missing: [[3, 4], [7, 8]] });
  StoreFwd.skipBelow(r, 7);
  assert.deepStrictEqual(StoreFwd.ackEntry(r), { upto: 6, max: 9, missing: [[7, 8]] });
});
test('after an ack a node drops what C2 has and resends what is missing, oldest first, within the budget', () => {
  const node = StoreFwd.createNode();
  for (let s = 1; s <= 6; s++) StoreFwd.remember(node, sent(s, s * 0.1), s * 0.1);
  const out = StoreFwd.onAck(node, { upto: 1, max: 6, missing: [[2, 3], [5, 5]] }, 5, 2, () => 1);
  assert.deepStrictEqual(out.map((m) => m.header.seq), [2, 3]);
  assert.ok(out.every((m) => m.arr === undefined), 'resends carry no old arrival time');
  assert.deepStrictEqual(node.store.map((m) => m.seq), [2, 3, 5]);
  assert.deepStrictEqual(StoreFwd.onAck(node, { upto: 1, max: 6, missing: [[2, 3], [5, 5]] }, 5.5, 9, () => 1).map((m) => m.header.seq), [5], 'just resent: not again yet');
});
test('a node counts itself offline after three missed acks, and expires what is older than its buffer', () => {
  const node = StoreFwd.createNode({ buffer_s: 10 });
  StoreFwd.onAck(node, { upto: 0, max: 0, missing: [] }, 2, Infinity, () => 1);
  assert.strictEqual(StoreFwd.isOffline(node, 5), false);
  assert.strictEqual(StoreFwd.isOffline(node, 5.1), true);
  for (let t = 0; t <= 20; t++) StoreFwd.remember(node, sent(t + 1, t), t);
  assert.strictEqual(node.store[0].t, 10);
  assert.strictEqual(node.stats.expired, 10);
});
test('health: a few lost messages early on are not a degraded link; silence is offline, then presumed dead', () => {
  const r = StoreFwd.createReceiver();
  [1, 4, 5].forEach((s) => StoreFwd.receive(r, s, 0.5));
  assert.strictEqual(StoreFwd.health(r, 1).state, 'ok');
  for (let s = 6; s <= 60; s++) if (s % 2) StoreFwd.receive(r, s, 1);
  assert.strictEqual(StoreFwd.health(r, 1).state, 'degraded');
  assert.strictEqual(StoreFwd.health(r, 5).state, 'offline');
  assert.strictEqual(StoreFwd.health(r, 16).state, 'presumed_dead');
});
test('an outage is caught up: nothing expires, the catch-up time is reported, C2 saw the node go offline', () => {
  const res = run({ sensor_faults: OUTAGE, store_forward: { enabled: true } });
  const sf = res.storeForward;
  assert.strictEqual(sf.nodes.F2.expired, 0);
  assert.ok(sf.nodes.F2.resent > 0 && sf.nodes.F2.late_arrivals > 0);
  assert.strictEqual(sf.outages.length, 1);
  assert.ok(sf.outages[0].catch_up_s > 0 && sf.outages[0].catch_up_s < 20, 'catch-up ' + sf.outages[0].catch_up_s);
  assert.ok(['offline', 'presumed_dead'].includes(res.frames[450].health.F2.state));
  assert.strictEqual(res.frames[450].health.F2.offline, true);
  assert.ok(res.alerts.some((a) => a.text === 'F2 link ok to offline'));
});
test('a clean run with store-and-forward raises no link alerts', () => {
  assert.ok(!run({ store_forward: { enabled: true } }).alerts.some((a) => / link /.test(a.text)));
});
test('without store-and-forward, or in Optimistic mode, there is no summary and no health', () => {
  const plain = run({ sensor_faults: OUTAGE });
  assert.strictEqual(plain.storeForward, undefined);
  assert.strictEqual(plain.frames[0].health, undefined);
  assert.strictEqual(run({ sensor_faults: OUTAGE, store_forward: { enabled: true } }, { mode: 'optimistic' }).storeForward, undefined);
});
test('a dropout fault stops the node like a dropout', () => {
  const asFault = run({ sensor_faults: [{ node: 'F3', kind: 'dropout', t_start: 40 }] });
  const asDropout = run({ dropout: [{ node: 'F3', t: 40 }] });
  assert.deepStrictEqual(asFault.summary, asDropout.summary);
  assert.deepStrictEqual(asFault.frames.map((f) => f.tracks), asDropout.frames.map((f) => f.tracks));
});
test('a delay burst makes messages late but loses none', () => {
  const res = run({ sensor_faults: [{ node: 'F2', kind: 'delay_burst', t_start: 30, t_end: 40, extra_ms: 5000 }], store_forward: { enabled: true } });
  assert.ok(res.storeForward.nodes.F2.late_arrivals > 0);
  assert.strictEqual(res.storeForward.nodes.F2.expired, 0);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + e.message); }
}
console.log(failed ? failed + ' failed' : 'all ' + tests.length + ' passed');
process.exit(failed ? 1 : 0);
