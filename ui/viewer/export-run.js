// Run the mock simulation headless and print the run as plain JSON.
//   node ui/viewer/export-run.js --scenario out/hard-s3/scenario.json   (a file made by seeder/generate.py; default: the challenge preset)
//   node ui/viewer/export-run.js --seed 4127 --mode realistic --weather fog --loss 30 --assign F1=skydio_x10,GS2=gs_radar_rf > run.json
// Output keys: params, scenario, result (frames, alerts, timeline, summary); numbers are rounded and object lists are stored as {cols, rows} tables. Feed it to seeder/save_simulation.py.
const fs = require('fs');
const Sim = require('./sim.js');

const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf('--' + k); return i >= 0 ? args[i + 1] : d; };
const scenario = opt('scenario', '') ? JSON.parse(fs.readFileSync(opt('scenario', ''), 'utf8')) : undefined;
const params = {
  scenario,
  seed: parseInt(opt('seed', String(scenario ? scenario.seed : 4127)), 10),
  mode: opt('mode', 'optimistic'),
  weather: opt('weather', 'clear'),
  loss: parseFloat(opt('loss', '0')),
  delayMs: parseFloat(opt('delay', '0')),
  driftMs: parseFloat(opt('drift', '0')),
  assign: Object.fromEntries((opt('assign', '') || '').split(',').filter(Boolean).map((kv) => kv.split('='))),
};

// Compact form for storage: numbers are rounded, and a list of objects with the same keys becomes
// { cols: [keys], rows: [[values]] } so the keys are written once. seeder/tables.py reads it back.
const POS = new Set(['x', 'y', 'sx', 'sy', 'pxx', 'pxy', 'pyy', 'pvv']); // metres: 0.1 m is far below sensor noise
function pack(v, key) {
  if (typeof v === 'number') { const d = POS.has(key) ? 1 : 3; return Number.isInteger(v) ? v : Number(v.toFixed(d)); }
  if (Array.isArray(v)) {
    const first = v[0];
    const plain = (o) => o && typeof o === 'object' && !Array.isArray(o);
    if (v.length > 1 && plain(first)) {
      const cols = Object.keys(first), same = v.every((o) => plain(o) && Object.keys(o).join() === cols.join());
      if (same) return { cols, rows: v.map((o) => cols.map((c) => pack(o[c], c))) };
    }
    return v.map((x) => pack(x, key));
  }
  if (v && typeof v === 'object') { const o = {}; for (const k of Object.keys(v)) o[k] = pack(v[k], k); return o; }
  return v;
}
const run = Sim.run(params);
const { frames, alerts, timeline, summary, sensors, commands, missionConfig, behaviorConfig, estimatorConfig, investigations } = run;
process.stdout.write(JSON.stringify({ params: run.params, scenario: scenario || Sim.DEFAULT_SCENARIO, result: pack({ frames, alerts, timeline, summary, sensors, commands, missionConfig, behaviorConfig, estimatorConfig, investigations }) }));
