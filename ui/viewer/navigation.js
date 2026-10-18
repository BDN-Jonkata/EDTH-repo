/*
 * Navigation estimator: each node learns how far its own pose is off and corrects its readings.
 *
 * A node's pose error is a fixed offset e = (ex, ey) of its position and eh of its heading (assumed model, the same
 * one sim.js applies). A friendly drone that broadcasts beacons is a landmark: where it really is, is known to a few
 * metres. When a node's sensor sees a landmark, the gap between what the reading says and what the beacon says
 * measures the node's pose error. A small Kalman filter per node averages these gaps. Only readings and beacons go
 * in, never the ground truth.
 */
(function (global) {
  const D2R = Math.PI / 180;
  const PRIOR = { pos_m: 30, heading_deg: 10 };   // how wrong a node may be before it has learned anything (assumed)
  const GATE = 9;                                   // a gap bigger than 3 standard deviations is not a landmark
  const AMBIGUOUS = 2;                              // the second-best landmark must be this many times farther than the best
  const wrap = (a) => Math.atan2(Math.sin(a), Math.cos(a));

  const create = (nodes) => {
    const est = {};
    nodes.forEach((n) => { est[n] = { e: [0, 0, 0], P: [PRIOR.pos_m ** 2, 0, 0, 0, PRIOR.pos_m ** 2, 0, 0, 0, (PRIOR.heading_deg * D2R) ** 2], n: 0 }; });
    return est;
  };
  const posVar = (s) => (s.P[0] + s.P[4]) / 2;

  // move a reading's believed sensor position and bearing; the same step applies a pose error and takes it back out
  function shiftRecord(rec, dx, dy, dh, compass) {
    rec.sx += dx; rec.sy += dy;
    if (rec.b === undefined || !rec.fields) return;
    rec.b += dh;
    if (rec.fields.bearing_deg !== undefined) rec.fields.bearing_deg = compass(rec.b);
    if (rec.fields.azimuth_deg !== undefined) rec.fields.azimuth_deg = compass(rec.b);
  }

  // a reading as the node's current estimate corrects it, with the estimate's own uncertainty added to its noise
  function correct(est, rec, compass) {
    const s = est[rec.node];
    if (!s) return;
    shiftRecord(rec, -s.e[0], -s.e[1], -s.e[2], compass);
    const posSd = Math.sqrt(posVar(s));
    if (rec.sigB !== undefined) {
      const dist = rec.r !== undefined ? rec.r : (rec.rmax || 200) / 2;
      rec.sigB = Math.hypot(rec.sigB, Math.sqrt(s.P[8]), posSd / Math.max(dist, 20));
      if (rec.sd) { if (rec.sd.bearing_deg !== undefined) rec.sd.bearing_deg = rec.sigB / D2R; if (rec.sd.azimuth_deg !== undefined) rec.sd.azimuth_deg = rec.sigB / D2R; }
    }
    if (rec.sigR !== undefined) { rec.sigR = Math.hypot(rec.sigR, posSd); if (rec.sd && rec.sd.range_m !== undefined) rec.sd.range_m = rec.sigR; }
  }

  // one scalar update of [ex, ey, eh]; false when the gap does not fit the estimate (a mismatch, not a landmark)
  function update(s, res, H, R) {
    const P = s.P, PH = [0, 1, 2].map((i) => H[0] * P[i * 3] + H[1] * P[i * 3 + 1] + H[2] * P[i * 3 + 2]);
    const S = H[0] * PH[0] + H[1] * PH[1] + H[2] * PH[2] + R;
    if (res * res / S > GATE) return false;
    const K = PH.map((v) => v / S);
    for (let i = 0; i < 3; i++) s.e[i] += K[i] * res;
    for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) P[i * 3 + j] -= K[i] * PH[j];
    return true;
  }

  // where the reading puts a landmark, or how far off in angle, under the node's current estimate
  function gap(s, rec, L) {
    const dx = L.x - rec.sx + s.e[0], dy = L.y - rec.sy + s.e[1];
    if (rec.m === 'rangeaz') {
      const r = rec.r, b = rec.b - s.e[2];
      return Math.hypot(dx - r * Math.cos(b), dy - r * Math.sin(b));
    }
    return Math.abs(wrap(rec.b - s.e[2] - Math.atan2(dy, dx))) * Math.hypot(dx, dy);
  }

  // the one landmark this reading most plausibly shows, or null when none is close enough or two are about as close
  function pickLandmark(s, rec, landmarks) {
    const near = landmarks.filter((L) => L.id !== rec.node).map((L) => ({ L, d: gap(s, rec, L) })).sort((a, b) => a.d - b.d);
    if (!near.length) return null;
    const reach = 3 * Math.sqrt(4 * posVar(s) + 2 * (rec.r || rec.rmax / 2) ** 2 * (s.P[8] + (rec.sigB || 0.05) ** 2)) + 30;
    if (near[0].d > reach || (near.length > 1 && near[1].d < AMBIGUOUS * near[0].d)) return null;
    return near[0].L;
  }

  // landmarks: [{ id, x, y, sd }] friendly positions from fresh beacons. Call with the reading as the sensor made it.
  function observe(est, rec, landmarks) {
    const s = est[rec.node];
    if (!s || (rec.m !== 'bearing' && rec.m !== 'rangeaz') || rec.clutter) return;
    const L = pickLandmark(s, rec, landmarks);
    if (!L) return;
    const dx = L.x - rec.sx + s.e[0], dy = L.y - rec.sy + s.e[1], r2 = Math.max(dx * dx + dy * dy, 1), r = Math.sqrt(r2);
    const used = [update(s, wrap(rec.b - (Math.atan2(dy, dx) + s.e[2])), [-dy / r2, dx / r2, 1], rec.sigB ** 2 + (L.sd / r) ** 2)];
    if (rec.m === 'rangeaz') used.push(update(s, rec.r - r, [dx / r, dy / r, 0], rec.sigR ** 2 + L.sd ** 2));
    if (used.some(Boolean)) s.n += 1;
  }

  const api = { create, observe, correct, shiftRecord };
  global.Navigation = api;
  if (typeof module !== 'undefined') module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
