/* Shared coverage and mission controller. Inputs are sensor geometry and tracker
 * estimates only; this module never receives hostile ground truth. */
(function (global) {
  'use strict';
  const CELL = 25, SIZE = 1000, SEP = 100, COMFORT = 160, LOOK = 5;
  const ACCEL = 2, YAW_RATE = 20 * Math.PI / 180, LEG_HOLD = 6;
  const clamp = (v) => Math.max(0, Math.min(SIZE, v));
  const wrap = (a) => Math.atan2(Math.sin(a), Math.cos(a));
  function closest(a, av, b, bv, horizon) {
    const x = a.x - b.x, y = a.y - b.y;
    const vx = av.vx - bv.vx, vy = av.vy - bv.vy;
    const vv = vx * vx + vy * vy;
    const t = vv ? Math.max(0, Math.min(horizon, -(x * vx + y * vy) / vv)) : 0;
    return Math.hypot(x + vx * t, y + vy * t);
  }
  function brake(v, dv) {
    const speed = Math.hypot(v.vx, v.vy), scale = speed > dv ? (speed - dv) / speed : 0;
    return { vx: v.vx * scale, vy: v.vy * scale };
  }
  // One commanded step followed by a complete, acceleration-limited stop.
  // The next frame's fallback is exactly the remaining tail of this trajectory.
  function stoppingProfile(d, velocity, dt) {
    let x = d.x, y = d.y, v = velocity;
    const points = [];
    do {
      points.push({ x, y, vx: v.vx, vy: v.vy });
      x += v.vx * dt; y += v.vy * dt;
      v = brake(v, (d.accel || ACCEL) * dt);
    } while (Math.hypot(points.at(-1).vx, points.at(-1).vy) > 1e-9);
    return { points, inBounds: points.every((p) => p.x >= -1e-8 && p.x <= SIZE + 1e-8 && p.y >= -1e-8 && p.y <= SIZE + 1e-8) };
  }
  function profilesClear(a, b, dt) {
    for (let i = 0; i < Math.max(a.points.length, b.points.length); i++) {
      const p = a.points[Math.min(i, a.points.length - 1)], q = b.points[Math.min(i, b.points.length - 1)];
      if (closest(p, p, q, q, dt) < SEP - 1e-7) return false;
    }
    return true;
  }
  class Controller {
    constructor(friendlies, sensors, dt, emit) {
      this.dt = dt; this.sensors = sensors; this.emit = emit || (() => {});
      this.drones = friendlies.map((f) => ({ id: f.id, x: f.x, y: f.y,
        vx: 0, vy: 0, speed: f.v, cruise: f.v, accel: Math.min(ACCEL, f.flight?.max_accel_mps2 ?? ACCEL),
        yawRate: Math.min(YAW_RATE, (f.flight?.max_turn_dps ?? 20) * Math.PI / 180), heading: Math.atan2(500 - f.y, 500 - f.x),
        courseRate: (f.flight?.max_turn_dps ?? 90) * Math.PI / 180,
        mode: 'patrol', target: null, goal: null, cell: null, blocked: false,
        nextPlan: 0, lastEstimate: null, followSensor: null, history: [] }));
      for (let i = 0; i < this.drones.length; i++) for (let j = 0; j < i; j++) {
        if (Math.hypot(this.drones[i].x - this.drones[j].x, this.drones[i].y - this.drones[j].y) < SEP)
          throw new Error('Friendly start positions must be at least ' + SEP + ' m apart');
      }
      this.cells = Array.from({ length: (SIZE / CELL) ** 2 }, (_, i) => ({
        x: (i % 40 + 0.5) * CELL, y: (Math.floor(i / 40) + 0.5) * CELL, last: -1,
      }));
    }
    record(t) {
      this.drones.forEach((d) => d.history.push({ t, x: d.x, y: d.y, vx: d.vx, vy: d.vy, heading: d.heading }));
    }
    state(id, t) {
      const d = this.drones.find((q) => q.id === id);
      if (!d) return null;
      const h = d.history;
      if (!h.length) return { x: d.x, y: d.y, vx: d.vx, vy: d.vy, heading: d.heading };
      const i = Math.min(h.length - 1, Math.max(0, Math.floor(t / this.dt + 1e-8)));
      const a = h[i], b = h[Math.min(i + 1, h.length - 1)];
      const u = b.t > a.t ? Math.max(0, Math.min(1, (t - a.t) / (b.t - a.t))) : 0;
      return { x: a.x + (b.x - a.x) * u, y: a.y + (b.y - a.y) * u,
        vx: a.vx, vy: a.vy, heading: wrap(a.heading + wrap(b.heading - a.heading) * u) };
    }
    command(id, cmd, flight) {
      const d = this.drones.find((q) => q.id === id);
      d.mode = cmd.command === 'return_to_patrol' ? 'patrol' : cmd.command;
      d.target = null; d.cell = null; d.lastEstimate = null; d.nextPlan = 0;
      d.goal = cmd.command === 'goto' ? { x: cmd.target[0], y: cmd.target[1] } :
        cmd.command === 'hold' ? { x: d.x, y: d.y } : null;
      d.speed = d.mode === 'patrol' ? d.cruise : Math.min(flight.max_speed_mps, cmd.speed_mps || flight.max_speed_mps);
      d.commandFace = cmd.face;
    }
    observe(t, k, isAlive = () => true) {
      this.sensors.forEach((s) => {
        const d = this.drones.find((q) => q.id === s.node);
        if (!d || !isAlive(d.id) || k % s.every || s.pd <= 0) return;
        this.cells.forEach((c) => {
          const dx = c.x - d.x, dy = c.y - d.y, r = Math.hypot(dx, dy);
          if (r < s.minRange || r > s.range) return;
          if (s.pointing !== 'omni' && Math.abs(wrap(Math.atan2(dy, dx) - d.heading)) > s.fov / 2) return;
          c.last = t;
        });
      });
    }
    transition(d, mode, target, t) {
      if (d.mode === mode && d.target === target) return;
      if (d.target !== target) d.followSensor = null;
      if (mode === 'search') d.searchHeading = d.heading;
      d.mode = mode; d.target = target; d.cell = null; d.goal = null; d.nextPlan = 0;
      this.emit(t, d.id + ' ' + mode + (target ? ' ' + target.id : ''));
    }
    // Source timestamps are measurement times, not delayed arrival times.
    contact(tr, id) {
      return Object.entries(tr.srcs).filter(([key]) => key.startsWith(id + ' '))
        .reduce((v, [, t]) => Math.max(v, t), -Infinity);
    }
    moduleFor(tr, id) {
      const keys = Object.keys(tr.srcs).filter((key) => key.startsWith(id + ' '))
        .sort((a, b) => tr.srcs[b] - tr.srcs[a] || a.localeCompare(b));
      const kind = keys.length ? keys[0].slice(id.length + 1) : null;
      return this.sensors.find((s) => s.node === id && s.kind === kind);
    }
    update(t, tracks) {
      const active = new Set(tracks);
      this.drones.forEach((d) => {
        if (d.disabled) { this.transition(d, 'offline', null, t); d.lastEstimate = null; d.desiredHeading = d.heading; }
      });
      this.drones.forEach((d) => {
        if (d.mode === 'goto' || d.mode === 'hold') {
          const face = d.commandFace;
          d.desiredHeading = face?.point ? Math.atan2(face.point[1] - d.y, face.point[0] - d.x) :
            face?.heading ?? (Math.hypot(d.vx, d.vy) > 1 ? Math.atan2(d.vy, d.vx) : d.heading);
          return;
        }
        while (d.target && d.target.replacement) d.target = d.target.replacement;
      });
      const owners = new Set();
      this.drones.forEach((d) => {
        if (d.target && owners.has(d.target)) this.transition(d, 'patrol', null, t);
        if (d.target) owners.add(d.target);
      });
      this.drones.forEach((d) => {
        if (!d.target) return;
        const tr = d.target;
        if (tr.kind === 'frd' || tr.cls === 'friendly') {
          this.transition(d, 'patrol', null, t); return;
        }
        const seen = this.contact(tr, d.id);
        if (active.has(tr) && t - seen <= 1 && tr.status === 'confirmed') {
          const e = d.lastEstimate, gain = 1 - Math.exp(-this.dt / 0.8);
          d.lastEstimate = !e ? { x: tr.s[0], y: tr.s[1], vx: tr.s[2], vy: tr.s[3], t } : {
            x: e.x + gain * (tr.s[0] - e.x), y: e.y + gain * (tr.s[1] - e.y),
            vx: e.vx + gain * (tr.s[2] - e.vx), vy: e.vy + gain * (tr.s[3] - e.vy), t };
          this.transition(d, 'follow', tr, t);
        } else {
          if (d.mode !== 'search') {
            d.searchStart = t;
            this.transition(d, 'search', tr, t);
          }
          if (t - d.searchStart >= 10 - 1e-8) this.transition(d, 'patrol', null, t);
        }
      });
      // Search assignments may be handed off to a drone with fresh observations.
      tracks.filter((tr) => tr.kind !== 'frd' && tr.cls !== 'friendly' && tr.status === 'confirmed')
        .forEach((tr) => {
          const owner = this.drones.find((d) => d.target === tr);
          if (owner && owner.mode === 'follow') return;
          const eligible = this.drones.filter((d) => d.mode === 'patrol' && t - this.contact(tr, d.id) <= 1);
          eligible.sort((a, b) => {
            const first = (id) => tr.firstSources && tr.firstSources[id] !== undefined ? tr.firstSources[id] : this.contact(tr, id);
            return first(a.id) - first(b.id) || a.id.localeCompare(b.id);
          });
          if (!eligible.length) return;
          if (owner) this.transition(owner, 'patrol', null, t);
          const d = eligible[0];
          d.lastEstimate = { x: tr.s[0], y: tr.s[1], vx: tr.s[2], vy: tr.s[3], t };
          this.transition(d, 'follow', tr, t);
        });
      this.drones.forEach((d) => {
        if (d.mode === 'patrol') {
          // Seeing a destination while approaching it must not reverse the drone
          // every sensor frame. Commit to a leg, then reassess at 1 Hz.
          if (t < d.nextPlan) return;
          d.nextPlan = t + 1;
          const distance = d.goal ? Math.hypot(d.goal.x - d.x, d.goal.y - d.y) : 0;
          const elapsed = t - (d.assignedAt || 0);
          if (d.cell !== null && !d.blocked && distance > 15 &&
              (elapsed < LEG_HOLD || (this.cells[d.cell].last < d.assignedAt && elapsed < 15))) return;
          const blockedCell = d.blocked ? d.cell : null;
          let best = null, dist = Infinity;
          this.cells.forEach((c, i) => {
            if (i === blockedCell) return;
            const r = Math.hypot(c.x - d.x, c.y - d.y);
            if (r < 80) return; // select useful patrol legs, not adjacent grid centres
            if (this.drones.some((other) => other !== d && (
              Math.hypot(c.x - other.x, c.y - other.y) < COMFORT ||
              (other.goal && Math.hypot(c.x - other.goal.x, c.y - other.goal.y) < COMFORT)))) return;
            if (best === null || c.last < this.cells[best].last || (c.last === this.cells[best].last && r < dist)) {
              best = i; dist = r;
            }
          });
          d.cell = best; d.goal = best === null ? null : { x: this.cells[best].x, y: this.cells[best].y };
          d.assignedAt = t;
        } else if (d.mode === 'follow') {
          const tr = d.target;
          if (!d.followSensor || t - (tr.srcs[d.id + ' ' + d.followSensor.kind] ?? -Infinity) > 2)
            d.followSensor = this.moduleFor(tr, d.id);
          const s = d.followSensor, e = d.lastEstimate;
          const distance = s ? Math.max(s.minRange + 5, s.range * 0.5) : 60;
          const dx = e.x - d.x, dy = e.y - d.y, r = Math.hypot(dx, dy) || 1;
          d.goal = { x: clamp(e.x + e.vx - dx / r * distance), y: clamp(e.y + e.vy - dy / r * distance) };
          d.desiredHeading = Math.atan2(dy, dx);
        } else if (d.lastEstimate) {
          const e = d.lastEstimate, dt = Math.min(3, t - e.t);
          const a = (t - d.searchStart) * Math.PI / 12;
          d.goal = { x: clamp(e.x + e.vx * dt + 40 * Math.cos(a)), y: clamp(e.y + e.vy * dt + 40 * Math.sin(a)) };
          d.desiredHeading = d.searchHeading + (t - d.searchStart) * Math.PI / 18;
        }
      });
    }
    move(t) {
      // Reserve full stopping paths, beginning with the previously guaranteed
      // safe braking fallback. Never assume a moving neighbour can stop instantly.
      const profiles = new Map(this.drones.map((d) => [d, stoppingProfile(d, brake(d, d.accel * this.dt), this.dt)]));
      const chosen = new Map();
      const rank = { offline: -1, hold: 0, goto: 1, follow: 2, search: 3, patrol: 4 };
      const order = this.drones.slice().sort((a, b) => rank[a.mode] - rank[b.mode] || a.id.localeCompare(b.id));
      order.forEach((d) => {
        const dx = d.goal ? d.goal.x - d.x : 0, dy = d.goal ? d.goal.y - d.y : 0;
        const distance = Math.hypot(dx, dy), a = Math.atan2(dy, dx);
        const speed = d.mode === 'hold' || d.disabled ? 0 : Math.min(d.speed, Math.sqrt(2 * d.accel * distance), distance / 2);
        const desired = { vx: Math.cos(a) * speed, vy: Math.sin(a) * speed };
        const preferred = { ...desired };
        this.drones.forEach((other) => {
          if (other === d) return;
          const rx = d.x - other.x, ry = d.y - other.y, r = Math.hypot(rx, ry);
          if (r < COMFORT + 50) {
            const weight = d.speed * Math.max(0, (COMFORT + 50 - r) / (COMFORT + 50 - SEP));
            preferred.vx += rx / r * weight; preferred.vy += ry / r * weight;
          }
        });
        const candidates = [brake(d, d.accel * this.dt), { vx: d.vx, vy: d.vy }];
        const capAcceleration = (v) => {
          const x = v.vx - d.vx, y = v.vy - d.vy, dv = Math.hypot(x, y);
          const scale = dv > d.accel * this.dt ? d.accel * this.dt / dv : 1;
          return { vx: d.vx + x * scale, vy: d.vy + y * scale };
        };
        candidates.push(capAcceleration(preferred), capAcceleration(desired));
        for (let i = 0; i < 16; i++) {
          const angle = a + i * Math.PI / 8;
          candidates.push({ vx: d.vx + Math.cos(angle) * d.accel * this.dt,
            vy: d.vy + Math.sin(angle) * d.accel * this.dt });
        }
        if (d.disabled || d.mode === 'hold') candidates.splice(1);
        candidates.forEach((v) => {
          const ax = (v.vx - d.vx) / this.dt, ay = (v.vy - d.vy) / this.dt;
          v.cost = (v.vx - preferred.vx) ** 2 + (v.vy - preferred.vy) ** 2 +
            0.02 * ((ax - (d.ax || 0)) ** 2 + (ay - (d.ay || 0)) ** 2);
          this.drones.forEach((other) => {
            if (other === d) return;
            const clearance = closest(d, v, other, chosen.get(other) || other, LOOK);
            v.cost += 0.03 * Math.max(0, COMFORT - clearance) ** 2;
          });
        });
        candidates.sort((a, b) => a.cost - b.cost);
        const v = candidates.find((v) => {
          if (Math.hypot(v.vx, v.vy) > Math.max(d.speed, Math.hypot(d.vx, d.vy) - d.accel * this.dt) + 1e-8) return false;
          if (Math.hypot(d.vx, d.vy) > 0.05 && Math.hypot(v.vx, v.vy) > 0.05 &&
              Math.abs(wrap(Math.atan2(v.vy, v.vx) - Math.atan2(d.vy, d.vx))) > d.courseRate * this.dt + 1e-8) return false;
          const profile = stoppingProfile(d, v, this.dt);
          if (!profile.inBounds || !this.drones.every((other) => other === d || profilesClear(profile, profiles.get(other), this.dt))) return false;
          profiles.set(d, profile);
          return true;
        });
        if (!v) throw new Error('No safe motion from a valid separated state');
        d.blocked = speed > 1 && Math.hypot(v.vx, v.vy) < 0.25 && Math.hypot(d.vx, d.vy) < 0.25;
        chosen.set(d, v);
      });
      // Validate continuous motion over this step, rather than endpoints alone.
      this.drones.forEach((d, i) => this.drones.slice(0, i).forEach((b) => {
        if (closest(d, chosen.get(d), b, chosen.get(b), this.dt) < SEP - 1e-7) throw new Error('Unsafe friendly motion');
      }));
      this.drones.forEach((d) => {
        const v = chosen.get(d);
        d.ax = (v.vx - d.vx) / this.dt; d.ay = (v.vy - d.vy) / this.dt;
        d.vx = v.vx; d.vy = v.vy;
        d.x = clamp(d.x + d.vx * this.dt); d.y = clamp(d.y + d.vy * this.dt);
        const desiredHeading = d.mode === 'patrol' ?
          (Math.hypot(d.vx, d.vy) > 1 ? Math.atan2(d.vy, d.vx) : d.heading) : (d.desiredHeading ?? d.heading);
        const delta = wrap(desiredHeading - d.heading);
        d.heading = wrap(d.heading + Math.max(-d.yawRate * this.dt, Math.min(d.yawRate * this.dt, delta)));
      });
    }
    snapshot() {
      return this.drones.map((d) => ({ id: d.id, mode: d.mode, target: d.target ? d.target.id : null,
        destination: d.goal ? { ...d.goal } : null, cell: d.cell, blocked: d.blocked }));
    }
  }
  const api = { Controller, closest, CELL, SIZE, SEP, COMFORT, ACCEL, YAW_RATE };
  global.Missions = api;
  if (typeof module !== 'undefined') module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
