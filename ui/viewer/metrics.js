/* Evaluation only. Truth enters here after inference; never feed these matches
 * back into the tracker, assessment, investigation or mission controllers. */
(function (global) {
  'use strict';
  const GATE_M = 60;
  const MIN_HEADING_SPEED_MPS = 1;

  // Maximum-cardinality gated assignment, then minimum squared position error.
  // Dummy columns let estimates remain unmatched. No identity/continuity bonus:
  // two tracks trading objects through a crossing must remain observable.
  function assign(tracks, truth, gate = GATE_M) {
    if (!tracks.length || !truth.length) return [];
    const rows = tracks.slice().sort((a, b) => a.id.localeCompare(b.id));
    const cols = truth.slice().sort((a, b) => a.id.localeCompare(b.id));
    const n = rows.length, m = cols.length + n;
    const unmatched = (n + 1) * gate * gate + 1, invalid = unmatched * (n + 1);
    const costs = rows.map((a) => cols.map((b) => {
      const d2 = (a.x-b.x)**2 + (a.y-b.y)**2;
      return d2 < gate*gate ? d2 : invalid;
    }).concat(Array(n).fill(unmatched)));
    // Rectangular Hungarian assignment, with rows <= columns.
    const u = Array(n+1).fill(0), v = Array(m+1).fill(0);
    const p = Array(m+1).fill(0), way = Array(m+1).fill(0);
    for (let i = 1; i <= n; i++) {
      p[0] = i;
      let j0 = 0;
      const minv = Array(m+1).fill(Infinity), used = Array(m+1).fill(false);
      do {
        used[j0] = true;
        const i0 = p[j0];
        let delta = Infinity, j1 = 0;
        for (let j = 1; j <= m; j++) if (!used[j]) {
          const current = costs[i0-1][j-1] - u[i0] - v[j];
          if (current < minv[j]) { minv[j] = current; way[j] = j0; }
          if (minv[j] < delta) { delta = minv[j]; j1 = j; }
        }
        for (let j = 0; j <= m; j++) {
          if (used[j]) { u[p[j]] += delta; v[j] -= delta; }
          else minv[j] -= delta;
        }
        j0 = j1;
      } while (p[j0] !== 0);
      do { const j1 = way[j0]; p[j0] = p[j1]; j0 = j1; } while (j0 !== 0);
    }
    const pairs = [];
    for (let j = 1; j <= cols.length; j++) {
      const i = p[j];
      if (i && costs[i-1][j-1] < gate*gate) pairs.push({
        track: rows[i-1], truth: cols[j-1], distance: Math.sqrt(costs[i-1][j-1]),
      });
    }
    return pairs;
  }

  function errors(pairs) {
    let positionSq = 0, velocitySq = 0, headingSq = 0, headingN = 0;
    pairs.forEach(({track:a, truth:b, distance}) => {
      positionSq += distance*distance;
      velocitySq += (a.vx-b.vx)**2 + (a.vy-b.vy)**2;
      if (Math.hypot(a.vx,a.vy) >= MIN_HEADING_SPEED_MPS && Math.hypot(b.vx,b.vy) >= MIN_HEADING_SPEED_MPS) {
        const d = Math.atan2(a.vy,a.vx) - Math.atan2(b.vy,b.vx);
        const degrees = Math.atan2(Math.sin(d),Math.cos(d)) * 180/Math.PI;
        headingSq += degrees*degrees; headingN++;
      }
    });
    return {positionSq, velocitySq, headingSq, headingN, n:pairs.length};
  }

  function aggregate(entries) {
    const sum = entries.reduce((a,e) => {
      for (const key of ['positionSq','velocitySq','headingSq','headingN','n']) a[key] += e[key];
      return a;
    }, {positionSq:0,velocitySq:0,headingSq:0,headingN:0,n:0});
    return {
      rmse:sum.n ? Math.sqrt(sum.positionSq/sum.n) : null,
      velocityRmse:sum.n ? Math.sqrt(sum.velocitySq/sum.n) : null,
      headingRmseDeg:sum.headingN ? Math.sqrt(sum.headingSq/sum.headingN) : null,
      matchedSamples:sum.n,
    };
  }

  const api = {GATE_M,MIN_HEADING_SPEED_MPS,assign,errors,aggregate};
  global.Metrics = api;
  if (typeof module !== 'undefined') module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
