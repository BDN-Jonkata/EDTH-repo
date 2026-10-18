// Runs the "degradation vs message loss" sweep off the page's thread: one lite simulation per message, so the
// page keeps responding while the ten loss levels are computed. app.js posts {run, loss, params, scenario} and
// gets {run, row} back; the files below are the ones sim.js needs (not the page's own UI scripts).
self.window = self;
importScripts('catalog.js', 'coverage.js', 'missions.js', 'messages.js', 'weather.js', 'jamming.js', 'linkcap.js',
  'storefwd.js', 'latedata.js', 'drones.js', 'encounters.js', 'behavior.js', 'traffic.js', 'friend-foe.js',
  'investigations.js', 'metrics.js', 'assessment.js', 'intent.js', 'sim.js');

self.onmessage = (e) => {
  const { run, loss, params, scenario } = e.data;
  const r = self.Sim.run(Object.assign({}, params, { loss, scenario }), { lite: true });
  const s = r.summary;
  self.postMessage({ run, row: { loss, rmse: s.rmse, count: s.countErr, swaps: s.swaps, ffa: s.ffa, coverage: s.trackedFraction } });
};
