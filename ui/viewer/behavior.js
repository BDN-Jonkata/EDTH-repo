/* Observed-motion policy. Python reference: drone_behavior/patterns.py.
 * Keep these implementations in step with test-behavior.js shared cases. */
(function (global) {
  'use strict';
  const mean = (a) => a.reduce((s, v) => s + v, 0) / a.length;
  const defaults = { protected_zones: [], corridors: [], window_s: 20, sample_period_s: 0.5,
    min_history_s: 4, max_gap_s: 2, max_sigma_m: 25, min_existence: 0.6, memory_ttl_s: 30 };
  function configFor(c2, overrides) {
    return Object.assign({}, defaults, { protected_zones: [{ x: c2[0], y: c2[1], radius_m: 150 }] }, overrides || {});
  }
  function features(h) {
    const speeds = h.map((s) => Math.hypot(s.vx, s.vy)), turns = [];
    let path = 0;
    for (let i = 1; i < h.length; i++) {
      const a = h[i - 1], b = h[i];
      path += Math.hypot(b.x - a.x, b.y - a.y);
      if (Math.min(speeds[i - 1], speeds[i]) >= 2)
        turns.push(Math.abs(Math.atan2(a.vx * b.vy - a.vy * b.vx, a.vx * b.vx + a.vy * b.vy)) / (b.t - a.t));
    }
    const speed = mean(speeds), first = h[0], last = h.at(-1);
    return { mean_speed_mps: speed, speed_cv: Math.sqrt(mean(speeds.map((v) => (v - speed) ** 2))) / Math.max(speed, 1),
      mean_turn_rad_s: turns.length ? mean(turns) : 0, path_m: path, displacement_m: Math.hypot(last.x - first.x, last.y - first.y) };
  }
  class Model {
    constructor(config, tau = 20, maxDt = 2, evidenceLimit = 4) {
      this.config = Object.assign({}, defaults, config || {}); this.tau = tau; this.maxDt = maxDt;
      this.evidenceLimit = evidenceLimit;
      if (![tau, maxDt, evidenceLimit].every((v) => Number.isFinite(v) && v > 0)) throw new Error('evidence decay and limits must be finite and positive');
      const c = this.config;
      for (const k of ['window_s', 'sample_period_s', 'min_history_s', 'max_gap_s', 'max_sigma_m', 'memory_ttl_s'])
        if (!Number.isFinite(c[k]) || c[k] <= 0) throw new Error(k + ' must be finite and positive');
      if (!(c.min_existence > 0 && c.min_existence <= 1 && c.sample_period_s <= c.max_gap_s && c.max_gap_s <= c.window_s))
        throw new Error('invalid behaviour sampling or existence settings');
      c.protected_zones.forEach((z) => {
        if (![z.x, z.y, z.radius_m].every(Number.isFinite) || z.radius_m <= 0) throw new Error('invalid protected zone');
      });
      c.corridors.forEach((q) => {
        if (!q.start.concat(q.end, [q.half_width_m, q.max_speed_mps ?? 30]).every(Number.isFinite) ||
            Math.hypot(q.end[0] - q.start[0], q.end[1] - q.start[1]) <= 0 || q.half_width_m <= 0 || (q.max_speed_mps ?? 30) <= 0)
          throw new Error('invalid authorized corridor');
      });
      this.now = 0; this.memory = new Map(); this.verified = new Set(); this.profiles = new Map();
    }
    begin(t) {
      if (!Number.isFinite(t) || t < this.now) throw new Error('behaviour time must be finite and monotonic');
      this.now = t;
      this.memory.forEach((m, id) => { if (t - m.seen > this.config.memory_ttl_s) { this.memory.delete(id); this.verified.delete(id); } });
      this.profiles = new Map();
      this.verified.forEach((id) => {
        const h = this.memory.get(id)?.history || [];
        if (h.length >= 2 && h.at(-1).t - h[0].t >= 10) this.profiles.set(id, features(h));
      });
    }
    evidence(tr) {
      const c = this.config, t = this.now;
      if (!this.memory.has(tr.track_id)) this.memory.set(tr.track_id, {
        history: [], obs: -Infinity, eval: -Infinity, llr: 0, called: t, seen: t, result: {},
      });
      const m = this.memory.get(tr.track_id), dt = Math.max(0, Math.min(t - m.called, this.maxDt));
      m.llr *= Math.exp(-dt / this.tau); m.called = t; m.seen = t;
      const obs = tr.observed_t ?? tr.t;
      const valid = [tr.t, obs, tr.pos_sigma, tr.existence_prob, ...tr.position, ...tr.velocity].every(Number.isFinite) &&
        tr.pos_sigma >= 0 && tr.pos_sigma <= c.max_sigma_m && tr.existence_prob >= c.min_existence && tr.existence_prob <= 1;
      const fresh = valid && obs > m.obs + 1e-8 && t - obs >= -0.5 && t - obs <= c.max_gap_s;
      let increment = 0;
      if (fresh && t - m.eval >= c.sample_period_s - 1e-8) {
        let h = m.history;
        if (h.length && (t - h.at(-1).t > c.max_gap_s || obs - m.obs > c.max_gap_s)) h = [];
        m.obs = obs; m.eval = t;
        h.push({ t, x: tr.position[0], y: tr.position[1], vx: tr.velocity[0], vy: tr.velocity[1], sigma: tr.pos_sigma, existence: tr.existence_prob });
        m.history = h = h.filter((s) => t - s.t <= c.window_s + 1e-8);
        const [score, reasons, f] = this.score(tr.track_id, h);
        const quality = mean(h.map((s) => s.existence)) / (1 + (mean(h.map((s) => s.sigma)) / 15) ** 2);
        const target = Math.max(-this.evidenceLimit, Math.min(this.evidenceLimit, score * quality));
        increment = target - m.llr; m.llr = target;
        m.result = { quality, observed_s: h.at(-1).t - h[0].t, reasons, features: f, last_observed_t: t };
      }
      m.result = Object.assign({}, m.result, { llr: m.llr, increment, model_version: 'motion-policy-v1' });
      return increment;
    }
    explain(id) { return Object.assign({}, this.memory.get(id)?.result || {}); }
    score(id, h) {
      const c = this.config, span = h.at(-1).t - h[0].t, f = features(h);
      if (span < c.min_history_s - 1e-8) return [0, ['insufficient_history'], f];
      let risk = 0, outsideAll = true;
      const reasons = [];
      c.protected_zones.forEach((z) => {
        const radius = z.radius_m, ds = h.map((s) => Math.hypot(s.x - z.x, s.y - z.y));
        const inside = ds.map((d, i) => d + 2 * h[i].sigma < radius), outside = ds.map((d, i) => d - 2 * h[i].sigma > radius);
        outsideAll = outsideAll && outside.every(Boolean);
        const last = h.at(-1);
        let start = h.length - 1;
        while (start > 0 && inside[start - 1]) start--;
        const dwell = inside.at(-1) ? last.t - h[start].t : 0;
        if (inside.at(-1) && outside.slice(0, start).some(Boolean) && dwell >= 2 - 1e-8) {
          risk = Math.max(risk, 3.2); reasons.push('sustained_protected_entry');
        }
        if (inside.at(-1) && span >= 12 && inside.filter(Boolean).length / h.length >= 0.8 &&
            (f.mean_speed_mps < 2 || (f.path_m >= 30 && f.displacement_m / Math.max(1, f.path_m) < 0.4))) {
          risk = Math.max(risk, 3); reasons.push('protected_loiter');
        }
        const dx = last.x - z.x, dy = last.y - z.y, speed2 = last.vx ** 2 + last.vy ** 2;
        const ahead = Math.max(0, Math.min(8, -(dx * last.vx + dy * last.vy) / Math.max(speed2, 1)));
        const miss = Math.hypot(dx + last.vx * ahead, dy + last.vy * ahead);
        const closing = -(dx * last.vx + dy * last.vy) / Math.max(ds.at(-1), 1);
        if (closing > 2 && ds[0] - ds.at(-1) > Math.max(20, 4 * last.sigma) && ds.at(-1) < radius + 150 && miss + 2 * last.sigma < radius) {
          risk = Math.max(risk, 1.2); reasons.push('approaching_protected_area');
        }
      });
      if (risk) return [risk, Array.from(new Set(reasons)).sort(), f];
      if (outsideAll && span >= 10) {
        if (c.corridors.some((q) => Model.inCorridor(h, q))) return [-3.2, ['authorized_corridor_transit'], f];
        if (f.speed_cv < 0.15 && f.mean_speed_mps > 2 && f.displacement_m > 0.9 * f.path_m)
          return [-0.7, ['consistent_transit_only'], f];
        for (const otherId of Array.from(this.profiles.keys()).filter((k) => k !== id).sort()) {
          const pf = this.profiles.get(otherId);
          if (Math.abs(pf.mean_speed_mps - f.mean_speed_mps) < 2 && Math.abs(pf.mean_turn_rad_s - f.mean_turn_rad_s) < 0.05)
            return [-0.5, ['resembles_verified_patrol_only'], f];
        }
      }
      return [0, ['ambiguous_motion'], f];
    }
    static inCorridor(h, c) {
      const [ax, ay] = c.start, dx = c.end[0] - ax, dy = c.end[1] - ay, length = Math.hypot(dx, dy), ux = dx / length, uy = dy / length;
      for (const s of h) {
        const px = s.x - ax, py = s.y - ay, along = px * ux + py * uy, across = Math.abs(px * uy - py * ux), speed = Math.hypot(s.vx, s.vy);
        if (along < 2 * s.sigma || along > length - 2 * s.sigma || across + 2 * s.sigma > c.half_width_m ||
            speed <= 2 || speed > (c.max_speed_mps ?? 30) || Math.abs(s.vx * ux + s.vy * uy) / speed < Math.cos(Math.PI / 9)) return false;
      }
      return Math.hypot(h.at(-1).x - h[0].x, h.at(-1).y - h[0].y) >= 40;
    }
  }
  global.Behavior = { Model, configFor };
  if (typeof module !== 'undefined') module.exports = global.Behavior;
})(typeof window !== 'undefined' ? window : globalThis);
