// A class reached on evidence stays until evidence for another class comes: a track never goes back to unknown.
// Run: node ui/viewer/test-held-class.js
const assert = require('assert');
const Sim = require('./sim.js');
const SCENARIOS = require('./scenarios.js');

for (const name of ['medium', 'mixed']) {
  const res = Sim.run({ seed: SCENARIOS[name].seed, mode: 'realistic', weather: 'clear', loss: 0.3, delayMs: 0, driftMs: 0, scenario: SCENARIOS[name], assign: {}, emitterHostile: true });
  const decided = {}, sized = {};
  let held = 0;
  res.frames.forEach((f) => f.tracks.forEach((t) => {
    // a track the radar has read as a bird or a vehicle, or that two receivers in reach never hear, is let go on purpose
    if (t.size) sized[t.id] = true;
    if (decided[t.id] && !sized[t.id] && !t.quiet) { assert.notStrictEqual(t.cls, 'unknown', name + ' ' + t.id + ' fell back to unknown at ' + f.t.toFixed(1) + ' s'); held++; }
    if (['hostile', 'peaceful', 'friendly'].includes(t.cls)) decided[t.id] = true;
  }));
  assert.ok(Object.keys(decided).length > 0, name + ': some track got a class');
  console.log('ok   ' + name + ': no track went back to unknown after it had a class (' + held + ' track-frames kept)');
}
console.log('all passed');
