/* The logic of the COP replay page (cop.html): read a saved run, count what a frame shows, follow a track back in time.
 * It reads a run from the Python pipeline (`python -m pipeline.export_run`) or from the JavaScript mock (`export-run.js`):
 * both are { params, scenario, result } with the compact { cols, rows } tables of docs/data-formats.md.
 * Truth is read only to draw the evaluation overlay and to count true hostiles beside the estimates; nothing here infers. */
(function (global) {
  'use strict';
  const CLASSES = ['hostile', 'suspicious', 'unknown', 'peaceful', 'friendly', 'object'];
  const NOT_THREATS = ['friendly', 'peaceful'];

  // { cols, rows } tables become lists of objects, as seeder/tables.py's unpack does.
  function unpack(v) {
    if (Array.isArray(v)) return v.map(unpack);
    if (v && typeof v === 'object') {
      const keys = Object.keys(v);
      if (keys.length === 2 && v.cols && v.rows) return v.rows.map((row) => Object.fromEntries(v.cols.map((c, i) => [c, unpack(row[i])])));
      return Object.fromEntries(keys.map((k) => [k, unpack(v[k])]));
    }
    return v;
  }

  function load(run) {
    if (!run || typeof run !== 'object' || !run.result) throw new Error('This is not a saved run: it has no "result".');
    const result = unpack(run.result);
    if (!Array.isArray(result.frames) || !result.frames.length) throw new Error('The run has no frames.');
    const frames = result.frames.map((f) => Object.assign({}, f, { tracks: f.tracks || [], truth: f.truth || [] }));
    return { engine: run.engine || 'js-mock', params: run.params || {}, scenario: run.scenario || {}, frames,
      summary: result.summary || {}, duration: result.T_END || frames[frames.length - 1].t };
  }

  const shown = (tracks) => tracks.filter((tr) => tr.st !== 'tentative');

  // What a frame says: tracks per class, the strict hostile count, the older "not friendly, not peaceful" count, and the true hostiles.
  function counts(frame) {
    const tracks = shown(frame.tracks), byClass = Object.fromEntries(CLASSES.map((c) => [c, 0]));
    tracks.forEach((tr) => { byClass[tr.cls] = (byClass[tr.cls] || 0) + 1; });
    return { byClass, hostile: byClass.hostile, presumed: tracks.filter((tr) => !NOT_THREATS.includes(tr.cls)).length,
      truthHostile: frame.truth.filter((o) => o.kind === 'hostile').length };
  }

  // Where a track was over the last `seconds`, oldest first.
  function trail(frames, k, id, seconds) {
    const out = [];
    for (let j = k; j >= 0 && frames[k].t - frames[j].t <= seconds; j -= 1) {
      const tr = shown(frames[j].tracks).find((o) => o.id === id);
      if (tr) out.unshift([tr.x, tr.y]);
    }
    return out;
  }

  const num = (v, digits) => (typeof v === 'number' && Number.isFinite(v) ? v.toFixed(digits) : 'n/a');
  const pct = (v) => (typeof v === 'number' ? Math.round(v * 100) + ' %' : 'n/a');

  // The run's own summary as label/value rows, whichever engine wrote it.
  function summaryRows(summary) {
    const w = summary.whole_run;
    if (w) {
      return [['Hostile tracked', pct(w.hostile_tracked_frac)], ['Count error (not friendly), mean', num(w.count_error_mean_abs, 2)],
        ['Position error', num(w.pos_rmse_m, 1) + ' m'], ['ID swaps', String(w.id_swaps)], ['False tracks per step', num(w.false_tracks_mean, 2)],
        ['Friendlies flagged', String(w.friendlies_flagged)]];
    }
    if (summary.rmse !== undefined) {
      return [['Position error', num(summary.rmse, 1) + ' m'], ['Hostile count error', num(summary.countErr, 2)],
        ['ID swaps', String(summary.swaps)], ['Friendlies flagged hostile', String(summary.ffa)]];
    }
    return [];
  }

  const heading = (vx, vy) => (((Math.atan2(vx, vy) * 180) / Math.PI) + 360) % 360;

  const api = { CLASSES, unpack, load, shown, counts, trail, summaryRows, heading };
  global.Cop = api;
  if (typeof module !== 'undefined') module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
