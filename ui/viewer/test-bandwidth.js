// Tests for link capacity in the mock channel. Run: node ui/viewer/test-bandwidth.js
const assert = require('assert');
const Sim = require('./sim.js');
const LinkCap = require('./linkcap.js');
const SCENARIOS = require('./scenarios.js');

const run = (extra, tap) => Sim.run(Object.assign({ seed: 5, mode: 'realistic', weather: 'clear', loss: 0, delayMs: 0, driftMs: 0, scenario: SCENARIOS.challenge }, extra), tap ? { tap } : undefined);
const msg = (type, n) => ({ type, header: { seq: 1 }, pad: 'x'.repeat(n), z: { big: 'mock only' }, arr: 1 });
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('size is the JSON length without the mock-only z and arr', () => {
  const m = msg('observation', 10);
  assert.strictEqual(LinkCap.sizeOf(m), JSON.stringify({ type: m.type, header: m.header, pad: m.pad }).length);
  assert.ok(LinkCap.sizeOf(m) < JSON.stringify(m).length);
});
test('a link never carries more than its cap: messages leave one after another, each taking bytes / rate', () => {
  const net = LinkCap.create(8); // 1000 bytes per second
  for (let i = 0; i < 5; i++) LinkCap.enqueue(net, 'F1', msg('observation', 250), 0, 0);
  const sent = [];
  for (let t = 0; t <= 10; t += 0.1) LinkCap.drain(net, t, (m, at) => sent.push({ at, bytes: m.bytes }));
  assert.strictEqual(sent.length, 5);
  for (let i = 1; i < sent.length; i++) assert.ok(sent[i].at - sent[i - 1].at >= sent[i].bytes / net.bytesPerS - 1e-9);
  const window = sent.filter((s) => s.at > 2 && s.at <= 3).reduce((n, s) => n + s.bytes, 0);
  assert.ok(window <= net.bytesPerS, 'bytes in one second: ' + window);
});
test('when the backlog is too long the oldest messages are dropped and the newest survive', () => {
  const net = LinkCap.create(8);
  for (let i = 0; i < 40; i++) { const m = msg('observation', 100); m.header.seq = i; LinkCap.enqueue(net, 'F1', m, 0, 0); }
  const kept = [];
  for (let t = 0; t <= 60; t += 0.1) LinkCap.drain(net, t, (m) => kept.push(m.payload.header.seq));
  const dropped = LinkCap.summary(net).observation.dropped;
  assert.ok(dropped > 0 && kept.length + dropped === 40);
  assert.deepStrictEqual(kept, kept.slice().sort((a, b) => a - b));
  assert.strictEqual(kept[kept.length - 1], 39, 'the newest message is kept');
  assert.ok(kept.length * 135 <= LinkCap.QUEUE_S * net.bytesPerS + 2 * 135);
});
test('links of different nodes are independent', () => {
  const net = LinkCap.create(8);
  LinkCap.enqueue(net, 'F1', msg('observation', 800), 0, 0);
  LinkCap.enqueue(net, 'F2', msg('observation', 100), 0, 0);
  const at = {};
  LinkCap.drain(net, 0, (m, finish) => { at[m.node] = finish; });
  assert.ok(at.F2 < 0.5 && at.F1 > 0.8);
});
test('a run with a cap reports the bytes per message type, matching the messages sent', () => {
  const sizes = {};
  const res = run({ bandwidthKbps: 64 }, (m) => { sizes[m.type] = (sizes[m.type] || 0) + LinkCap.sizeOf(m); });
  Object.keys(sizes).forEach((type) => assert.strictEqual(res.bandwidth[type].bytes, sizes[type], type));
  assert.ok(res.bandwidth.observation.count > 100 && res.bandwidth.observation.avg_bytes > 200);
});
test('a low cap drops messages; a cap above the demand drops none', () => {
  const dropped = (r) => Object.keys(r.bandwidth).reduce((n, t) => n + r.bandwidth[t].dropped, 0);
  assert.ok(dropped(run({ bandwidthKbps: 8 })) > 0);
  assert.strictEqual(dropped(run({ bandwidthKbps: 100000 })), 0);
});
test('messages that are lost on the link still used their airtime', () => {
  const dropped = (r) => r.bandwidth.observation.dropped;
  assert.strictEqual(dropped(run({ bandwidthKbps: 16, loss: 100 })), dropped(run({ bandwidthKbps: 16, loss: 0 })));
});
test('no cap, or Optimistic mode: no bandwidth entry and the same run', () => {
  assert.strictEqual(run({}).bandwidth, undefined);
  assert.strictEqual(run({ bandwidthKbps: null }).bandwidth, undefined);
  assert.strictEqual(run({ mode: 'optimistic', bandwidthKbps: 8 }).bandwidth, undefined);
});
test('the scenario sets the cap unless the run overrides it', () => {
  const sc = JSON.parse(JSON.stringify(SCENARIOS.challenge));
  sc.degradations.network = Object.assign({}, sc.degradations.network, { bandwidth_kbps: 32 });
  assert.ok(run({ scenario: sc }).bandwidth);
  assert.strictEqual(run({ scenario: sc, bandwidthKbps: null }).bandwidth, undefined);
});

let failed = 0;
tests.forEach(([name, fn]) => { try { fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + e.message); } });
if (failed) process.exit(1);
