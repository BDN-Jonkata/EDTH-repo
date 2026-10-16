// Run the mock simulation headless and print the run as plain JSON.
//   node ui/viewer/export-run.js --seed 4127 --mode realistic --weather fog --loss 30 --assign F1=skydio_x10,GS2=gs_radar_rf > run.json
// Output keys: params, scenario, result (frames, alerts, timeline, summary). Feed it to seeder/save_simulation.py.
const Sim = require('./sim.js');

const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf('--' + k); return i >= 0 ? args[i + 1] : d; };
const params = {
  seed: parseInt(opt('seed', '4127'), 10),
  mode: opt('mode', 'optimistic'),
  weather: opt('weather', 'clear'),
  loss: parseFloat(opt('loss', '0')),
  delayMs: parseFloat(opt('delay', '0')),
  driftMs: parseFloat(opt('drift', '0')),
  assign: Object.fromEntries((opt('assign', '') || '').split(',').filter(Boolean).map((kv) => kv.split('='))),
};
const run = Sim.run(params);
const { frames, alerts, timeline, summary, sensors, missionConfig } = run;
process.stdout.write(JSON.stringify({ params: run.params, scenario: Sim.SCEN, result: { frames, alerts, timeline, summary, sensors, missionConfig } }));
