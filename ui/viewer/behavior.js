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
    const motion = [[h[0].vx, h[0].vy]], angles = [];
    for (let i = 1; i < h.length; i++) {
      const a = h[i - 1], b = h[i], gain = 1 - Math.exp(-(b.t - a.t) / 1.5), prev = motion.at(-1);
      motion.push([prev[0] + gain * (b.vx - prev[0]), prev[1] + gain * (b.vy - prev[1])]);
    }
    const speeds = motion.map(([vx, vy]) => Math.hypot(vx, vy));
    let path = 0, ix = 0, iy = 0;
    for (let i = 1; i < h.length; i++) {
      const a = h[i - 1], b = h[i];
      path += (speeds[i - 1] + speeds[i]) * (b.t - a.t) / 2;
      ix += (motion[i - 1][0] + motion[i][0]) * (b.t - a.t) / 2; iy += (motion[i - 1][1] + motion[i][1]) * (b.t - a.t) / 2;
      if (Math.min(speeds[i - 1], speeds[i]) >= 2)
        angles.push(Math.atan2(motion[i - 1][0] * motion[i][1] - motion[i - 1][1] * motion[i][0],
          motion[i - 1][0] * motion[i][0] + motion[i - 1][1] * motion[i][1]));
    }
    const speed = mean(speeds), first = h[0], last = h.at(-1);
    const total = angles.reduce((s, a) => s + Math.abs(a), 0), signed = angles.reduce((s, a) => s + a, 0), span = Math.max(last.t - first.t, 0.5);
    return { mean_speed_mps: speed, speed_cv: Math.sqrt(mean(speeds.map((v) => (v - speed) ** 2))) / Math.max(speed, 1),
      course_vx_mps: motion.at(-1)[0], course_vy_mps: motion.at(-1)[1],
      mean_turn_rad_s: total / span, signed_turn_rad_s: signed / span, total_turn_rad: total, turn_coherence: Math.abs(signed) / Math.max(total, 1e-9),
      velocity_consistency: Math.max(0, 1 - Math.hypot(last.x - first.x - ix, last.y - first.y - iy) / Math.max(path, 20)),
      path_m: path, displacement_m: Math.hypot(last.x - first.x, last.y - first.y) };
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
        if (h.length) {
          const p = h.at(-1), elapsed = t - p.t;
          const residual = Math.hypot(tr.position[0] - p.x - p.vx * elapsed, tr.position[1] - p.y - p.vy * elapsed);
          if (residual > Math.max(30, 4 * Math.hypot(p.sigma, tr.pos_sigma) + 5 * elapsed ** 2)) h = [];
        }
        m.obs = obs; m.eval = t;
        h.push({ t, x: tr.position[0], y: tr.position[1], vx: tr.velocity[0], vy: tr.velocity[1], sigma: tr.pos_sigma, existence: tr.existence_prob });
        m.history = h = h.filter((s) => t - s.t <= c.window_s + 1e-8);
        const [score, reasons, f] = this.score(tr.track_id, h);
        const quality = mean(h.map((s) => s.existence)) / (1 + (mean(h.map((s) => s.sigma)) / 15) ** 2);
        const target = Math.max(-this.evidenceLimit, Math.min(this.evidenceLimit, score * quality));
        increment = target - m.llr; m.llr = target;
        m.result = { quality, observed_s: h.at(-1).t - h[0].t, reasons, features: f, last_observed_t: t,
          pattern: h.length >= 2 ? Model.pattern(f) : 'insufficient_history' };
      }
      m.result = Object.assign({}, m.result, { llr: m.llr, increment, model_version: 'motion-policy-v2' });
      return increment;
    }
    explain(id) { return Object.assign({}, this.memory.get(id)?.result || {}); }
    score(id, h) {
      const c = this.config, span = h.at(-1).t - h[0].t, f = features(h);
      if (span < c.min_history_s - 1e-8) return [0, ['insufficient_history'], f];
      let risk = 0, outsideAll = true, safeCourse = true;
      const reasons = [];
      c.protected_zones.forEach((z) => {
        const radius = z.radius_m, ds = h.map((s) => Math.hypot(s.x - z.x, s.y - z.y));
        const inside = ds.map((d, i) => d + 2 * h[i].sigma < radius), outside = ds.map((d, i) => d - 2 * h[i].sigma > radius);
        outsideAll = outsideAll && ds.every((d, i) => d - 2 * h[i].sigma > radius + 40);
        const last = h.at(-1);
        let start = h.length - 1;
        while (start > 0 && inside[start - 1]) start--;
        const dwell = inside.at(-1) ? last.t - h[start].t : 0;
        if (inside.at(-1) && outside.slice(0, start).some(Boolean) && dwell >= 2 - 1e-8) {
          risk = Math.max(risk, 1.5); reasons.push('sustained_protected_entry');
        }
        const loiter = f.mean_speed_mps < 2 || (f.path_m >= 30 && f.displacement_m / Math.max(1, f.path_m) < 0.6 && f.turn_coherence > 0.65);
        if (inside.at(-1) && span >= 8 && inside.filter(Boolean).length / h.length >= 0.6 && loiter) {
          risk = Math.max(risk, 1.8); reasons.push('protected_loiter');
          if (span >= 18 && inside.filter(Boolean).length / h.length >= 0.85 && ds.at(-1) + 2 * last.sigma < 0.7 * radius) {
            risk = Math.max(risk, 3.4); reasons.push('persistent_protected_loiter');
          }
        }
        const entries = [];
        let lastSide = null;
        h.forEach((s, i) => {
          if (outside[i]) lastSide = 'outside';
          else if (inside[i] && lastSide === 'outside') {
            if (!entries.length || s.t - entries.at(-1) >= 4) entries.push(s.t);
            lastSide = 'inside';
          }
        });
        if (entries.length >= 2) {
          risk = Math.max(risk, 3.4); reasons.push('repeated_protected_intrusions');
        }
        const dx = last.x - z.x, dy = last.y - z.y, vx = f.course_vx_mps, vy = f.course_vy_mps, speed2 = vx ** 2 + vy ** 2;
        const ahead = Math.max(0, Math.min(8, -(dx * vx + dy * vy) / Math.max(speed2, 1)));
        const miss = Math.hypot(dx + vx * ahead, dy + vy * ahead);
        const closing = -(dx * vx + dy * vy) / Math.max(ds.at(-1), 1);
        const closestT = Math.max(0, -(dx * vx + dy * vy) / Math.max(speed2, 1));
        const futureMiss = Math.hypot(dx + vx * closestT, dy + vy * closestT);
        const omega = f.signed_turn_rad_s;
        let orbitSafe = false;
        if (f.total_turn_rad >= Math.PI / 2 && f.turn_coherence > 0.75 && Math.abs(omega) >= 0.04) {
          const cx = last.x - vy / omega, cy = last.y + vx / omega;
          orbitSafe = Math.hypot(cx - z.x, cy - z.y) - Math.sqrt(speed2) / Math.abs(omega) - 2 * last.sigma > radius + 40;
        }
        if (!orbitSafe && closestT <= 60 && futureMiss - 2 * last.sigma <= radius + 40) safeCourse = false;
        if (closing > 2 && ds[0] - ds.at(-1) > Math.max(20, 4 * last.sigma) && ds.at(-1) < radius + 150 && miss + 2 * last.sigma < radius) {
          risk = Math.max(risk, 1.2); reasons.push('approaching_protected_area');
        }
      });
      if (risk) return [risk, Array.from(new Set(reasons)).sort(), f];
      if (outsideAll && safeCourse && span >= 10) {
        if (c.corridors.some((q) => Model.inCorridor(h, q))) return [-3.2, ['authorized_corridor_transit'], f];
        if (span >= 15 && f.speed_cv < 0.35 && f.mean_speed_mps > 2 && f.displacement_m > Math.max(60, 0.85 * f.path_m) && f.velocity_consistency > 0.75 && f.mean_turn_rad_s < 0.15)
          return [-3.4 * Math.min(1, (span - 10) / 8), ['sustained_safe_transit', 'protected_area_clearance', 'non_converging_course'], f];
        if (span >= 18 && f.path_m >= 100 && f.speed_cv < 0.3 && f.total_turn_rad >= Math.PI / 2 && f.turn_coherence > 0.75 && f.mean_turn_rad_s >= 0.04 && f.mean_turn_rad_s <= 0.4 && f.velocity_consistency > 0.75)
          return [-3.3, ['consistent_safe_orbit', 'protected_area_clearance'], f];
        if (f.speed_cv < 0.35 && f.mean_speed_mps > 2 && f.displacement_m > 0.85 * f.path_m)
          return [-0.7, ['developing_transit_pattern'], f];
        for (const otherId of Array.from(this.profiles.keys()).filter((k) => k !== id).sort()) {
          const pf = this.profiles.get(otherId);
          if (Math.abs(pf.mean_speed_mps - f.mean_speed_mps) < 2 && Math.abs(pf.mean_turn_rad_s - f.mean_turn_rad_s) < 0.05)
            return [-0.5, ['resembles_verified_patrol_only'], f];
        }
      }
      return [0, ['ambiguous_motion'], f];
    }
    static pattern(f) {
      if (f.mean_speed_mps < 2) return 'hover';
      if (f.total_turn_rad >= Math.PI / 2 && f.turn_coherence > 0.65) return 'orbit';
      if (f.displacement_m > 0.85 * f.path_m && f.speed_cv < 0.35) return 'transit';
      return 'maneuvering';
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
