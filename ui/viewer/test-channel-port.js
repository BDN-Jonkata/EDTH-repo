// Port check: every case of common/testdata/channel_cases.json (made by `python -m common.golden` from the Python
// ports in common/jamming.py and common/linkcap.py) must get the same answer from jamming.js and linkcap.js.
// Run: node ui/viewer/test-channel-port.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const Jamming = require('./jamming.js');
const LinkCap = require('./linkcap.js');

const cases = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', 'common', 'testdata', 'channel_cases.json'), 'utf8'));
const close = (a, b, what) => assert.ok(Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(b)), what + ': ' + a + ' vs ' + b);
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('jamming: loss and RF noise at every position and time', () => {
  cases.jamming.forEach((c) => {
    const pos = { x: c.pos[0], y: c.pos[1] };
    close(Jamming.lossAt(c.zones, c.base, pos, c.t), c.loss, 'loss at ' + c.pos + ' t=' + c.t);
    close(Jamming.rfNoiseMult(c.zones, pos, c.t), c.rf_noise_mult, 'rf at ' + c.pos + ' t=' + c.t);
  });
});
test('message size: the JSON length without z and arr', () => {
  cases.sizes.forEach((c) => assert.strictEqual(LinkCap.sizeOf(c.payload), c.bytes));
});
cases.linkcap.forEach((c) => test('link cap: ' + c.name, () => {
  const net = LinkCap.create(c.kbps), sent = [];
  c.offers.forEach((o, i) => LinkCap.enqueue(net, o.node, { type: o.type, header: { seq: i, source_id: 'F1' }, pad: 'x'.repeat(o.pad), z: { mock: 'only' }, arr: 1 }, o.t, 0));
  c.drain_times.forEach((t) => LinkCap.drain(net, t, (m, finish) => sent.push({ seq: m.payload.header.seq, finish })));
  assert.deepStrictEqual(sent.map((s) => s.seq), c.sent.map((s) => s.seq));
  sent.forEach((s, i) => close(s.finish, c.sent[i].finish, 'finish of #' + s.seq));
  const stats = LinkCap.summary(net);
  assert.deepStrictEqual(Object.keys(stats).sort(), Object.keys(c.stats).sort());
  Object.keys(stats).forEach((k) => ['count', 'bytes', 'dropped'].forEach((f) => assert.strictEqual(stats[k][f], c.stats[k][f], k + '.' + f)));
}));

let failed = 0;
tests.forEach(([name, fn]) => { try { fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + e.message); } });
if (failed) process.exit(1);
