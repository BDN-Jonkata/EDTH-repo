// Tests for the message format of the mock (header and fields). Run: node ui/viewer/test-messages.js
const assert = require('assert');
const Sim = require('./sim.js');
const Messages = require('./messages.js');
const SCENARIOS = require('./scenarios.js');

const TASKS = [{ t: 10, drone_id: 'F2', command: 'goto', target: [500, 500, 60] }, { t: 40, drone_id: 'F2', command: 'return_to_patrol' }];
// every message sent in a run, lost or not
function sent(extra) {
  const out = [];
  const P = Object.assign({ seed: 5, mode: 'realistic', weather: 'clear', loss: 30, delayMs: 200, driftMs: 50, scenario: SCENARIOS.challenge, commands: TASKS }, extra);
  Sim.run(P, { lite: true, tap: (m) => out.push(m) });
  return out;
}
const ofType = (msgs, type) => msgs.filter((m) => m.type === type);
const isSquare = (M, n) => M.length === n && M.every((row) => row.length === n);
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('makeHeader: msg_id, per-source seq, schema_version', () => {
  const seqs = {};
  const a = Messages.makeHeader(seqs, 'C2', 1.5), b = Messages.makeHeader(seqs, 'C2', 2), c = Messages.makeHeader(seqs, 'F1', 2);
  assert.deepStrictEqual(Object.keys(a), Messages.HEADER_FIELDS);
  assert.strictEqual(a.msg_id, 'C2-1'); assert.strictEqual(b.msg_id, 'C2-2'); assert.strictEqual(c.msg_id, 'F1-1');
  assert.strictEqual(a.schema_version, 1);
});

test('every message has a type and the full header, and msg_id is unique', () => {
  const msgs = sent({});
  const types = new Set(msgs.map((m) => m.type));
  assert.deepStrictEqual([...types].sort(), ['drone_command', 'drone_state', 'friendly_beacon', 'observation']);
  msgs.forEach((m) => assert.deepStrictEqual(Object.keys(m.header), Messages.HEADER_FIELDS, m.type));
  assert.strictEqual(new Set(msgs.map((m) => m.header.msg_id)).size, msgs.length, 'msg_id repeats');
  const last = {};
  msgs.forEach((m) => { // seq counts up by one per source
    assert.strictEqual(m.header.seq, (last[m.header.source_id] || 0) + 1, m.header.msg_id);
    last[m.header.source_id] = m.header.seq;
  });
});

test('t_sent is the sender clock: true time without drift, off by the drift with it', () => {
  const still = sent({ driftMs: 0 }), drift = sent({});
  assert.ok(ofType(still, 'observation').every((m) => Math.abs(m.header.t_sent - m.z.t) < 1e-9));
  assert.ok(ofType(drift, 'observation').some((m) => Math.abs(m.header.t_sent - m.z.t) > 1e-3));
  assert.ok(ofType(drift, 'drone_command').every((m) => m.header.source_id === 'C2'), 'commands come from C2');
});

test('observation: sensor, kind, native value and a covariance over cov_fields', () => {
  const obs = ofType(sent({}), 'observation');
  assert.ok(obs.length > 100);
  obs.forEach((m) => {
    assert.ok(['eo_camera', 'thermal_camera', 'microphone', 'rf_receiver', 'radar'].includes(m.sensor_type), m.sensor_type);
    assert.ok(['bearing', 'range_bearing', 'detection'].includes(m.kind), m.kind);
    assert.strictEqual(m.header.source_id, m.z.node);
    assert.strictEqual(m.t_obs, m.header.t_sent);
    assert.ok(m.cov_fields.length > 0 && m.cov_fields.every((f) => typeof m.value[f] === 'number'), m.cov_fields.join());
    assert.ok(isSquare(m.covariance, m.cov_fields.length) && m.covariance.every((row, i) => row[i] > 0));
  });
  assert.deepStrictEqual(new Set(obs.map((m) => m.kind)).size, 3, 'all three kinds appear in the challenge preset');
});

test('friendly_beacon: the fields friend_foe/jsonl_io.py reads', () => {
  const beacons = ofType(sent({}), 'friendly_beacon');
  assert.ok(beacons.length > 50);
  beacons.forEach((m) => {
    const keys = Object.keys(m).filter((k) => k !== 'arr'); // arr: arrival time the mock channel adds
    assert.deepStrictEqual(keys, ['type', 'header', 'friend_id', 'position', 'velocity', 'covariance']);
    assert.strictEqual(m.friend_id, m.header.source_id);
    assert.strictEqual(m.position.length, 3); assert.strictEqual(m.velocity.length, 3);
    assert.ok(isSquare(m.covariance, 3));
  });
});

let failed = 0;
tests.forEach(([name, fn]) => {
  try { fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + e.message); }
});
process.exit(failed ? 1 : 0);
