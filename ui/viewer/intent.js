/*
 * Intent from motion, learned while the run goes on. It never reads the truth and is trained on nothing recorded in advance.
 *
 * A track is described by where its course takes it relative to what is defended (C2, the ground sensors, the friendly
 * drones): the closest point it will reach on its present course, how fast it closes, how far it is, how it turns, and whether
 * it loiters near them. A logistic score turns that into the chance that it is going for the defended area.
 *
 * It starts from a physical prior (a course through the defended area is hostile, one that passes by is not) and then learns
 * from what the run shows afterwards: a track that came within ENGAGE_M of something defended is a positive example (its
 * features from when it was first well observed), a track that lived LIFE_S and left without doing so is a negative one.
 * The label is the later outcome, so the model learns to predict it early. Every track therefore teaches the next one.
 */
(function (global) {
  const CFG = {
    engage_m: 60,          // within this of a defended point counts as having come for it
    life_s: 25,            // a track this old that never did is a negative example
    snapshot_s: 8,         // the features are taken when a track has been watched this long
    horizon_s: 60,         // how far ahead the closest point is looked for
    hover_mps: 1.5,
    lr: 0.08,              // learning rate
    pull: 0.01,            // how strongly the weights are drawn back to the prior
    // Hostile from the course alone is off (a threshold above 1): measured on the seeds, the course of a hostile and of a harmless
    // drone overlap too much, and turning it on called harmless drones hostile in 27 % of their time against 5 % without it.
    // Peaceful from the course is on: harmless drones got it 22 % of their time, real hostiles 1 %.
    hostile_p: 1.01, peaceful_p: 0.3, hostile_after_s: 8, peaceful_after_s: 20,
    // Not on any known plan and going for the defended area soon is a threat: do not wait for proof of intent.
    reach_s: 30, pass_m: 100, zone_through: 0.6,   // a course through the middle 60 % of the zone counts; one that only clips its edge does not
 closing_mps: 3, threat_after_s: 4,
    plan_m: 50, plan_keep_s: 4,   // within plan_m of the planned position for plan_keep_s is keeping to the plan
  };
  //                bias  cpa   closing  range  speed  loiter turn
  const PRIOR = [1.2, -2.6, 1.6, -0.8, 0.2, 1.5, 0.4];
  const clip = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const sigmoid = (z) => 1 / (1 + Math.exp(-z));

  // closest point of a straight course to a point, within the horizon
  function closest(px, py, vx, vy, ax, ay, horizon) {
    const dx = ax - px, dy = ay - py, v2 = vx * vx + vy * vy;
    const tc = v2 < 1e-6 ? 0 : clip((dx * vx + dy * vy) / v2, 0, horizon);
    return { cpa: Math.hypot(dx - vx * tc, dy - vy * tc), range: Math.hypot(dx, dy), closing: v2 < 1e-6 ? 0 : (dx * vx + dy * vy) / Math.hypot(dx, dy) };
  }

  // Seconds until a track reaches the defended area on its present course, if it is going to: it must pass within
  // `pass_m` of a defended point and be closing at `closing_mps` or more. Infinity when it is not going there.
  function timeToReach(tr, assets, cfg) {
    let best = Infinity;
    assets.forEach((a) => {
      const r = closest(tr.s[0], tr.s[1], tr.s[2], tr.s[3], a.x, a.y, cfg.horizon_s);
      const reach = a.r || cfg.engage_m;   // a zone has a radius; a point (a drone) is reached within engage_m
      if (r.cpa <= (a.r ? cfg.zone_through * a.r : a.pass || cfg.pass_m) && r.closing >= cfg.closing_mps) best = Math.min(best, Math.max(0, r.range - reach) / r.closing);
    });
    return best;
  }

  // Flight plans the base knows ([t, x, y] waypoints). A track that keeps to one is expected traffic, never a threat.
  class Plans {
    constructor(routes, cfg) {
      this.routes = routes || [];
      this.cfg = { ...CFG, ...cfg };
      this.kept = new Map();   // track id -> {route id, seconds it has kept to the plan}
    }
    plannedAt(route, t) {
      const w = route.waypoints;
      for (let i = 0; i + 1 < w.length; i++) {
        if (t >= w[i][0] && t <= w[i + 1][0]) {
          const f = w[i + 1][0] === w[i][0] ? 0 : (t - w[i][0]) / (w[i + 1][0] - w[i][0]);
          return { x: w[i][1] + f * (w[i + 1][1] - w[i][1]), y: w[i][2] + f * (w[i + 1][2] - w[i][2]) };
        }
      }
      return null;
    }
    // the plan this track has kept to for `plan_keep_s`, or null
    update(t, dt, tracks) {
      const out = new Map();
      tracks.filter((tr) => tr.kind !== 'frd').forEach((tr) => {
        const on = this.routes.find((r) => { const p = this.plannedAt(r, t); return p && Math.hypot(p.x - tr.s[0], p.y - tr.s[1]) <= this.cfg.plan_m; });
        const prev = this.kept.get(tr.id) || { route: null, s: 0 };
        const s = on ? prev.s + dt : Math.max(0, prev.s - 2 * dt);
        this.kept.set(tr.id, { route: on ? on.id : prev.route, s });
        if (s >= this.cfg.plan_keep_s) out.set(tr.id, this.kept.get(tr.id).route);
      });
      return out;
    }
  }

  function features(st, tr, assets) {
    let best = null;
    assets.forEach((a) => {
      const r = closest(tr.s[0], tr.s[1], tr.s[2], tr.s[3], a.x, a.y, CFG.horizon_s);
      if (!best || r.cpa < best.cpa) best = r;
    });
    const range = Math.min(...assets.map((a) => Math.hypot(a.x - tr.s[0], a.y - tr.s[1])));
    const hoverFrac = st.watched > 0 ? st.hovering / st.watched : 0;
    return [1, clip(best.cpa, 0, 500) / 250, clip(best.closing, -10, 10) / 10, clip(range, 0, 600) / 300,
      clip(Math.hypot(tr.s[2], tr.s[3]), 0, 20) / 15, hoverFrac * (1 - clip(range, 0, 300) / 300), clip(st.turn, 0, 20) / 20];
  }

  class Learner {
    constructor(config) {
      this.cfg = { ...CFG, ...config };
      this.w = PRIOR.slice();
      this.stats = new Map();   // track id -> what has been seen of it
      this.taught = 0;
    }
    score(x) { return sigmoid(x.reduce((s, v, i) => s + v * this.w[i], 0)); }
    learn(x, label) {
      const err = label - this.score(x);
      this.w = this.w.map((w, i) => w + this.cfg.lr * err * x[i] - this.cfg.pull * (w - PRIOR[i]));
      this.taught++;
    }
    // one frame: tracks are [{id, s: [x, y, vx, vy], kind}], assets [{x, y}]; returns the verdict of each non-friendly track
    update(t, dt, tracks, assets) {
      const seen = new Set(), verdicts = new Map();
      tracks.filter((tr) => tr.kind !== 'frd').forEach((tr) => {
        seen.add(tr.id);
        const st = this.stats.get(tr.id) || this.start(tr, t);
        this.observe(st, tr, dt, assets);
        const x = features(st, tr, assets);
        if (!st.snap && st.watched >= this.cfg.snapshot_s) st.snap = x;
        if (st.snap && st.approached && !st.taught) { st.taught = true; this.learn(st.snap, 1); }
        verdicts.set(tr.id, { p: this.score(x), watched: st.watched, approached: st.approached, reach: timeToReach(tr, assets, this.cfg) });
      });
      this.retire(seen);
      return verdicts;
    }
    start(tr, t) {
      const st = { watched: 0, hovering: 0, turn: 0, heading: null, approached: false, taught: false, snap: null };
      this.stats.set(tr.id, st);
      return st;
    }
    observe(st, tr, dt, assets) {
      st.watched += dt;
      const speed = Math.hypot(tr.s[2], tr.s[3]);
      if (speed < this.cfg.hover_mps) st.hovering += dt;
      if (speed > this.cfg.hover_mps) {
        const h = Math.atan2(tr.s[3], tr.s[2]);
        if (st.heading !== null) {
          const d = Math.abs(Math.atan2(Math.sin(h - st.heading), Math.cos(h - st.heading))) * 180 / Math.PI / dt;
          st.turn += 0.05 * (d - st.turn);
        }
        st.heading = h;
      }
      if (assets.some((a) => Math.hypot(a.x - tr.s[0], a.y - tr.s[1]) < (a.r || this.cfg.engage_m))) st.approached = true;
    }
    // a track that is gone after a long life without coming near anything defended is a negative example
    retire(seen) {
      this.stats.forEach((st, id) => {
        if (seen.has(id)) return;
        if (st.snap && !st.taught && !st.approached && st.watched >= this.cfg.life_s) this.learn(st.snap, 0);
        this.stats.delete(id);
      });
    }
    // the class this evidence supports, or null while there is not enough of it
    verdict(v) {
      if (!v) return null;
      if (v.reach <= this.cfg.reach_s && v.watched >= this.cfg.threat_after_s) return 'hostile';
      if (v.p >= this.cfg.hostile_p && v.watched >= this.cfg.hostile_after_s) return 'hostile';
      if (v.p <= this.cfg.peaceful_p && v.watched >= this.cfg.peaceful_after_s && !v.approached) return 'peaceful';
      return null;
    }
  }

  const api = { CFG, PRIOR, Learner, Plans, features, closest, timeToReach };
  global.Intent = api;
  if (typeof module !== 'undefined') module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
