/* Relative-motion cues. Python reference: drone_behavior/encounters.py. */
(function (global) {
  'use strict';
  const mean = (a) => a.reduce((s, v) => s + v, 0) / a.length;
  function at(series, t) {
    if (!series.length || t < series[0].t - 1e-8 || t > series.at(-1).t + 1e-8) return null;
    if (series.length === 1) return series[0];
    let lo = 1, hi = series.length - 1;
    while (lo < hi) { const mid = Math.floor((lo + hi) / 2); if (series[mid].t >= t - 1e-8) hi = mid; else lo = mid + 1; }
    const a = series[lo - 1], b = series[lo], w = Math.max(0, Math.min(1, (t - a.t) / (b.t - a.t)));
    return Object.fromEntries(['x', 'y', 'vx', 'vy', 'sigma'].map((k) => [k, a[k] + w * (b[k] - a[k])]));
  }
  const cosine = (a, b) => (a.vx * b.vx + a.vy * b.vy) / Math.max(1, Math.hypot(a.vx, a.vy) * Math.hypot(b.vx, b.vy));
  const turn = (a, b) => Math.atan2(a.vx * b.vy - a.vy * b.vx, a.vx * b.vx + a.vy * b.vy);
  function maneuvers(series) {
    const events = [];
    series.forEach((s) => {
      const old = at(series, s.t - 2);
      if (!old || Math.min(Math.hypot(old.vx, old.vy), Math.hypot(s.vx, s.vy)) < 2) return;
      const angle = turn(old, s);
      if (Math.abs(angle) >= 0.28 && (!events.length || (s.t - events.at(-1)[0] >= 3 && angle * events.at(-1)[1] < 0))) events.push([s.t, angle]);
    });
    return events;
  }
  function assess(contact, ally) {
    const pairs = contact.map((s) => [s, at(ally, s.t)]).filter(([, a]) => a);
    const empty = { response_count: 0, closing_m: 0, intercept_episodes: 0, response_lag_s: 0 };
    if (pairs.length < 2 || pairs.at(-1)[0].t - pairs[0][0].t < 8) return [0, [], empty, false];
    const rows = pairs.map(([s, a]) => {
      const dx = s.x - a.x, dy = s.y - a.y, vx = s.vx - a.vx, vy = s.vy - a.vy;
      const d = Math.hypot(dx, dy), sigma = Math.hypot(s.sigma, a.sigma);
      const closing = -(dx * vx + dy * vy) / Math.max(d, 1), toward = -(dx * s.vx + dy * s.vy) / Math.max(d, 1);
      const tcpa = -(dx * vx + dy * vy) / Math.max(vx * vx + vy * vy, 1), miss = Math.hypot(dx + vx * tcpa, dy + vy * tcpa);
      const resolved = sigma <= 12 && d > 2 * sigma + 5, moving = Math.hypot(a.vx, a.vy) >= 2 && Math.hypot(s.vx, s.vy) >= 2;
      return { t: s.t, d, closing, toward, resolved,
        hazard: resolved && moving && closing > 2 && toward > 2 && tcpa > 0 && tcpa <= 12 && miss + 2 * sigma < 25,
        converging: resolved && moving && closing > 1.5 && toward > 2 && tcpa > 0 && tcpa <= 30 && miss - 2 * sigma < 35,
        aimed: toward / Math.max(1, Math.hypot(s.vx, s.vy)) > 0.55 };
    });
    const span = rows.at(-1).t - rows[0].t;
    let episodes = 0, runStart = null, lastEnd = -Infinity;
    rows.forEach((r) => {
      if (r.hazard) {
        if (runStart === null) runStart = r.t;
        if (r.t - runStart >= 2 && runStart - lastEnd >= 3) { episodes++; lastEnd = Infinity; }
      } else { if (runStart !== null) lastEnd = r.t; runStart = null; }
    });
    const current = rows.at(-1);
    let risk = episodes && current.hazard ? 1.2 : 0, reasons = risk ? ['sustained_collision_course'] : [];
    if (episodes >= 2) { risk = 2.1; reasons = ['repeated_intercept_approaches']; }
    const events = maneuvers(ally);
    const times = pairs.map(([s]) => s.t).filter((t) => t >= Math.max(contact[0].t, ally[0].t) + 3 && t <= Math.min(contact.at(-1).t, ally.at(-1).t) - 3);
    const fits = [-3, -2, -1, 0, 1, 2, 3].map((lag) => {
      const usable = times.map((t) => [at(contact, t + lag), at(ally, t)]).filter(([s, a]) => s && a && Math.min(Math.hypot(s.vx, s.vy), Math.hypot(a.vx, a.vy)) >= 2);
      return [usable.length >= 8 ? mean(usable.map(([s, a]) => 1 - cosine(s, a))) : 2, lag];
    });
    const [bestError, lag] = fits.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1])[0];
    const earlierError = Math.min(...fits.filter(([, delay]) => delay <= 0).map(([error]) => error));
    let responses = 0;
    if (lag > 0 && bestError < 0.12 && bestError + 0.015 < earlierError && bestError < 0.75 * earlierError) {
      events.forEach(([t, angle]) => {
        const a = at(ally, t), s = at(contact, t + lag), old = at(contact, t + lag - 2);
        if (s && old && turn(old, s) * angle > 0.035 && cosine(s, a) > 0.8) responses++;
      });
    }
    const closingM = rows[0].d - current.d;
    const pursuing = span >= 12 && responses >= 2 && rows.filter((r) => r.aimed && r.resolved).length / rows.length >= 0.65;
    if (pursuing) {
      risk = Math.max(risk, 1.8); reasons.push('responsive_pursuit');
      const closure = closingM > Math.max(35, 4 * Math.hypot(pairs.at(-1)[0].sigma, pairs.at(-1)[1].sigma));
      const sustained = rows.filter((r) => r.closing > 1.5 && r.toward > 2).length / rows.length >= 0.3;
      const excess = mean(pairs.map(([s, a]) => Math.hypot(s.vx, s.vy) - Math.hypot(a.vx, a.vy))) > 1;
      if ((closure && sustained && excess && current.converging) || episodes >= 2) { risk = 3.8; reasons.push('pursuit_with_intercept_risk'); }
    }
    return [risk, [...new Set(reasons)].sort(), { response_count: responses, closing_m: closingM,
      intercept_episodes: episodes, response_lag_s: responses ? lag : 0 }, current.converging];
  }
  global.Encounters = { assess };
  if (typeof module !== 'undefined') module.exports = global.Encounters;
})(typeof window !== 'undefined' ? window : globalThis);
