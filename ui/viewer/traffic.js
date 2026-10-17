/* Physical non-cooperative traffic actors for simulation demonstrations.
 * Only the sensing/world side reads these states; inference sees measurements.
 * Actors react to flown ally trajectories, never to estimated flags. */
(function (global) {
  'use strict';
  class Traffic {
    constructor(specs, targets, allies, dt) {
      this.dt = dt; this.actors = new Map();
      (specs || []).forEach((s) => {
        if (this.actors.has(s.id) || !targets.some((t) => t.id === s.id) || !allies.some((f) => f.id === s.ally) ||
            !['follow', 'intercept'].includes(s.mode) || !Number.isFinite(s.start_s) || s.start_s < 0)
          throw new Error('Invalid traffic behavior');
        this.actors.set(s.id, { spec: s, history: [] });
      });
    }
    step(t, state) {
      this.actors.forEach((a) => {
        const s = a.spec;
        if (t < s.start_s) return;
        const current = state(s.ally, t), past = state(s.ally, Math.max(0, t - 2));
        const speed = Math.hypot(past.vx, past.vy), heading = speed > 1 ? Math.atan2(past.vy, past.vx) : past.heading;
        if (!a.history.length) {
          a.x = Math.max(5, Math.min(995, current.x - 140 * Math.cos(heading)));
          a.y = Math.max(5, Math.min(995, current.y - 140 * Math.sin(heading)));
          a.vx = past.vx; a.vy = past.vy;
        } else {
          const dx = current.x - a.x, dy = current.y - a.y, d = Math.hypot(dx, dy);
          // Follow observed course changes with a two-second reaction delay.
          // A weak position correction preserves that delay instead of cutting
          // straight across every turn. Interceptors close the stand-off gap.
          const attacking = s.mode === 'intercept' && t - s.start_s >= 18;
          const trail = attacking ? 20 : 110;
          const closure = (attacking ? 0.06 : 0.02) * (d - trail);
          let vx = past.vx + closure * dx / Math.max(d, 1);
          let vy = past.vy + closure * dy / Math.max(d, 1);
          const cap = Math.min(1, 18 / (Math.hypot(vx, vy) || 1)); vx *= cap; vy *= cap;
          const dvx = vx - a.vx, dvy = vy - a.vy, gain = Math.min(1, 3 * this.dt / (Math.hypot(dvx, dvy) || 1));
          a.vx += gain * dvx; a.vy += gain * dvy;
          a.x += a.vx * this.dt; a.y += a.vy * this.dt;
        }
        a.history.push({ t, x:a.x, y:a.y, vx:a.vx, vy:a.vy });
      });
    }
    state(id, t) {
      const a = this.actors.get(id);
      if (!a || !a.history.length || t < a.history[0].t) return null;
      const i = Math.max(0, Math.min(a.history.length-1, Math.floor((t-a.history[0].t)/this.dt+1e-8)));
      const p = a.history[i], q = a.history[Math.min(i+1,a.history.length-1)];
      const u = q.t > p.t ? Math.max(0, Math.min(1,(t-p.t)/(q.t-p.t))) : 0;
      const result = { x:p.x+(q.x-p.x)*u, y:p.y+(q.y-p.y)*u, vx:p.vx+(q.vx-p.vx)*u, vy:p.vy+(q.vy-p.vy)*u };
      return result.x < 0 || result.x > 1000 || result.y < 0 || result.y > 1000 ? null : result;
    }
  }
  global.Traffic = Traffic;
  if (typeof module !== 'undefined') module.exports = Traffic;
})(typeof window !== 'undefined' ? window : globalThis);
