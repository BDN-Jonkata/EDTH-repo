/*
 * Late data for the mock channel (docs/data-formats.md, "Late readings").
 *
 * Every sensor reading a node sends is logged with the time it was taken and, once C2 has it, the time it arrived.
 * A reading that arrives more than StoreFwd.LATE_S after it was taken (a delay burst, or a resend after an outage), or
 * never arrives, is a "late reading". The live tracker does not take it in, but the history can be revised: each
 * late reading is matched with the track it belongs to, as that track was at the time the reading was taken, and
 * gives the position correction a filter would have made had the reading come on time (retrodiction on the
 * recorded track states). The viewer shows the revised timeline next to the one C2 actually had.
 */
(function (global) {
  const GATE = 9.21;      // chi-square, 2 degrees of freedom, 99 %: a late reading must fit its track to be applied
  const TAU_S = 6;        // ASSUMED: a correction fades over this time constant; the live tracker re-converges by itself
  const MIN_SHIFT_M = 0.5;
  const MAX_SHIFT_M = 60; // ASSUMED: a coasting track can be a hundred metres unsure; the correction drawn is capped so a track does not jump across the map
  const ALONG_RAY = 0.3;  // a bearing says nothing about range: along the ray the uncertainty is this share of the distance, squared by the caller
  const r1 = (v) => Math.round(v * 10) / 10;

  // what the viewer needs to draw a reading: where it was taken and what it measured (native form)
  function view(z) {
    const v = { k: z.k, module: z.module, m: z.m, sx: Math.round(z.sx), sy: Math.round(z.sy), rmax: Math.round(z.rmax) };
    if (z.m === 'bearing') Object.assign(v, { b: Math.round(z.b * 1e4) / 1e4, sigB: z.sigB });
    if (z.m === 'rangeaz') Object.assign(v, { b: Math.round(z.b * 1e4) / 1e4, r: r1(z.r), sigB: z.sigB, sigR: z.sigR });
    if (z.m === 'range') Object.assign(v, { r: r1(z.r), sigR: z.sigR });
    return v;
  }

  const createLog = () => ({ byNode: {}, bySeq: {} });
  function logSent(log, node, seq, t, z) {
    const entry = Object.assign({ node, seq, t: r1(t * 10) / 10, arr: null }, view(z));
    (log.byNode[node] = log.byNode[node] || []).push(entry);
    log.bySeq[node + ':' + seq] = entry;
  }
  // first arrival of a logged reading; returns it
  function logArrived(log, node, seq, t) {
    const entry = log.bySeq[node + ':' + seq];
    if (!entry || entry.arr !== null) return null;
    entry.arr = Math.round(t * 100) / 100;
    return entry;
  }
  // the late ones: arrived long after being taken, or not at all. `lateS` = the lateness limit
  function lateReadings(log, lateS) {
    const out = [];
    Object.keys(log.byNode).forEach((n) => log.byNode[n].forEach((e) => { if (e.arr === null || e.arr - e.t > lateS) out.push(e); }));
    return out.sort((a, b) => (a.t - b.t) || (a.node < b.node ? -1 : 1));
  }

  // position fix of a reading as the track sees it; null for a range ring (no direction)
  function fixFor(reading, tr, fixFromRangeAz) {
    if (reading.m === 'rangeaz') return fixFromRangeAz(reading);
    if (reading.m !== 'bearing') return null;
    const d = Math.max(30, Math.hypot(tr.x - reading.sx, tr.y - reading.sy)), c = Math.cos(reading.b), s = Math.sin(reading.b);
    const along = Math.pow(ALONG_RAY * d, 2), across = Math.pow(d * reading.sigB, 2);
    return { x: reading.sx + d * c, y: reading.sy + d * s, R: [along * c * c + across * s * s, (along - across) * c * s, along * s * s + across * c * c] };
  }
  // squared distance of the fix from the track, and the 2-D position update it would give
  function fitOf(tr, fix) {
    const sxx = tr.pxx + fix.R[0], sxy = tr.pxy + fix.R[1], syy = tr.pyy + fix.R[2], det = sxx * syy - sxy * sxy;
    if (det <= 1e-9) return null;
    const ix = fix.x - tr.x, iy = fix.y - tr.y;
    const d2 = (syy * ix * ix - 2 * sxy * ix * iy + sxx * iy * iy) / det;
    const kx = (tr.pxx * syy - tr.pxy * sxy) / det * ix + (-tr.pxx * sxy + tr.pxy * sxx) / det * iy;
    const ky = (tr.pxy * syy - tr.pyy * sxy) / det * ix + (-tr.pxy * sxy + tr.pyy * sxx) / det * iy;
    return { d2, dx: kx, dy: ky };
  }
  // the track a late reading belongs to and the correction it gives, from the frame the reading was taken in
  function reviseOne(reading, frame, fixFromRangeAz) {
    let best = null;
    frame.tracks.forEach((tr) => {
      if (tr.cls === 'friendly') return;
      const fix = fixFor(reading, tr, fixFromRangeAz), fit = fix && fitOf(tr, fix);
      if (fit && fit.d2 <= GATE && (!best || fit.d2 < best.fit.d2)) best = { tr, fit };
    });
    const size = best && Math.hypot(best.fit.dx, best.fit.dy);
    if (!best || size < MIN_SHIFT_M) return null;
    const k = Math.min(1, MAX_SHIFT_M / size);
    return { track: best.tr.id, node: reading.node, t: reading.t, dx: r1(best.fit.dx * k), dy: r1(best.fit.dy * k) };
  }
  // corrections for every late reading that did arrive (frames: the run's recorded frames, DT apart)
  function revise(readings, frames, dt, fixFromRangeAz) {
    const out = [];
    readings.forEach((r) => {
      const frame = r.arr !== null && frames[Math.min(frames.length - 1, Math.round(r.t / dt))];
      const rev = frame && reviseOne(r, frame, fixFromRangeAz);
      if (rev) out.push(rev);
    });
    return out;
  }
  // correction for one track at time `t` (viewer): the average of the corrections so far, older ones weighted less.
  // Each correction is against the recorded track, not against the earlier corrections, so they are averaged, not added;
  // with only old ones left (weights below 1 in all) the correction fades out.
  function shiftAt(revisions, trackId, t) {
    let dx = 0, dy = 0, wsum = 0;
    revisions.forEach((v) => {
      if (v.track !== trackId || v.t > t) return;
      const w = Math.exp(-(t - v.t) / TAU_S);
      dx += v.dx * w; dy += v.dy * w; wsum += w;
    });
    const norm = Math.max(1, wsum);
    return { dx: dx / norm, dy: dy / norm };
  }

  const api = { GATE, TAU_S, createLog, logSent, logArrived, lateReadings, revise, shiftAt, view };
  global.LateData = api;
  if (typeof module !== 'undefined') module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
