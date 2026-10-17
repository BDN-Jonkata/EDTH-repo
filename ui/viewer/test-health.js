// Port check: every case of health/testdata/health_cases.json (made by `python -m health.golden` from the Python
// reference in health/link.py and health/monitor.py) must get the same answer from health.js.
// Run: node ui/viewer/test-health.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const Health = require('./health.js');

const cases = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', 'health', 'testdata', 'health_cases.json'), 'utf8'));
const close = (a, b, what) => assert.ok(Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(b)), what + ': ' + a + ' vs ' + b);
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('the defaults equal the Python HealthConfig', () => {
  Object.keys(cases.config).forEach((k) => {
    if (typeof cases.config[k] === 'number') close(Health.DEFAULTS[k], cases.config[k], 'config ' + k);
    else assert.strictEqual(Health.DEFAULTS[k], cases.config[k], 'config ' + k);
  });
});
test('Wilson intervals', () => {
  cases.wilson_cases.forEach((c) => {
    const [lo, hi] = Health.wilson(c.missed, c.n, c.z);
    close(lo, c.interval[0], 'lower of ' + c.missed + '/' + c.n);
    close(hi, c.interval[1], 'upper of ' + c.missed + '/' + c.n);
  });
});
cases.link_cases.forEach((c) => test('link: ' + c.name, () => {
  const monitor = Health.create(cases.config);
  const messages = c.messages.slice().sort((a, b) => a.t - b.t);
  let i = 0;
  c.expected.forEach((e) => {
    while (i < messages.length && messages[i].t <= e.t) {
      Health.observe(monitor, { header: { source_id: messages[i].source, seq: messages[i].seq } }, messages[i].t);
      i++;
    }
    const snap = Health.snapshot(monitor, e.t);
    assert.deepStrictEqual(Object.keys(snap).sort(), Object.keys(e.nodes).sort(), 'nodes at t=' + e.t);
    Object.keys(e.nodes).forEach((n) => {
      const want = e.nodes[n], what = ' (' + n + ' t=' + e.t + ')';
      assert.strictEqual(snap[n].state, want.state, 'state' + what);
      assert.strictEqual(snap[n].alarm, want.alarm, 'alarm' + what);
      close(snap[n].p_bad, want.p_bad, 'p_bad' + what);
      close(snap[n].loss_rate, want.loss_rate, 'loss_rate' + what);
      close(snap[n].silent_s, want.silent_s, 'silent_s' + what);
      close(Health.trust(monitor, n, e.t), want.trust, 'trust' + what);
      close(Health.trust(monitor, n, e.t, 5.0), want.trust_age_5, 'trust at age 5' + what);
      close(Health.explainsSilence(monitor, n, e.t), want.explains_silence, 'explains_silence' + what);
    });
  });
}));

let failed = 0;
tests.forEach(([name, fn]) => { try { fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + e.message); } });
if (failed) process.exit(1);
