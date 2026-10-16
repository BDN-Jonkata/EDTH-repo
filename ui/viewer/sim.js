/*
 * Mock drone-defense simulation + baseline tracker for the viewer.
 *
 * Runs the whole 120 s scenario up front (deterministic for a given seed) and
 * returns an array of frames the viewer replays. World coordinates are metres,
 * x = East, y = North, origin bottom-left of the 1 km x 1 km area.
 *
 * Each node (5 friendly drones, 2 ground sensors) is built from a platform in
 * the catalog (catalog.js, generated from seeder/catalog/*.json), so sensor
 * numbers and weather effects come from there. The platform of each node is
 * chosen with params.assign.
 *
 * This is a stand-in for the real modules (seeder, simulation, sensors,
 * tracker, fusion, friend_foe). Simplifications are marked "MOCK".
 */
(function (global) {
  'use strict';

  const CAT = typeof CATALOG !== 'undefined' ? CATALOG : require('./catalog.js'); // eslint-disable-line no-undef
  const DT = 0.1;
  const T_END = 120;
  const NF = Math.round(T_END / DT);
  const EVAL = [45, 90]; // default; each run uses the window around its own crossing
  const D2R = Math.PI / 180;
  const GATE = 9.21; // chi-square, 2 dof, 99 %
  const KIND = { eo_camera: 'EO', thermal_camera: 'IR', microphone: 'MIC', rf_receiver: 'RF', radar: 'RAD' };
  const NO_EFFECT = { range_mult: 1, noise_mult: 1, pd_mult: 1 };
  const RAD2DEG = 180 / Math.PI;
  const ALT = { friendly: 60, hostile: 80, ground: 5 }; // metres, only used for elevation angles
  const wrapPi = (a) => Math.atan2(Math.sin(a), Math.cos(a));
  const compass = (mathRad) => ((90 - mathRad * RAD2DEG) % 360 + 360) % 360; // 0 = north, clockwise
  const G_BEARING = 6.63; // chi-square, 1 dof, 99 %
  const WEATHERS = ['clear', 'fog', 'rain', 'wind', 'night'];

  // ---------------------------------------------------------------- scenario
  // A scenario comes from the seeder (seeder/scenario.py, exported to scenarios.js or served by serve.py):
  // friendly patrol loops, ground sensors, hostile waypoint paths, environment and degradations.
  const DEFAULT_SCENARIO = typeof SCENARIOS !== 'undefined' ? SCENARIOS.challenge : require('./scenarios.js').challenge; // eslint-disable-line no-undef
  const SIG_KEY = { EO: 'eo', IR: 'thermal', MIC: 'acoustic', RF: 'rf', RAD: 'radar' };

  function prepare(sc) {
    const world = {
      id: sc.id, name: sc.name, duration: sc.duration_s, c2: { x: sc.c2[0], y: sc.c2[1] },
      ground: sc.ground.map((g) => ({ id: g.id, platform: g.platform, x: g.position[0], y: g.position[1], heading: (90 - g.heading_deg) * D2R })),
      friendlies: sc.friendlies.map((f) => Object.assign({ id: f.id, platform: f.platform, alt: f.altitude_m }, f.loop)),
      hostiles: sc.targets.map((t) => ({ id: t.id, wps: t.waypoints, wob: t.wobble_m, ph: t.phase, alt: t.altitude_m, sig: t.signature || {}, emits: t.emits !== false })),
      beacon: sc.beacon, env: sc.environment, deg: sc.degradations, sensorKinds: sc.sensor_set.enabled_kinds, assign: {},
    };
    sc.friendlies.concat(sc.ground).forEach((n) => { world.assign[n.id] = n.platform; });
    const cr = sc.config && sc.config.targets && sc.config.targets.crossing;
    const tc = cr && cr.enabled ? cr.t : sc.duration_s / 2;
    world.eval = [Math.max(0, tc - 6), Math.min(sc.duration_s, tc + 39)]; // window around the crossing used for summary metrics
    return world;
  }

  function frState(f, t) {
    const a = f.th0 + f.dir * (f.v / f.R) * t;
    return {
      x: f.cx + f.R * Math.cos(a), y: f.cy + f.R * Math.sin(a),
      vx: -f.dir * f.v * Math.sin(a), vy: f.dir * f.v * Math.cos(a),
    };
  }
  // piecewise-linear path with a sideways wobble (same maths as seeder/scenario.py)
  function hoPos(h, t) {
    const w = h.wps;
    let i = 0;
    while (i < w.length - 2 && t > w[i + 1][0]) i++;
    const t0 = w[i][0], x0 = w[i][1], y0 = w[i][2], t1 = w[i + 1][0], x1 = w[i + 1][1], y1 = w[i + 1][2];
    const s = t1 === t0 ? 0 : (t - t0) / (t1 - t0), dx = x1 - x0, dy = y1 - y0, seg = Math.hypot(dx, dy);
    let x = x0 + dx * s, y = y0 + dy * s;
    if (seg > 1e-6) { // no wobble while hovering; it fades out at each waypoint so turns stay continuous
      const taper = Math.max(0, Math.min(1, (t - t0) / 2, (t1 - t) / 2));
      const wv = h.wob * taper * Math.sin(0.35 * (t - w[0][0]) + h.ph);
      x -= (dy / seg) * wv; y += (dx / seg) * wv;
    }
    return { x, y };
  }
  function hoState(h, t) {
    const w = h.wps;
    if (t < w[0][0] || t > w[w.length - 1][0]) return null;
    const a = hoPos(h, t - 0.05), b = hoPos(h, t + 0.05), p = hoPos(h, t);
    if (p.x < 0 || p.x > 1000 || p.y < 0 || p.y > 1000) return null;
    return { x: p.x, y: p.y, vx: (b.x - a.x) / 0.1, vy: (b.y - a.y) / 0.1 };
  }

  // ----------------------------------------------------------------- sensors
  // MOCK: every sensor reports a position fix with an honest covariance
  // (long along the line of sight for bearing-type sensors). Numbers come from
  // the catalog module's `sim` block, scaled by its weather effect.
  const MODULES = {};
  CAT.modules.forEach((m) => { MODULES[m.id] = m; });
  const PLATFORMS = {};
  CAT.platforms.forEach((p) => { PLATFORMS[p.id] = p; });

  function rng(seed) {
    let a = seed >>> 0;
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function gauss(r) {
    let u = 0;
    while (!u) u = r();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * r());
  }

  function buildSensors(assign, weather, kinds) {
    const list = [];
    Object.keys(assign).forEach((node) => {
      const plat = PLATFORMS[assign[node]];
      if (!plat) throw new Error('Unknown platform for ' + node + ': ' + assign[node]);
      plat.modules.forEach((link) => {
        const m = MODULES[link.module_id];
        if (!KIND[m.kind] || kinds.indexOf(m.kind) < 0) return; // gnss / imu are not detection sensors; the scenario can switch kinds off
        const eff = (m.weather_effects && m.weather_effects[weather]) || NO_EFFECT;
        const sm = m.sim;
        list.push({
          node, module: m.id, kind: KIND[m.kind],
          range: sm.range_m * eff.range_mult,
          minRange: sm.min_range_m,
          fov: sm.fov_deg * D2R,
          pointing: sm.pointing,
          every: Math.max(1, Math.round(10 / sm.rate_hz)),
          latency: sm.latency_ms / 1000,
          native: m.native.type,
          fields: m.native.fields.map((f) => f.name),
          pd: Math.min(1, sm.pd * eff.pd_mult),
          pdFar: sm.pd_far,
          nm: eff.noise_mult,
          noise: sm.noise,
          cell: sm.resolution_cell || null,
          clutter: m.kind === 'radar' ? (eff.clutter_rate_per_s || 0.05) : 0,
        });
      });
    });
    return list;
  }

  // ----------------------------------------------------------- Kalman filter
  // State [x y vx vy], row-major 4x4 covariance, position-only measurements.
  function newTrack(id, kind, z, q, velVar) {
    const P = new Float64Array(16);
    P[0] = z.R[0]; P[1] = z.R[1]; P[4] = z.R[1]; P[5] = z.R[2];
    P[10] = velVar; P[15] = velVar;
    return {
      id, kind, q, s: [z.x, z.y, 0, 0], P, hitFrames: 0, born: z.t, lastUpd: z.t,
      status: kind === 'frd' ? 'confirmed' : 'tentative', srcs: {}, alerted: false, ffa: false,
    };
  }
  function predict(tr, dt) {
    const P = tr.P, s = tr.s;
    s[0] += s[2] * dt; s[1] += s[3] * dt;
    for (let j = 0; j < 4; j++) { P[j] += dt * P[8 + j]; P[4 + j] += dt * P[12 + j]; }
    for (let i = 0; i < 4; i++) { P[i * 4] += dt * P[i * 4 + 2]; P[i * 4 + 1] += dt * P[i * 4 + 3]; }
    const q = tr.q, d2 = dt * dt, d3 = d2 * dt, d4 = d3 * dt;
    P[0] += q * d4 / 4; P[5] += q * d4 / 4;
    P[2] += q * d3 / 2; P[8] += q * d3 / 2; P[7] += q * d3 / 2; P[13] += q * d3 / 2;
    P[10] += q * d2; P[15] += q * d2;
  }
  function innov(tr, z) {
    const P = tr.P;
    const a = P[0] + z.R[0], b = P[1] + z.R[1], c = P[5] + z.R[2];
    const det = a * c - b * b;
    const y0 = z.x - tr.s[0], y1 = z.y - tr.s[1];
    const i00 = c / det, i01 = -b / det, i11 = a / det;
    return { d2: y0 * (i00 * y0 + i01 * y1) + y1 * (i01 * y0 + i11 * y1), det, y0, y1, i00, i01, i11 };
  }
  function update(tr, z, n) {
    const P = tr.P, s = tr.s;
    const K = [];
    for (let i = 0; i < 4; i++) {
      K.push([P[i * 4] * n.i00 + P[i * 4 + 1] * n.i01, P[i * 4] * n.i01 + P[i * 4 + 1] * n.i11]);
    }
    for (let i = 0; i < 4; i++) s[i] += K[i][0] * n.y0 + K[i][1] * n.y1;
    const r0 = [P[0], P[1], P[2], P[3]], r1 = [P[4], P[5], P[6], P[7]];
    for (let i = 0; i < 4; i++) {
      for (let j = 0; j < 4; j++) P[i * 4 + j] -= K[i][0] * r0[j] + K[i][1] * r1[j];
    }
    for (let i = 0; i < 4; i++) for (let j = i + 1; j < 4; j++) { const m = (P[i * 4 + j] + P[j * 4 + i]) / 2; P[i * 4 + j] = P[j * 4 + i] = m; }
  }

  // Native measurements are scalars: bearing (rad), range (m) and radial speed (m/s).
  // Each returns the residual, its Jacobian row H (over x y vx vy) and noise variance.
  function scalarModel(tr, rec, which) {
    const dx = tr.s[0] - rec.sx, dy = tr.s[1] - rec.sy;
    const r2 = Math.max(dx * dx + dy * dy, 1), r = Math.sqrt(r2);
    if (which === 'b') return { res: wrapPi(rec.b - Math.atan2(dy, dx)), H: [-dy / r2, dx / r2, 0, 0], R: rec.sigB * rec.sigB };
    if (which === 'r') return { res: rec.r - r, H: [dx / r, dy / r, 0, 0], R: rec.sigR * rec.sigR };
    const vx = tr.s[2] - rec.svx, vy = tr.s[3] - rec.svy, dot = dx * vx + dy * vy; // radial speed relative to the sensor
    return {
      res: rec.rr - dot / r,
      H: [vx / r - (dx * dot) / (r2 * r), vy / r - (dy * dot) / (r2 * r), dx / r, dy / r],
      R: rec.sigRR * rec.sigRR,
    };
  }
  function scalarS(tr, H, R) {
    const P = tr.P;
    let s = R;
    for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) s += H[i] * P[i * 4 + j] * H[j];
    return s;
  }
  function scalarUpdate(tr, mdl) {
    const P = tr.P, H = mdl.H;
    const PH = [0, 0, 0, 0];
    for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) PH[i] += P[i * 4 + j] * H[j];
    const S = scalarS(tr, H, mdl.R);
    const K = PH.map((v) => v / S);
    for (let i = 0; i < 4; i++) tr.s[i] += K[i] * mdl.res;
    for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) P[i * 4 + j] -= K[i] * PH[j];
    for (let i = 0; i < 4; i++) for (let j = i + 1; j < 4; j++) { const m = (P[i * 4 + j] + P[j * 4 + i]) / 2; P[i * 4 + j] = P[j * 4 + i] = m; }
  }
  // which scalars gate a record, and how strict the gate is
  const GATE_PARTS = { bearing: ['b'], range: ['r'], rangeaz: ['r', 'b'] };
  function gateRecord(tr, rec) {
    const parts = GATE_PARTS[rec.m];
    let d2 = 0, logS = 0;
    parts.forEach((w) => {
      const mdl = scalarModel(tr, rec, w), S = scalarS(tr, mdl.H, mdl.R);
      d2 += (mdl.res * mdl.res) / S; logS += Math.log(S);
    });
    if (d2 > (parts.length === 1 ? G_BEARING : GATE)) return null;
    return d2 + logS; // likelihood-style score: a wide track must not beat a precise one
  }
  function applyRecord(tr, rec) {
    GATE_PARTS[rec.m].forEach((w) => scalarUpdate(tr, scalarModel(tr, rec, w)));
    if (rec.m === 'rangeaz') scalarUpdate(tr, scalarModel(tr, rec, 'rr'));
  }
  // position fix from a record that has range and bearing (radar)
  function fixFromRangeAz(rec) {
    const c = Math.cos(rec.b), sn = Math.sin(rec.b), sr = rec.sigR, sp = rec.r * rec.sigB;
    return { x: rec.sx + rec.r * c, y: rec.sy + rec.r * sn, R: [sr * sr * c * c + sp * sp * sn * sn, (sr * sr - sp * sp) * c * sn, sr * sr * sn * sn + sp * sp * c * c], t: rec.t };
  }
  // two bearings from different nodes cross at a point; covariance from the perpendicular uncertainty of each ray
  function triangulate(a, b) {
    const det = Math.sin(a.b - b.b);
    if (Math.abs(det) < Math.sin(15 * D2R)) return null;
    const dx = b.sx - a.sx, dy = b.sy - a.sy;
    const t1 = (-dx * Math.sin(b.b) + Math.cos(b.b) * dy) / det;
    const t2 = (Math.cos(a.b) * dy - Math.sin(a.b) * dx) / det;
    if (t1 <= 0 || t2 <= 0 || t1 > a.rmax * 1.2 || t2 > b.rmax * 1.2) return null;
    let m00 = 0, m01 = 0, m11 = 0;
    [[a, t1], [b, t2]].forEach(([rec, tt]) => {
      const nx = -Math.sin(rec.b), ny = Math.cos(rec.b), sg = Math.max(tt * rec.sigB, 1);
      m00 += (nx * nx) / (sg * sg); m01 += (nx * ny) / (sg * sg); m11 += (ny * ny) / (sg * sg);
    });
    const dm = m00 * m11 - m01 * m01;
    return { x: a.sx + t1 * Math.cos(a.b), y: a.sy + t1 * Math.sin(a.b), R: [m11 / dm, -m01 / dm, m00 / dm], t: Math.max(a.t, b.t) };
  }
  // number of different nodes that fed a track lately
  function recentNodes(tr, t) {
    const set = {};
    Object.keys(tr.srcs).forEach((k) => { if (k !== 'self' && t - tr.srcs[k] <= 3) set[k.split(' ')[0]] = 1; });
    return Object.keys(set).length;
  }
  function hasRangeSource(tr, t) {
    return tr.rangeT !== undefined && t - tr.rangeT <= 3; // a radar or single-microphone range reading
  }

  // --------------------------------------------------------------------- run
  function run(P, opts) {
    opts = opts || {};
    const lite = !!opts.lite;
    const rn = rng(P.seed * 7919 + 13);   // sensor noise
    const rnet = rng(P.seed * 104729 + 7); // network
    const rcl = rng(P.seed * 15485863 + 3); // clutter
    const real = P.mode === 'realistic';
    const loss = real ? P.loss / 100 : 0;
    const delay = real ? P.delayMs / 1000 : 0;
    const drift = real ? P.driftMs / 1000 : 0;
    const world = prepare(P.scenario || DEFAULT_SCENARIO);
    const T_END = world.duration, NF = Math.round(T_END / DT), EVAL = world.eval; // this run's own length and scoring window
    const assign = Object.assign({}, world.assign, P.assign || {});
    const sensors = buildSensors(assign, P.weather, world.sensorKinds);
    const falseAlarms = ((world.env.clutter && world.env.clutter.false_alarms_per_min) || 0) / 60;
    const radarCount = sensors.filter((q) => q.kind === 'RAD').length || 1;
    sensors.forEach((q) => { if (q.kind === 'RAD') q.clutter = Math.max(q.clutter, falseAlarms / radarCount); });
    const hostileById = {};
    world.hostiles.forEach((h) => { hostileById[h.id] = h; });
    const dropT = {}; // nodes that die mid-run (realistic mode only)
    if (real) (world.deg.dropout || []).forEach((d) => { dropT[d.node] = d.t; });
    const alive = (n, t) => dropT[n] === undefined || t < dropT[n];
    const nodes = world.ground.map((g) => g.id).concat(world.friendlies.map((f) => f.id));
    const driftScale = {};
    nodes.forEach((n) => { driftScale[n] = rn() * 2 - 1; });
    const nodePos = (id, t) => {
      const g = world.ground.find((x) => x.id === id);
      if (g) return { x: g.x, y: g.y, vx: 0, vy: 0, heading: g.heading };
      const f = world.friendlies.find((x) => x.id === id);
      return Object.assign({ alt: f.alt }, frState(f, t));
    };
    const linkQ = {};
    nodes.forEach((n) => { linkQ[n] = 1; });

    let queue = [];
    function send(node, payload, t, latency) {
      const ok = rnet() >= loss;
      linkQ[node] = 0.97 * linkQ[node] + 0.03 * (ok ? 1 : 0);
      if (!ok) return;
      const dly = delay > 0 ? Math.max(0, delay * (1 + 0.3 * gauss(rnet))) : 0;
      payload.arr = t + dly + (latency || 0);
      queue.push(payload);
    }

    const beaconEvery = Math.max(1, Math.round(10 / (world.beacon.rate_hz || 2)));
    const beaconSigma = world.beacon.pos_sigma_m || 3;
    const tracks = [];
    const pending = []; // bearing-only records waiting for a second view
    const friends = {};
    let hostileCount = 0, unkCount = 0;
    const alerts = [];
    const frames = [];
    const lastMatch = {};
    let swaps = 0, ffaCount = 0;
    const sqHist = [];
    const crossAlerted = {};
    let evalSq = 0, evalN = 0, evalCnt = 0, evalCntN = 0;
    const timeline = [];

    // friendly roster is synced before the mission: tracks start at the true state
    world.friendlies.forEach((f) => {
      const st = frState(f, 0);
      const tr = newTrack(f.id, 'frd', { x: st.x, y: st.y, R: [9, 0, 9], t: 0 }, 6, 4);
      tr.s[2] = st.vx; tr.s[3] = st.vy; tr.cls = 'friendly'; tr.srcs.self = 0;
      friends[f.id] = tr; tracks.push(tr);
    });

    for (let k = 0; k <= NF; k++) {
      const t = k * DT;
      const off = (n) => drift * driftScale[n] * (t / T_END);

      // ---- truth
      const truth = [];
      world.friendlies.forEach((f) => truth.push(Object.assign({ id: f.id, kind: 'friendly' }, frState(f, t))));
      world.hostiles.forEach((h) => {
        const st = hoState(h, t);
        if (st) truth.push(Object.assign({ id: h.id, kind: 'hostile' }, st));
      });
      const targetAt = (obj, tt) => {
        if (obj.kind === 'friendly') return frState(world.friendlies.find((f) => f.id === obj.id), tt);
        return hoState(hostileById[obj.id], tt);
      };

      // ---- sensing and messaging
      const rawMeas = [];
      sensors.forEach((s) => {
        if (k % s.every || !alive(s.node, t)) return;
        const sp = nodePos(s.node, t);
        const tt = Math.max(0, t - off(s.node));
        const heading = s.pointing === 'omni' ? null : (sp.heading !== undefined ? sp.heading : Math.atan2(sp.vy, sp.vx));
        const isGround = s.node.startsWith('GS');
        // 1. who is inside the sensor's limits: range window, field of view, detection probability
        let seen = [];
        truth.forEach((o) => {
          if (o.id === s.node) return;
          const tg = targetAt(o, tt);
          if (!tg) return;
          const dx = tg.x - sp.x, dy = tg.y - sp.y, r = Math.hypot(dx, dy);
          if (r > s.range || r < s.minRange || r < 1) return;
          const h = hostileById[o.id]; // a hostile's signature scales how well each sensor type sees it
          if (s.kind === 'RF' && h && !h.emits) return; // a silent hostile is invisible to RF
          const az = Math.atan2(dy, dx);
          if (heading !== null && Math.abs(wrapPi(az - heading)) > s.fov / 2) return;
          const pd = Math.min(1, s.pd * (h ? (h.sig[SIG_KEY[s.kind]] || 1) : 1)) * (1 - (1 - s.pdFar) * (r / s.range) * (r / s.range)); // detections thin out with distance
          if (rn() > pd) return;
          seen.push({ x: tg.x, y: tg.y, vx: tg.vx, vy: tg.vy, r, az, n: 1, o: Object.assign({}, o, { alt: h ? h.alt : undefined }) });
        });
        if (s.cell && seen.length > 1) seen = mergeCells(seen, s.cell); // radar resolution cell
        // 2. each detection becomes the sensor's native record
        seen.forEach((d) => rawMeas.push(makeRecord(s, d, sp, t, isGround, rn)));
        if (s.clutter && rcl() < s.clutter * s.every * DT) {
          const half = heading === null ? Math.PI : s.fov / 2, a = (heading || 0) + (rcl() * 2 - 1) * half;
          const rr = s.minRange + Math.sqrt(rcl()) * (s.range - s.minRange);
          rawMeas.push(makeRecord(s, { x: sp.x + rr * Math.cos(a), y: sp.y + rr * Math.sin(a), vx: 0, vy: 0, r: rr, az: a, n: 1, o: { kind: 'clutter' } }, sp, t, isGround, rcl, true));
        }
      });
      // group a node's frame messages
      rawMeas.forEach((z) => send(z.node, { type: 'meas', z }, t, z.latency));
      if (k % beaconEvery === 0) {
        if (world.beacon.enabled !== false) {
          world.friendlies.forEach((f) => {
            if (!alive(f.id, t)) return;
            const st = frState(f, Math.max(0, t - off(f.id)));
            send(f.id, { type: 'beacon', id: f.id, x: st.x + gauss(rn) * beaconSigma, y: st.y + gauss(rn) * beaconSigma, t }, t);
          });
        }
        world.ground.forEach((g) => { if (alive(g.id, t)) linkQ[g.id] = 0.97 * linkQ[g.id] + 0.03 * (rnet() >= loss ? 1 : 0); });
      }

      // ---- deliver
      const arrived = queue.filter((m) => m.arr <= t + 1e-9);
      queue = queue.filter((m) => m.arr > t + 1e-9);
      arrived.sort((a, b) => (a.arr - b.arr) || ((a.type === 'beacon' ? 0 : 1) - (b.type === 'beacon' ? 0 : 1)));

      // ---- tracker
      tracks.forEach((tr) => { predict(tr, DT); tr.updated = false; });
      const frameMeas = [];
      arrived.forEach((m) => {
        if (m.type === 'beacon') {
          const z = { x: m.x, y: m.y, R: [9, 0, 9], t, node: m.id };
          let tr = friends[m.id];
          if (!tr) {
            tr = friends[m.id] = newTrack(m.id, 'frd', z, 6, 100);
            tr.cls = 'friendly';
            tracks.push(tr);
          } else update(tr, z, innov(tr, z));
          tr.lastUpd = t; tr.srcs.self = t;
          return;
        }
        const rec = m.z;
        frameMeas.push(rec);
        let best = null, bs = Infinity;
        tracks.forEach((tr) => {
          const sc = gateRecord(tr, rec);
          if (sc !== null && sc < bs) { bs = sc; best = tr; }
        });
        if (best && best.kind === 'frd') return; // the detection is a friendly we already know about
        if (best) {
          applyRecord(best, rec);
          if (rec.m !== 'bearing') best.rangeT = t;
          best.updated = true; best.lastUpd = t;
          best.srcs[rec.node + ' ' + rec.k] = t;
        } else if (rec.m === 'rangeaz') {
          // radar gives range and bearing: enough to start a track by itself
          const fix = fixFromRangeAz(rec);
          if (!tracks.some((tr) => tr.kind !== 'frd' && Math.hypot(tr.s[0] - fix.x, tr.s[1] - fix.y) < 60)) {
            const tr = newTrack('U' + (++unkCount), 'trk', fix, 3, 225);
            tr.rangeT = t;
            tr.updated = true; tr.srcs[rec.node + ' ' + rec.k] = t;
            tracks.push(tr);
          }
        } else if (rec.m === 'bearing') {
          // bearing only: needs a second bearing from another node to fix a position
          const mate = pending.find((p) => p.node !== rec.node && t - p.t <= 1.0 && triangulate(p, rec));
          if (mate) {
            const fix = triangulate(mate, rec);
            pending.splice(pending.indexOf(mate), 1);
            if (!tracks.some((tr) => tr.kind !== 'frd' && Math.hypot(tr.s[0] - fix.x, tr.s[1] - fix.y) < 60)) {
              const tr = newTrack('U' + (++unkCount), 'trk', fix, 3, 225);
              tr.updated = true; tr.srcs[mate.node + ' ' + mate.k] = t; tr.srcs[rec.node + ' ' + rec.k] = t;
              tracks.push(tr);
            }
          } else pending.push(rec);
        }
      });
      for (let i = pending.length - 1; i >= 0; i--) if (t - pending[i].t > 1.0) pending.splice(i, 1);

      // ---- lifecycle
      const events = [];
      tracks.forEach((tr) => {
        if (tr.kind === 'frd') return;
        if (tr.updated) tr.hitFrames++;
        // confirm only with enough hits, a pinned-down position, and either range data or three viewpoints (rules out ghost crossings)
        if (tr.status === 'tentative' && tr.hitFrames >= 6 && Math.sqrt(Math.max(tr.P[0], tr.P[5])) < 30 && (hasRangeSource(tr, t) || recentNodes(tr, t) >= 3)) {
          tr.status = 'confirmed';
          tr.unsup = null;
          if (/^U/.test(tr.id)) { // a demoted track that is confirmed again keeps its ID
            tr.id = 'H' + (++hostileCount);
            alerts.push({ t, sev: 'info', text: tr.id + ' confirmed hostile' });
            timeline.push({ t, label: tr.id + ' seen', color: 'red' });
          }
        }
        if (tr.status === 'tentative' && !tr.alerted && tr.hitFrames >= 3) {
          tr.alerted = true;
          alerts.push({ t, sev: 'info', text: 'New unknown drone in range: ' + tr.id + ' (' + Object.keys(tr.srcs)[0] + ')' });
        }
        if (tr.status === 'confirmed') tr.status = t - tr.lastUpd > 1.0 ? 'coasting' : 'confirmed';
        if (tr.status === 'coasting' && t - tr.lastUpd <= 1.0) tr.status = 'confirmed';
        // a confirmed track must keep its support (range data or three viewpoints); without it, back to 'unknown'
        if (tr.status !== 'tentative') {
          if (hasRangeSource(tr, t) || recentNodes(tr, t) >= 3) tr.unsup = null;
          else if (tr.unsup === null || tr.unsup === undefined) tr.unsup = t;
          else if (t - tr.unsup > 4) { tr.status = 'tentative'; tr.hitFrames = 0; tr.unsup = null; }
        }
      });
      for (let i = tracks.length - 1; i >= 0; i--) {
        const tr = tracks[i];
        if (tr.kind === 'frd') continue;
        const silent = t - tr.lastUpd;
        const tent = tr.status === 'tentative';
        if ((tent && silent > 1.5) || (!tent && silent > 8) || tr.P[0] + tr.P[5] > 40000) tracks.splice(i, 1);
      }
      // a track riding on a beacon-known friendly is that friendly, not a new object
      for (let i = tracks.length - 1; i >= 0; i--) {
        const tr = tracks[i];
        if (tr.kind === 'frd') continue;
        const onFriend = Object.keys(friends).some((id) => {
          const f = friends[id];
          const n = innov(f, { x: tr.s[0], y: tr.s[1], R: [tr.P[0], tr.P[1], tr.P[5]] });
          return n.d2 < GATE && Math.hypot(f.s[2] - tr.s[2], f.s[3] - tr.s[3]) < 5;
        });
        if (onFriend && tr.status !== 'confirmed') tracks.splice(i, 1);
      }
      // drop duplicates: two confirmed tracks on top of each other moving alike
      for (let i = 0; i < tracks.length; i++) {
        for (let j = i + 1; j < tracks.length; j++) {
          const a = tracks[i], b = tracks[j];
          if (a.kind === 'frd' || b.kind === 'frd' || a.status === 'tentative' || b.status === 'tentative') continue;
          const sep = { x: b.s[0], y: b.s[1], R: [a.P[0] + b.P[0], a.P[1] + b.P[1], a.P[5] + b.P[5]] };
          const n = innov(a, { x: sep.x, y: sep.y, R: [b.P[0], b.P[1], b.P[5]] });
          const close = Math.hypot(a.s[0] - b.s[0], a.s[1] - b.s[1]) < 30;
          if ((n.d2 < 6 || close) && Math.hypot(a.s[2] - b.s[2], a.s[3] - b.s[3]) < 6) {
            const drop = a.hitFrames >= b.hitFrames ? b : a;
            tracks.splice(tracks.indexOf(drop), 1); i = -1; break;
          }
        }
      }

      // ---- snapshot
      const snap = [];
      const hostileTracks = [];
      tracks.forEach((tr) => {
        let cls, pH, pU, pF;
        if (tr.kind === 'frd') { cls = 'friendly'; pF = Math.max(0.5, 1 - (t - tr.lastUpd) * 0.05); pH = 0; pU = 1 - pF; }
        else if (tr.status === 'tentative') { cls = 'unknown'; pH = Math.min(0.35, tr.hitFrames * 0.05); pF = 0.1; pU = 1 - pH - pF; }
        else { cls = 'hostile'; pH = Math.min(0.99, 0.7 + tr.hitFrames / 120); pU = (1 - pH) * 0.7; pF = 1 - pH - pU; }
        const nodesList = Object.keys(tr.srcs).filter((n) => t - tr.srcs[n] <= 2);
        const o = {
          id: tr.id, cls, st: tr.status, x: tr.s[0], y: tr.s[1], vx: tr.s[2], vy: tr.s[3],
          pxx: tr.P[0], pyy: tr.P[5], pxy: tr.P[1], pvv: tr.P[10] + tr.P[15],
          conf: cls === 'friendly' ? pF : cls === 'hostile' ? pH : pH + 0.3,
          age: t - tr.lastUpd, nodes: nodesList, pH, pU, pF, born: tr.born,
        };
        snap.push(o);
        if (cls === 'hostile') hostileTracks.push(o);
      });

      // ---- scoring against ground truth
      const trueHost = truth.filter((o) => o.kind === 'hostile');
      const pairs = [];
      hostileTracks.forEach((a) => trueHost.forEach((b) => {
        const d = Math.hypot(a.x - b.x, a.y - b.y);
        // a pair that was matched before stays matched while it is still close, so two tracks near each other do not flicker
        if (d < 60) pairs.push([lastMatch[b.id] === a.id && d < 40 ? d - 1000 : d, a, b, d]);
      }));
      pairs.sort((p, q) => p[0] - q[0]);
      const usedA = new Set(), usedB = new Set(), match = [];
      pairs.forEach(([key, a, b, d]) => {
        if (usedA.has(a.id) || usedB.has(b.id)) return;
        usedA.add(a.id); usedB.add(b.id); match.push([a.id, b.id, d]);
        a.err = d;
        if (lastMatch[b.id] && lastMatch[b.id] !== a.id) {
          swaps++;
          alerts.push({ t, sev: 'crit', text: 'Identity swap on ' + b.id + ': ' + lastMatch[b.id] + ' → ' + a.id });
          timeline.push({ t, label: 'swap', color: 'red' });
        }
        lastMatch[b.id] = a.id;
      });
      let sqSum = 0;
      match.forEach((m) => { sqSum += m[2] * m[2]; });
      sqHist.push(match.length ? [sqSum / match.length, 1] : [0, 0]);
      let ws = 0, wn = 0;
      for (let i = Math.max(0, sqHist.length - 100); i < sqHist.length; i++) { ws += sqHist[i][0] * sqHist[i][1]; wn += sqHist[i][1]; }
      const rmse10 = wn ? Math.sqrt(ws / wn) : null;
      hostileTracks.forEach((a) => {
        if (usedA.has(a.id)) return;
        const tr = tracks.find((x) => x.id === a.id);
        if (!tr || tr.ffa) return;
        const fr = truth.find((o) => o.kind === 'friendly' && Math.hypot(o.x - a.x, o.y - a.y) < 40);
        if (fr) {
          tr.ffa = true; ffaCount++;
          alerts.push({ t, sev: 'crit', text: 'Friendly ' + fr.id + ' flagged as hostile (' + a.id + ')' });
          timeline.push({ t, label: 'FFA', color: 'red' });
        }
      });
      const countErr = hostileTracks.length - trueHost.length;
      if (t >= EVAL[0] && t <= EVAL[1]) {
        evalSq += sqSum; evalN += match.length; evalCnt += Math.abs(countErr); evalCntN++;
      }

      // ---- crossing prediction
      let cross = null;
      for (let i = 0; i < hostileTracks.length; i++) {
        for (let j = i + 1; j < hostileTracks.length; j++) {
          const a = hostileTracks[i], b = hostileTracks[j];
          const dx = b.x - a.x, dy = b.y - a.y, dvx = b.vx - a.vx, dvy = b.vy - a.vy, v2 = dvx * dvx + dvy * dvy;
          if (v2 < 0.5) continue;
          const tca = -(dx * dvx + dy * dvy) / v2;
          if (tca <= 0 || tca > 15) continue;
          const dmin = Math.hypot(dx + dvx * tca, dy + dvy * tca);
          if (dmin > 60) continue;
          if (!cross || tca < cross.tca) {
            cross = {
              a: a.id, b: b.id, tca, dmin, sep: Math.hypot(dx, dy),
              x: (a.x + a.vx * tca + b.x + b.vx * tca) / 2, y: (a.y + a.vy * tca + b.y + b.vy * tca) / 2,
            };
          }
        }
      }
      if (cross) {
        const key = cross.a + cross.b;
        if (!crossAlerted[key] || t - crossAlerted[key] > 25) {
          crossAlerted[key] = t;
          alerts.push({ t, sev: 'warn', text: 'Crossing predicted ' + cross.a + ' × ' + cross.b + ' in ' + cross.tca.toFixed(1) + ' s: identity risk' });
          timeline.push({ t: t + cross.tca, label: 'crossing?', color: 'amber', dashed: true });
        }
      }

      if (lite) continue;
      frames.push({
        t, k, truth, tracks: snap, match: match.map((m) => [m[0], m[1]]),
        meas: frameMeas.map((z) => ({ k: z.k, node: z.node, module: z.module, t: z.t, m: z.m, sx: z.sx, sy: z.sy, b: z.b, r: z.r, rmax: z.rmax, fields: z.fields, merged: !!z.merged, clutter: !!z.clutter })),
        links: Object.assign({}, linkQ),
        cross,
        m: { est: hostileTracks.length, tru: trueHost.length, countErr, rmse10, swaps, ffa: ffaCount },
      });
    }

    const summary = {
      rmse: evalN ? Math.sqrt(evalSq / evalN) : null,
      countErr: evalCntN ? evalCnt / evalCntN : 0,
      swaps, ffa: ffaCount,
    };
    // entry markers from scenario script
    world.hostiles.forEach((h) => timeline.push({ t: h.wps[0][0], label: h.id + ' in', color: 'red' }));
    return {
      frames, alerts, timeline, summary, scen: world, params: Object.assign({}, P, { assign, scenario: undefined, scenario_id: world.id }), T_END, DT, NF, EVAL,
      sensors: sensors.map((s) => ({ node: s.node, module: s.module, kind: s.kind, range: s.range, minRange: s.minRange, fovDeg: s.pointing === 'omni' ? 360 : Math.round(s.fov * RAD2DEG), pointing: s.pointing, native: s.native, fields: s.fields, rateHz: Math.round(10 / s.every * 10) / 10 })),
    };
  }

  // The record a sensor reports for one detection: only its native fields, with noise.
  function makeRecord(s, d, sp, t, isGround, rand, clutter) {
    const nz = s.noise, nm = s.nm, r = d.r;
    const rec = { k: s.kind, node: s.node, module: s.module, t, sx: sp.x, sy: sp.y, svx: sp.vx || 0, svy: sp.vy || 0, rmax: s.range, latency: s.latency, merged: d.n > 1, clutter: !!clutter };
    const tgtAlt = d.o.alt || (d.o.kind === 'friendly' ? ALT.friendly : ALT.hostile);
    const own = isGround ? ALT.ground : (sp.alt || ALT.friendly);
    const level = (sigma) => nz.source_level_db - 20 * Math.log10(Math.max(r, 1)) + gauss(rand) * sigma * nm;
    switch (s.native) {
      case 'bearing_elevation': {
        const sigB = nz.bearing_deg * D2R * nm;
        rec.m = 'bearing'; rec.b = d.az + gauss(rand) * sigB; rec.sigB = sigB;
        const elev = Math.atan2(tgtAlt - own, r) * RAD2DEG + gauss(rand) * nz.elevation_deg * nm;
        const pRight = Math.max(0.5, 0.95 - 0.45 * (r / s.range)); // the classifier gets worse with distance
        const truthClass = d.o.kind === 'friendly' ? 'friendly' : 'unknown';
        const hint = rand() < pRight ? truthClass : (truthClass === 'friendly' ? 'unknown' : 'friendly');
        rec.fields = s.kind === 'IR'
          ? { bearing_deg: compass(rec.b), elevation_deg: elev, intensity: Math.max(0, 1 - 0.5 * r / s.range + gauss(rand) * 0.05) }
          : { bearing_deg: compass(rec.b), elevation_deg: elev, class_hint: hint };
        break;
      }
      case 'bearing_level': {
        const sigB = nz.bearing_deg * D2R * nm;
        rec.m = 'bearing'; rec.b = d.az + gauss(rand) * sigB; rec.sigB = sigB;
        rec.fields = { bearing_deg: compass(rec.b), level_db: 90 - 20 * Math.log10(Math.max(r, 1)) + gauss(rand) * nz.level_db * nm, presence: true };
        break;
      }
      case 'level': {
        const lv = level(nz.level_db); // a single microphone only hears how loud it is
        rec.m = 'range'; rec.r = Math.pow(10, (nz.source_level_db - lv) / 20);
        rec.sigR = rec.r * (Math.LN10 / 20) * nz.level_db * nm;
        rec.fields = { level_db: lv, presence: true };
        break;
      }
      case 'bearing_rssi': {
        const sigB = nz.bearing_deg * D2R * nm;
        rec.m = 'bearing'; rec.b = d.az + gauss(rand) * sigB; rec.sigB = sigB;
        rec.fields = { bearing_deg: compass(rec.b), rssi_dbm: -40 - 20 * Math.log10(Math.max(r, 1)) + gauss(rand) * nz.rssi_db * nm, center_freq_mhz: d.o.kind === 'friendly' ? 5745 : 2437 };
        break;
      }
      default: { // range_azimuth_doppler
        const sigR = nz.range_m * nm, sigB = nz.azimuth_deg * D2R * nm, sigRR = nz.radial_mps * nm;
        rec.m = 'rangeaz'; rec.r = r + gauss(rand) * sigR; rec.b = d.az + gauss(rand) * sigB;
        rec.sigR = sigR; rec.sigB = sigB; rec.sigRR = sigRR;
        const ux = Math.cos(d.az), uy = Math.sin(d.az);
        rec.rr = (d.vx - (sp.vx || 0)) * ux + (d.vy - (sp.vy || 0)) * uy + gauss(rand) * sigRR;
        rec.fields = { range_m: rec.r, azimuth_deg: compass(rec.b), radial_mps: rec.rr, snr_db: 20 - 20 * Math.log10(Math.max(r, 1) / 100) + gauss(rand) };
      }
    }
    return rec;
  }

  // targets closer than the cell in range and azimuth merge into one detection at their centroid
  function mergeCells(seen, cell) {
    const out = [], used = new Array(seen.length).fill(false);
    for (let i = 0; i < seen.length; i++) {
      if (used[i]) continue;
      const grp = [seen[i]];
      used[i] = true;
      for (let j = i + 1; j < seen.length; j++) {
        if (used[j]) continue;
        if (Math.abs(seen[j].r - seen[i].r) < cell.range_m && Math.abs(seen[j].az - seen[i].az) < cell.azimuth_deg * D2R) {
          grp.push(seen[j]); used[j] = true;
        }
      }
      const n = grp.length, avg = (key) => grp.reduce((acc, g) => acc + g[key], 0) / n;
      out.push({ x: avg('x'), y: avg('y'), vx: avg('vx'), vy: avg('vy'), r: avg('r'), az: avg('az'), n, o: grp[0].o });
    }
    return out;
  }

  global.Sim = { run, prepare, DT, T_END, NF, EVAL, WEATHERS, PLATFORMS, MODULES, DEFAULT_SCENARIO };
  if (typeof module !== 'undefined') module.exports = global.Sim;
})(typeof window !== 'undefined' ? window : globalThis);
