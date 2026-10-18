// The whole system in weather: the same scenarios under single conditions and combinations, with the identification numbers.
// Run: node ui/viewer/weather-sweep.js [preset,preset] [loss in percent] [weather,weather+weather]
// Hostile is the share of ALL frames of a real hostile in which a track on it is called hostile, so a hostile nobody tracked counts against it.
const Sim = require('./sim.js');
const SCENARIOS = require('./scenarios.js');

const presets = (process.argv[2] || 'mixed,challenge').split(',');
const loss = +(process.argv[3] || 30);
const CONDITIONS = (process.argv[4] || 'clear,rain,fog,wind,night,rain+night,fog+night,fog+rain,fog+wind,rain+wind,rain+wind+night,fog+rain+wind+night').split(',');
const mean = (x) => x.reduce((a, b) => a + b, 0) / Math.max(1, x.length);
const pct = (a, b) => (100 * a / Math.max(1, b)).toFixed(0) + '%';

function roles(s) {
  const out = {}, planned = (s.cleared_routes || []).length;
  s.targets.forEach((t) => { out[t.id] = t.role === 'hostile' ? 'hostile' : (t.id <= 'N' + planned ? 'plan' : 'benign'); });
  s.clutter.forEach((c) => { out[c.id] = c.type; });
  return out;
}
// the track on a real object that no other drone could own
function trackOn(f, o) {
  const others = f.truth.filter((d) => d.kind !== 'friendly' && d.kind !== 'clutter' && d.id !== o.id);
  return f.tracks.find((t) => !t.id.startsWith('F') && (t.st !== 'tentative' || t.once) && Math.hypot(t.x - o.x, t.y - o.y) < 40 && !others.some((d) => Math.hypot(d.x - t.x, d.y - t.y) < 60));
}
function measure(weather) {
  const m = { tracked: [], host: [0, 0], decl: [0, 0], range: [], bird: [0, 0, 0], plan: [0, 0], ffa: [], cnt: [], rmse: [], over: [], under: [], false: [] };
  presets.forEach((name) => {
    const s = SCENARIOS[name], role = roles(s);
    const res = Sim.run({ emitterHostile: true, learnIntent: true, objectClass: true, repeatObs: 'auto', seed: s.seed, mode: 'realistic', weather, loss, delayMs: 0, driftMs: 0, scenario: s, assign: {} });
    res.frames.forEach((f) => f.truth.forEach((o) => {
      const r = role[o.id]; if (!r) return;
      const q = trackOn(f, o);
      if (r === 'hostile') { m.host[1]++; if (q && q.cls === 'hostile') m.host[0]++; }
      if (r === 'bird' && q) { m.bird[2]++; if (q.cls === 'object') m.bird[0]++; if (q.cls === 'hostile') m.bird[1]++; }
      if (r === 'plan' && q) { m.plan[1]++; if (q.cls === 'peaceful') m.plan[0]++; }
    }));
    const after = res.frames.filter((f) => f.t >= 10);   // after the warm-up
    m.over.push(mean(after.map((f) => Math.max(0, f.m.est - f.m.tru)))); m.under.push(mean(after.map((f) => Math.max(0, f.m.tru - f.m.est))));
    m.false.push(mean(after.map((f) => f.tracks.filter((t) => !t.id.startsWith('F') && (t.st !== 'tentative' || t.once) && !f.truth.some((o) => Math.hypot(o.x - t.x, o.y - t.y) < 60)).length)));
    const sm = res.summary;
    m.tracked.push(sm.trackedFraction || 0); m.decl[0] += sm.declare.declared; m.decl[1] += sm.declare.hostiles;
    if (sm.declare.rangeM !== null) m.range.push(sm.declare.rangeM);
    m.ffa.push(sm.ffa || 0); m.cnt.push(Math.abs(sm.countErr)); m.rmse.push(sm.rmse || 0);
  });
  return m;
}
module.exports = { measure, CONDITIONS };
if (require.main === module) {
  console.log('presets', presets.join('+'), '| message loss', loss, '%');
  console.log('weather'.padEnd(20), 'tracked  hostile  declared  range  birds obj/host  plan peaceful  ffa  count-err  too-many too-few  false-tracks  rmse');
  CONDITIONS.forEach((w) => {
    const m = measure(w);
    console.log(w.padEnd(20), mean(m.tracked).toFixed(2).padStart(6), pct(m.host[0], m.host[1]).padStart(8), (m.decl[0] + '/' + m.decl[1]).padStart(9), (mean(m.range).toFixed(0) + 'm').padStart(6),
      (pct(m.bird[0], m.bird[2]) + '/' + pct(m.bird[1], m.bird[2])).padStart(14), pct(m.plan[0], m.plan[1]).padStart(13), mean(m.ffa).toFixed(1).padStart(4), mean(m.cnt).toFixed(2).padStart(9), mean(m.over).toFixed(2).padStart(9), mean(m.under).toFixed(2).padStart(8), mean(m.false).toFixed(2).padStart(12), mean(m.rmse).toFixed(1).padStart(6));
  });
}
