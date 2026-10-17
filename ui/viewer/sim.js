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
 * This browser baseline runs independently of the Python tracking/fusion
 * pipeline. Simplifications are marked "MOCK"; its results do not validate
 * the Python backend.
 */
(function (global) {
  'use strict';

  const Drones = typeof window !== 'undefined' ? window.Drones : require('./drones.js');
  const Messages = typeof window !== 'undefined' ? window.Messages : require('./messages.js');
  const Mission = typeof window !== 'undefined' ? window.Missions : require('./missions.js');
  const Weather = typeof window !== 'undefined' ? window.Weather : require('./weather.js');
  const Jamming = typeof window !== 'undefined' ? window.Jamming : require('./jamming.js');
  const LinkCap = typeof window !== 'undefined' ? window.LinkCap : require('./linkcap.js');
  const StoreFwd = typeof window !== 'undefined' ? window.StoreFwd : require('./storefwd.js');
  const LateData = typeof window !== 'undefined' ? window.LateData : require('./latedata.js');
  const Behavior = typeof window !== 'undefined' ? window.Behavior : require('./behavior.js');
  const Traffic = typeof window !== 'undefined' ? window.Traffic : require('./traffic.js');
  const FriendFoe = typeof window !== 'undefined' ? window.FriendFoe : require('./friend-foe.js');
  const Investigations = typeof window !== 'undefined' ? window.Investigations : require('./investigations.js');
  const Metrics = typeof window !== 'undefined' ? window.Metrics : require('./metrics.js');
  const Assessment = typeof window !== 'undefined' ? window.Assessment : require('./assessment.js');
  const CAT = typeof CATALOG !== 'undefined' ? CATALOG : require('./catalog.js'); // eslint-disable-line no-undef
  const DT = 0.1;
  const T_END = 120;
  const NF = Math.round(T_END / DT);
  const EVAL = [45, 90]; // default; each run uses the window around its own crossing
  const D2R = Math.PI / 180;
  const GATE = 9.21; // chi-square, 2 dof, 99 %
  const KIND = { eo_camera: 'EO', thermal_camera: 'IR', microphone: 'MIC', rf_receiver: 'RF', radar: 'RAD' };
  const RAD2DEG = 180 / Math.PI;
  const ALT = { friendly: 60, hostile: 80, ground: 5 }; // metres, only used for elevation angles
  const wrapPi = (a) => Math.atan2(Math.sin(a), Math.cos(a));
  const compass = (mathRad) => ((90 - mathRad * RAD2DEG) % 360 + 360) % 360; // 0 = north, clockwise
  const G_BEARING = 6.63; // chi-square, 1 dof, 99 %

  // ---------------------------------------------------------------- scenario
  // A scenario comes from the seeder (seeder/scenario.py, exported to scenarios.js or served by serve.py):
  // friendly patrol loops, ground sensors, hostile waypoint paths, environment and degradations.
  const DEFAULT_SCENARIO = typeof SCENARIOS !== 'undefined' ? SCENARIOS.challenge : require('./scenarios.js').challenge; // eslint-disable-line no-undef
  const SIG_KEY = { EO: 'eo', IR: 'thermal', MIC: 'acoustic', RF: 'rf', RAD: 'radar' };

  function prepare(sc) {
    const targets = sc.targets.map(pathObject);
    const world = {
      id: sc.id, name: sc.name, duration: sc.duration_s, c2: { x: sc.c2[0], y: sc.c2[1] },
      ground: sc.ground.map((g) => ({ id: g.id, platform: g.platform, x: g.position[0], y: g.position[1], heading: (90 - g.heading_deg) * D2R })),
      friendlies: sc.friendlies.map((f) => Object.assign({ id: f.id, platform: f.platform, alt: f.altitude_m }, f.loop, {
        x: f.loop.cx + f.loop.R * Math.cos(f.loop.th0), y: f.loop.cy + f.loop.R * Math.sin(f.loop.th0),
      })),
      targets, hostiles: targets.filter((t) => t.role !== 'benign'), benigns: targets.filter((t) => t.role === 'benign'),
      clutter: (sc.clutter || []).map((o) => Object.assign(pathObject(o), { type: o.type })), // birds, vehicles: seen, not threats
      commands: sc.commands || [], beacon: sc.beacon, env: sc.environment, deg: sc.degradations, sensorKinds: sc.sensor_set.enabled_kinds, assign: {},
    };
    sc.friendlies.concat(sc.ground).forEach((n) => { world.assign[n.id] = n.platform; });
    const cr = sc.config && sc.config.targets && sc.config.targets.crossing;
    const tc = cr && cr.enabled ? cr.t : sc.duration_s / 2;
    world.eval = [Math.max(0, tc - 6), Math.min(sc.duration_s, tc + 39)]; // window around the crossing used for summary metrics
    return world;
  }
  // an object on a waypoint path (a hostile or clutter); moved by hoState
  const pathObject = (t) => ({ id: t.id, role: t.role || 'hostile', wps: t.waypoints, wob: t.wobble_m, ph: t.phase, alt: t.altitude_m, sig: t.signature || {}, emits: t.emits !== false });

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
  // Sensors report their native bearing/range/Doppler/loudness fields, not
  // oracle position fixes. Numbers come from the catalog module's `sim` block,
  // scaled by its weather effect. Node pose is still exact in this baseline.
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

  // radar clutter rate under the active effects: the highest one the catalog gives, else the default
  function clutterRate(m, effects) {
    const rates = Object.keys(effects).map((n) => m.weather_effects && m.weather_effects[n] && m.weather_effects[n].clutter_rate_per_s).filter((r) => r !== undefined);
    return rates.length ? Math.max.apply(null, rates) : 0.05;
  }
  // effects = the weather that holds everywhere and all run; events and the sky are applied per detection (sensorAt)
  function buildSensors(assign, effects, kinds) {
    const list = [];
    Object.keys(assign).forEach((node) => {
      const plat = PLATFORMS[assign[node]];
      if (!plat) throw new Error('Unknown platform for ' + node + ': ' + assign[node]);
      plat.modules.forEach((link) => {
        const m = MODULES[link.module_id];
        if (!KIND[m.kind] || kinds.indexOf(m.kind) < 0) return; // gnss / imu are not detection sensors; the scenario can switch kinds off
        const q = Weather.sensorQuality(m, effects), sm = m.sim;
        list.push({
          node, module: m.id, kind: KIND[m.kind], mod: m, sm,
          range: sm.range_m * q.range,
          minRange: sm.min_range_m,
          fov: sm.fov_deg * D2R,
          pointing: sm.pointing,
          every: Math.max(1, Math.round(10 / sm.rate_hz)),
          latency: sm.latency_ms / 1000,
          native: m.native.type,
          fields: m.native.fields.map((f) => f.name),
          pd: Math.min(1, sm.pd * q.pd),
          pdFar: sm.pd_far,
          nm: q.noise,
          noise: sm.noise,
          cell: sm.resolution_cell || null,
          clutter: m.kind === 'radar' ? clutterRate(m, effects) : 0,
        });
      });
    });
    return list;
  }

  // ----------------------------------------------------------- Kalman filter
  // State [x y vx vy], row-major 4x4 covariance, native scalar measurement updates.
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
  function symmetrize(P) { // keep the covariance symmetric despite rounding
    for (let i = 0; i < 4; i++) for (let j = i + 1; j < 4; j++) { const m = (P[i * 4 + j] + P[j * 4 + i]) / 2; P[i * 4 + j] = P[j * 4 + i] = m; }
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
    symmetrize(P);
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
    symmetrize(P);
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
  // A run keeps everything in one context object `c` (scenario, random streams, message queue, tracker
  // state, counters). Each frame passes it through small stages:
  // sense -> send -> deliver -> track -> lifecycle -> prune -> snapshot -> score -> crossing.
  function run(P, opts) {
    const c = newContext(P);
    c.lite = !!(opts && opts.lite);
    c.tap = (opts && opts.tap) || null; // tests: network sends plus local investigation contract events; arr is set only by the channel
    startFriendTracks(c);
    for (let k = 0; k <= c.NF; k++) stepFrame(c, k);
    return finish(c);
  }

  function newContext(P) {
    const real = P.mode === 'realistic';
    const world = prepare(P.scenario || DEFAULT_SCENARIO);
    const assign = Object.assign({}, world.assign, P.assign || {});
    const wx = Weather.providerFor(world.env, P.weather || 'clear', P.sky !== undefined ? P.sky : world.env.sky);
    const c = {
      P, world, assign, real, lite: false,
      rn: rng(P.seed * 7919 + 13),   // sensor noise
      rnet: rng(P.seed * 104729 + 7), // network
      rcl: rng(P.seed * 15485863 + 3), // clutter
      loss: real ? P.loss / 100 : 0, delay: real ? P.delayMs / 1000 : 0, drift: real ? P.driftMs / 1000 : 0,
      T_END: world.duration, NF: Math.round(world.duration / DT), EVAL: world.eval,
      wx: wx.provider, wxStatic: wx.isStatic,
      link: linkFor(P, world, real),
      faults: real ? (world.deg.sensor_faults || []) : [], // injected data loss: like dropout, only in Realistic mode
      zones: real ? ((world.deg.network && world.deg.network.jamming_zones) || []) : [], // jamming is a comms degradation: only in Realistic mode
      sensors: buildSensors(assign, Weather.activeEffects(wx.base), world.sensorKinds),
      nodes: world.ground.map((g) => g.id).concat(world.friendlies.map((f) => f.id)),
      pathById: {}, dropT: {}, driftScale: {}, linkQ: {}, queue: [],
      drones: {}, seqs: {}, cmd: { script: scriptedCommands(P, world), open: {}, records: {}, seen: {}, count: 0 },
      beaconEvery: Math.max(1, Math.round(10 / (world.beacon.rate_hz || 2))), beaconSigma: world.beacon.pos_sigma_m || 3,
      tracks: [], pending: [], rfRecent: [], friends: {}, alerts: [], frames: [], timeline: [], lastMatch: {}, sqHist: [], crossAlerted: {},
      beacons: {},
      groundWatch: world.ground.map((g)=>({...g,goalHeading:g.heading,updated:0})),
      n: { hostile: 0, unk: 0, swaps: 0, ffa: 0, cfa: 0, bfa: 0, evalSq: 0, evalN: 0, evalVelocitySq: 0,
        evalHeadingSq: 0, evalHeadingN: 0, evalTruthN: 0, evalExactN: 0, evalCnt: 0, evalCntN: 0 },
    };
    world.targets.concat(world.clutter).forEach((h) => { c.pathById[h.id] = h; });
    setDropTimes(c, world, real);
    c.sf = storeForwardFor(world, real, c.nodes);
    c.late = c.sf ? LateData.createLog() : null; // what each node took, and when C2 got it
    c.nodes.forEach((n) => { c.driftScale[n] = c.rn() * 2 - 1; c.linkQ[n] = 1; });
    addControllers(c, world, assign);
    shareFalseAlarmsAcrossRadars(c);
    return c;
  }
  // nodes that die mid-run: the scenario's dropout list and dropout faults
  function setDropTimes(c, world, real) {
    if (real) (world.deg.dropout || []).forEach((d) => { c.dropT[d.node] = d.t; });
    c.faults.filter((f) => f.kind === 'dropout').forEach((f) => { c.dropT[f.node] = Math.min(c.dropT[f.node] ?? Infinity, f.t_start); });
  }
  // investigations, missions and the friend/foe estimator, for the fleet within its platforms' flight limits
  function addControllers(c, world, assign) {
    const fleet = world.friendlies.map((f) => {
      const flight = PLATFORMS[assign[f.id]].spec.flight;
      return { ...f, v: Math.min(f.v, flight.max_speed_mps), flight };
    });
    c.investigations = new Investigations.Controller(c.sensors, fleet.map((f) => f.id), c.wx,
      (s, sp, tg, t) => sensorAt(c, s, t, sp, tg), (m) => { if (c.tap) c.tap(m); }, c.seqs,
      (id, t) => id === 'estimator' ? t : localTime(c, id, t),
      {cooperative:true,cueGround:(tr,t)=>cueGround(c,tr,t)});
    c.missions = new Mission.Controller(fleet, c.sensors, DT, (t, text) => {
      c.alerts.push({ t, text, sev: 'info' }); c.timeline.push({ t, label: text, color: 'amber' });
    }, { requireInvestigation: true, geometry: (tr, d, t) => c.investigations.geometry(tr, d, t),
      coverage:{base:world.c2,ground:c.groundWatch,sensorAt:(s,sp,tg,t)=>sensorAt(c,s,t,sp,tg),isAlive:(id,t)=>alive(c,id,t)} });
    c.assessment = new Assessment.Model(world.c2);
    const policy = c.P.behavior || (c.P.scenario?.config?.drone_behavior) || {};
    c.traffic = new Traffic(c.P.traffic || c.P.scenario?.config?.traffic_behaviors, world.targets, world.friendlies, DT);
    c.classifier = new FriendFoe.AutomaticEstimator(Behavior.configFor([world.c2.x, world.c2.y], policy),
      // safe mode (as pipeline/behaviour.py): steady transit alone never makes a track peaceful, because a hostile that
      // flies straight looks the same; on the scenarios 62 to 70 % of the tracks on real hostiles were called peaceful
      { beacon_rate_hz: world.beacon.rate_hz || 2, peaceful_min_updates: c.P.motionPeaceful ? 0 : 1e9 }, fleet.map((f) => f.id));
  }
  // commands to send, in time order: from the run parameters if given, otherwise from the scenario
  function scriptedCommands(P, world) {
    return (P.commands || world.commands).slice().sort((a, b) => a.t - b.t);
  }
  function shareFalseAlarmsAcrossRadars(c) {
    const clutter = c.world.env.clutter;
    const perSec = ((clutter && clutter.false_alarms_per_min) || 0) / 60;
    const radars = c.sensors.filter((q) => q.kind === 'RAD');
    radars.forEach((q) => { q.faFloor = perSec / radars.length; q.clutter = Math.max(q.clutter, q.faFloor); });
  }
  // friendly roster is synced before the mission: tracks start at the true state
  function startFriendTracks(c) {
    c.world.friendlies.forEach((f) => {
      const st = friendlyState(c, f, 0);
      const tr = newTrack(f.id, 'frd', { x: st.x, y: st.y, R: [9, 0, 9], t: 0 }, 6, 4);
      tr.s[2] = st.vx; tr.s[3] = st.vy; tr.cls = 'friendly'; tr.srcs.self = 0;
      c.friends[f.id] = tr; c.tracks.push(tr);
    });
  }

  function stepFrame(c, k) {
    const t = k * DT;
    c.groundWatch.forEach((g)=>{g.heading=wrapPi(g.heading+Math.max(-Math.PI/9*DT,Math.min(Math.PI/9*DT,wrapPi(g.goalHeading-g.heading))));});
    c.missions.drones.forEach((d) => { d.disabled = !alive(c, d.id, t); });
    c.missions.record(t);
    c.missions.observe(t, k, (id) => alive(c, id, t), (s, sp, tg) => sensorAt(c, s, t, sp, tg));
    stepDrones(c, t);
    issueCommands(c, t);
    c.traffic.step(t, (id, at) => friendlyState(c, c.world.friendlies.find((f) => f.id === id), at));
    const truth = truthAt(c, t);
    sendAll(c, k, t, sense(c, k, t, truth));
    drainLinks(c, t);
    sendAcks(c, k, t);
    const frameMeas = trackFrame(c, t, handleControl(c, t, noteArrivals(c, t, deliver(c, t))));
    noteHealth(c, t);
    updateLifecycle(c, t);
    pruneTracks(c, t);
    classifyFrame(c, t);
    c.investigations.update(t, c.tracks);
    c.missions.update(t, c.tracks);
    c.investigations.sync(t, c.missions.drones);
    const { snap, hostileTracks } = snapshot(c, t);
    const score = scoreFrame(c, t, truth, hostileTracks, snap);
    const cross = findCrossing(hostileTracks);
    if (cross) announceCrossing(c, t, cross);
    if (!c.lite) c.frames.push(frameRecord(c, { t, k, truth, snap, frameMeas, cross, score, hostileTracks }));
    if (k < c.NF) c.missions.move(t);
  }

  function finish(c) {
    const n = c.n;
    const summary = { rmse: n.evalN ? Math.sqrt(n.evalSq / n.evalN) : null,
      velocityRmse: n.evalN ? Math.sqrt(n.evalVelocitySq / n.evalN) : null,
      headingRmseDeg: n.evalHeadingN ? Math.sqrt(n.evalHeadingSq / n.evalHeadingN) : null,
      trackedFraction: n.evalTruthN ? n.evalN / n.evalTruthN : null, matchedSamples: n.evalN, targetSamples: n.evalTruthN,
      exactCountFraction: n.evalCntN ? n.evalExactN / n.evalCntN : null,
      countErr: n.evalCntN ? n.evalCnt / n.evalCntN : 0, swaps: n.swaps, ffa: n.ffa };
    if (c.world.clutter.length) summary.cfa = n.cfa; // clutter objects tracked as hostile; only scenarios with clutter report it
    if (c.world.benigns.length) summary.bfa = n.bfa;
    // entry markers from scenario script
    c.world.targets.forEach((h) => c.timeline.push({ t: h.wps[0][0], label: h.id + ' in', color: h.role === 'benign' ? 'amber' : 'red' }));
    const commands = Object.keys(c.cmd.records).map((id) => c.cmd.records[id]);
    faultTimeline(c);
    return Object.assign(commands.length ? { commands } : {}, c.link ? { bandwidth: LinkCap.summary(c.link) } : {},
      c.sf ? { storeForward: storeForwardSummary(c) } : {}, {
      frames: c.frames, alerts: c.alerts, timeline: c.timeline, summary, scen: c.world,
      params: Object.assign({}, c.P, { assign: c.assign, scenario: undefined, scenario_id: c.world.id }),
      T_END: c.T_END, DT, NF: c.NF, EVAL: c.EVAL, sensors: c.sensors.map(sensorInfo),
      missionConfig: { cellSize: Mission.CELL, areaSize: Mission.SIZE, separation: Mission.SEP,
        patrolSpacing: Mission.COMFORT, maxAcceleration: Mission.ACCEL, maxYawDegSec: Mission.YAW_RATE * RAD2DEG,
        coverage:{...c.missions.coverage.config},base:{...c.world.c2} },
      assessmentConfig:{...c.assessment.config},
      behaviorConfig: c.classifier.behavior.config,
      estimatorConfig: { ...c.classifier.config },
      investigations: { requests: c.investigations.requests, statuses: c.investigations.statuses },
    });
  }
  function sensorInfo(s) {
    return {
      node: s.node, module: s.module, kind: s.kind, range: s.range, minRange: s.minRange,
      fovDeg: s.pointing === 'omni' ? 360 : Math.round(s.fov * RAD2DEG), pointing: s.pointing,
      native: s.native, fields: s.fields, rateHz: Math.round(10 / s.every * 10) / 10,
    };
  }
  function frameRecord(c, f) {
    const { score } = f;
    return {
      t: f.t, k: f.k, truth: f.truth, tracks: f.snap, match: score.match.map((m) => [m[0], m[1]]),
      missions: c.missions.snapshot(), coverage: c.missions.cells.map((cell) => cell.last),
      watch:c.missions.coverage.stats(f.t), groundWatch:c.groundWatch.map((g)=>({id:g.id,x:g.x,y:g.y,heading:g.heading})),
      meas: f.frameMeas.map((z) => ({ k: z.k, node: z.node, module: z.module, t: z.t, m: z.m, sx: z.sx, sy: z.sy, b: z.b, r: z.r, rmax: z.rmax, fields: z.fields, merged: !!z.merged, clutter: !!z.clutter })),
      links: Object.assign({}, c.linkQ), cross: f.cross,
      ...(c.sf ? { health: JSON.parse(JSON.stringify(c.sf.health)) } : {}),
      m: { est: f.hostileTracks.length, tru: score.trueHost.length, countErr: score.countErr,
        tracked: score.match.length, trackingTargets: score.trueHost.length, matchedSamples: score.match.length,
        trackCoverage: score.trueHost.length ? score.match.length / score.trueHost.length : null,
        rmse10: score.rolling.rmse, velocityRmse10: score.rolling.velocityRmse, headingRmse10: score.rolling.headingRmseDeg,
        swaps: c.n.swaps, ffa: c.n.ffa },
    };
  }

  // ---------------------------------------------------------------- world state
  function cueGround(c,tr,t) {
    if(t<(tr.nextGroundCue??-Infinity))return tr.groundCues||[];
    tr.nextGroundCue=t+1; const cued=[];let quickest=Infinity;
    c.groundWatch.forEach((g)=>{
      if(!alive(c,g.id,t) || tr.assessment.source_nodes.includes(g.id) ||
          c.missions.coverage.reserved.has(g.id) ||
          (g.target && g.target!==tr.id && t-g.updated<3))return;
      const usable=c.sensors.some((s)=>{
        if(s.node!==g.id || s.kind==='RF')return false;
        const q=sensorAt(c,s,t,g,{x:tr.s[0],y:tr.s[1]}),r=Math.hypot(tr.s[0]-g.x,tr.s[1]-g.y);
        return q.pd>=0.15 && r>=q.minRange && r<=q.range*0.85;
      });
      if(!usable)return;
      const heading=Math.atan2(tr.s[1]-g.y,tr.s[0]-g.x);
      const check=c.missions.coverage.departure(g,g,heading,t);
      // Ground turning does not need to obey the airborne anchor radius.
      if(check.lostCells>0)return;
      quickest=Math.min(quickest,Math.abs(wrapPi(heading-g.heading))/(Math.PI/9));
      g.goalHeading=heading;g.target=tr.id;g.updated=t;cued.push(g.id);
    });
    tr.groundWait=quickest<=1.5?1.5:0;
    tr.groundCues=cued;return cued;
  }
  const alive = (c, node, t) => c.dropT[node] === undefined || t < c.dropT[node];
  const clockOffset = (c, node, t) => c.drift * c.driftScale[node] * (t / c.T_END);
  function nodePos(c, id, t) {
    const g = c.groundWatch.find((x) => x.id === id);
    if (g) return { x: g.x, y: g.y, vx: 0, vy: 0, heading: g.heading };
    const f = c.world.friendlies.find((x) => x.id === id);
    return Object.assign({ alt: f.alt }, friendlyState(c, f, t));
  }
  function truthAt(c, t) {
    const truth = [];
    c.world.friendlies.forEach((f) => truth.push(Object.assign({ id: f.id, kind: 'friendly' }, friendlyState(c, f, t))));
    c.world.targets.forEach((h) => {
      const st = c.traffic.actors.has(h.id) ? c.traffic.state(h.id, t) : hoState(h, t);
      if (st) truth.push(Object.assign({ id: h.id, kind: h.role === 'benign' ? 'benign' : 'hostile' }, st));
    });
    c.world.clutter.forEach((o) => {
      const st = hoState(o, t);
      if (st) truth.push(Object.assign({ id: o.id, kind: 'clutter', type: o.type }, st));
    });
    return truth;
  }
  function targetAt(c, obj, t) {
    if (obj.kind === 'friendly') return friendlyState(c, c.world.friendlies.find((f) => f.id === obj.id), t);
    if (c.traffic.actors.has(obj.id)) return c.traffic.state(obj.id, t);
    return hoState(c.pathById[obj.id], t);
  }

  // -------------------------------------------------------------------- sensing
  function sense(c, k, t, truth) {
    const raw = [];
    c.sensors.forEach((s) => {
      if (k % s.every || !alive(c, s.node, t)) return;
      senseWith(c, s, t, truth, raw);
    });
    return raw;
  }
  function senseWith(c, s, t, truth, raw) {
    const sp = nodePos(c, s.node, t);
    const tt = Math.max(0, t - clockOffset(c, s.node, t));
    const heading = s.pointing === 'omni' ? null : (sp.heading !== undefined ? sp.heading : Math.atan2(sp.vy, sp.vx));
    const isGround = s.node.startsWith('GS');
    let seen = detect(c, s, { sp, heading, truth, tt, t });
    if (s.cell && seen.length > 1) seen = mergeCells(seen, s.cell); // radar resolution cell
    seen.forEach((d) => raw.push(makeRecord(d.sq || s, d, sp, t, isGround, c.rn))); // each detection becomes the native record
    addClutter(c, s, { sp, heading, t, isGround }, raw);
  }
  // who is inside the sensor's limits: range window, field of view, detection probability
  function detect(c, s, view) {
    const { sp, heading, truth, tt, t } = view;
    const seen = [];
    truth.forEach((o) => {
      if (o.id === s.node) return;
      const tg = targetAt(c, o, tt);
      if (!tg) return;
      const dx = tg.x - sp.x, dy = tg.y - sp.y, r = Math.hypot(dx, dy), sq = sensorAt(c, s, t, sp, tg);
      if (r > sq.range || r < sq.minRange || r < 1) return;
      const h = c.pathById[o.id]; // a hostile's or clutter object's signature scales how well each sensor type sees it
      if (s.kind === 'RF' && h && !h.emits) return; // a silent hostile is invisible to RF
      const az = Math.atan2(dy, dx);
      if (heading !== null && Math.abs(wrapPi(az - heading)) > s.fov / 2) return;
      if (c.rn() > detectionProb(sq, h, r)) return;
      seen.push({ x: tg.x, y: tg.y, vx: tg.vx, vy: tg.vy, r, az, n: 1, sq, o: Object.assign({}, o, { alt: h ? h.alt : undefined }) });
    });
    return seen;
  }
  // the sensor as the weather on this line of sight leaves it; a weather that never changes was applied once, in buildSensors
  function sensorAt(c, s, t, sp, tg) {
    return jammedRf(c, weatherSensor(c, s, t, sp, tg), t, sp);
  }
  // RF receivers inside an active jamming zone are noisier
  function jammedRf(c, s, t, sp) {
    const m = s.kind === 'RF' && c.zones.length ? Jamming.rfNoiseMult(c.zones, sp, t) : 1;
    return m > 1 ? Object.assign({}, s, { nm: s.nm * m }) : s;
  }
  function weatherSensor(c, s, t, sp, tg) {
    if (c.wxStatic) return s;
    const effects = Weather.activeEffects(Weather.conditionsBetween(c.wx, [sp.x, sp.y], [tg.x, tg.y], t));
    const q = Weather.sensorQuality(s.mod, effects);
    const clutter = s.kind === 'RAD' ? Math.max(clutterRate(s.mod, effects), s.faFloor || 0) : 0;
    return Object.assign({}, s, { range: s.sm.range_m * q.range, pd: Math.min(1, s.sm.pd * q.pd), nm: q.noise, clutter });
  }
  function detectionProb(s, obj, r) { // obj: the hostile or clutter object, none for a friendly
    const v = obj && obj.sig[SIG_KEY[s.kind]], sig = v === undefined ? 1 : v; // a signature of 0 means unseen, not "missing"
    return Math.min(1, s.pd * sig) * (1 - (1 - s.pdFar) * (r / s.range) * (r / s.range)); // detections thin out with distance
  }
  function addClutter(c, base, view, raw) {
    const { sp, heading, t, isGround } = view, s = sensorAt(c, base, t, sp, sp); // false alarms follow the weather at the sensor
    if (!s.clutter || c.rcl() >= s.clutter * s.every * DT) return;
    const half = heading === null ? Math.PI : s.fov / 2, a = (heading || 0) + (c.rcl() * 2 - 1) * half;
    const rr = s.minRange + Math.sqrt(c.rcl()) * (s.range - s.minRange);
    const ghost = { x: sp.x + rr * Math.cos(a), y: sp.y + rr * Math.sin(a), vx: 0, vy: 0, r: rr, az: a, n: 1, o: { kind: 'clutter' } };
    raw.push(makeRecord(s, ghost, sp, t, isGround, c.rcl, true));
  }

  // ------------------------------------------------------------------- messaging
  function noteLink(c, node, ok) { // smoothed share of messages that got through
    c.linkQ[node] = 0.97 * c.linkQ[node] + 0.03 * (ok ? 1 : 0);
  }
  // base loss, raised to the loss of any active jamming zone the node is inside
  function lossFor(c, node, t) {
    if (c.faults.length && activeFault(c, node, 'link_outage', t)) return 1;
    return c.zones.length ? Jamming.lossAt(c.zones, c.loss, nodePos(c, node, t), t) : c.loss;
  }
  const activeFault = (c, node, kind, t) => c.faults.find((f) => f.node === node && f.kind === kind && t >= f.t_start && (f.t_end === undefined || t < f.t_end));
  function extraDelay(c, node, t) {
    const f = c.faults.length && activeFault(c, node, 'delay_burst', t);
    return f ? f.extra_ms / 1000 : 0;
  }
  // each node's link to C2 has a cap when the scenario (or the run) sets one; like jamming, only in Realistic mode
  function linkFor(P, world, real) {
    const kbps = P.bandwidthKbps !== undefined ? P.bandwidthKbps : (world.deg.network || {}).bandwidth_kbps;
    return real && kbps ? LinkCap.create(kbps) : null;
  }
  function sendMessage(c, node, payload, t, latency, resend) {
    if (c.tap) c.tap(payload);
    if (c.sf && !resend && payload.header.source_id !== 'C2') StoreFwd.remember(c.sf.nodes[node], payload, t);
    if (c.late && !resend && payload.type === 'observation') LateData.logSent(c.late, node, payload.header.seq, t, payload.z);
    if (c.link) LinkCap.enqueue(c.link, node, payload, t, latency);
    else putOnChannel(c, node, payload, t, latency);
  }
  // messages whose turn has come on their node's link leave now, at the moment their last byte does
  function drainLinks(c, t) {
    if (c.link) LinkCap.drain(c.link, t, (m, at) => putOnChannel(c, m.node, m.payload, at, m.latency));
  }
  // the channel decides: lost (base loss or a jamming zone) or delivered after delay and latency
  function putOnChannel(c, node, payload, t, latency) {
    const ok = c.rnet() >= lossFor(c, node, t);
    noteLink(c, node, ok);
    if (!ok) return;
    const dly = c.delay > 0 ? Math.max(0, c.delay * (1 + 0.3 * gauss(c.rnet))) : 0;
    payload.arr = t + dly + (latency || 0) + (c.faults.length ? extraDelay(c, node, t) : 0);
    c.queue.push(payload);
  }
  function sendAll(c, k, t, raw) {
    raw.forEach((z) => sendMessage(c, z.node, observation(c, z, t), t, z.latency));
    if (k % c.beaconEvery === 0) sendBeacons(c, t);
  }
  // Fields as in docs/data-formats.md. MOCK: `z` is the internal record the baseline tracker reads; it is not
  // part of the format and a real node would not send it.
  function observation(c, z, t) {
    const covFields = Object.keys(z.sd);
    return stamped(c, z.node, 'observation', {
      sensor_type: SENSOR_TYPE[z.k], sensor_id: z.module, t_obs: localTime(c, z.node, t), kind: OBS_KIND[z.m],
      value: z.fields, cov_fields: covFields, covariance: diagonal(covFields.map((f) => z.sd[f])), z,
    }, t);
  }
  const SENSOR_TYPE = Object.keys(KIND).reduce((o, k) => Object.assign(o, { [KIND[k]]: k }), {});
  const OBS_KIND = { bearing: 'bearing', rangeaz: 'range_bearing', range: 'detection' }; // a lone microphone only hears how loud
  const diagonal = (sd) => sd.map((a, i) => sd.map((_, j) => (i === j ? a * a : 0)));
  function sendBeacons(c, t) {
    if (c.world.beacon.enabled !== false) {
      c.world.friendlies.forEach((f) => { if (alive(c, f.id, t)) sendBeacon(c, f, t); });
    }
    c.world.ground.forEach((g) => {
      if (alive(c, g.id, t)) noteLink(c, g.id, c.rnet() >= c.loss);
      if (c.sf && alive(c, g.id, t) && Math.round(t / DT) % 10 === 0) sendNodeStatus(c, g.id, t);
    });
  }
  // the friendly reports where its own (drifted) clock says it is, with GNSS-like noise
  function sendBeacon(c, f, t) {
    const st = friendlyState(c, f, Math.max(0, localTime(c, f.id, t))), s = c.beaconSigma;
    const position = [st.x + gauss(c.rn) * s, st.y + gauss(c.rn) * s, f.alt];
    const body = { friend_id: f.id, position, velocity: [st.vx, st.vy, 0], covariance: diagonal([s, s, s]) };
    if (c.sf) body.status = StoreFwd.status(c.sf.nodes[f.id], t);
    sendMessage(c, f.id, stamped(c, f.id, 'friendly_beacon', body, t), t);
  }
  // every message: top-level type, the shared header stamped with the sender's clock, then the body
  function stamped(c, source, type, body, t) {
    return Object.assign({ type, header: Messages.makeHeader(c.seqs, source, localTime(c, source, t)) }, body);
  }
  const localTime = (c, node, t) => (node === 'C2' ? t : t - clockOffset(c, node, t));
  function deliver(c, t) {
    const arrived = c.queue.filter((m) => m.arr <= t + 1e-9);
    c.queue = c.queue.filter((m) => m.arr > t + 1e-9);
    const beaconFirst = (m) => (m.type === 'friendly_beacon' ? 0 : 1);
    return arrived.sort((a, b) => (a.arr - b.arr) || (beaconFirst(a) - beaconFirst(b)));
  }

  // ------------------------------------------------- store-and-forward (StoreFwd)
  // on when the scenario asks for it, and only in Realistic mode: nodes keep unacknowledged messages and resend them
  function storeForwardFor(world, real, nodes) {
    const cfg = world.deg.store_forward;
    if (!real || !cfg || !cfg.enabled) return null;
    const sf = { share: cfg.resend_share || StoreFwd.RESEND_SHARE, nodes: {}, rx: {}, health: {}, done: {}, late: {}, dups: 0, outages: [] };
    nodes.forEach((n) => { sf.nodes[n] = StoreFwd.createNode(cfg); sf.rx[n] = StoreFwd.createReceiver(); sf.late[n] = 0; });
    return sf;
  }
  function sendNodeStatus(c, node, t) {
    sendMessage(c, node, stamped(c, node, 'node_status', { node_id: node, status: StoreFwd.status(c.sf.nodes[node], t) }, t), t);
  }
  // C2 broadcasts one ack a second; each node hears it, or not, over its own link
  function sendAcks(c, k, t) {
    if (!c.sf || k === 0 || k % Math.round(StoreFwd.ACK_EVERY_S / DT)) return;
    const acks = {};
    c.nodes.forEach((n) => { acks[n] = StoreFwd.ackEntry(c.sf.rx[n]); });
    const msg = stamped(c, 'C2', 'c2_ack', { acks }, t);
    if (c.tap) c.tap(msg);
    c.nodes.forEach((n) => { if (alive(c, n, t)) putOnChannel(c, n, Object.assign({}, msg, { to: n }), t, 0); });
  }
  // a node hears the ack and resends what C2 is missing, within its share of the link
  function onAck(c, m, t) {
    if (!alive(c, m.to, t)) return;
    const budget = c.link ? c.sf.share * c.link.bytesPerS * StoreFwd.ACK_EVERY_S : Infinity;
    StoreFwd.onAck(c.sf.nodes[m.to], m.acks[m.to], t, budget, LinkCap.sizeOf).forEach((p) => sendMessage(c, m.to, p, t, 0, true));
  }
  // C2: count what arrived, drop duplicates, keep late (resent) messages out of the live picture
  function noteArrivals(c, t, arrived) {
    if (!c.sf) return arrived;
    return arrived.filter((m) => {
      const src = m.header.source_id, rx = c.sf.rx[src];
      if (m.type === 'c2_ack' || !rx) return true;
      if (!StoreFwd.receive(rx, m.header.seq, t)) { c.sf.dups++; return false; }
      if (m.status) StoreFwd.skipBelow(rx, m.status.oldest_seq);
      if (m.type === 'node_status') return false;
      const late = t - m.header.t_sent > StoreFwd.LATE_S;
      if (late) c.sf.late[src]++;
      if (m.type === 'observation') LateData.logArrived(c.late, src, m.header.seq, t);
      return !late || m.type === 'drone_state';
    });
  }
  // C2's view of each node, plus what the node itself knows (offline, how much it holds); state changes become alerts
  function noteHealth(c, t) {
    if (!c.sf) return;
    c.nodes.forEach((n) => {
      const node = c.sf.nodes[n], before = c.sf.health[n];
      const h = StoreFwd.health(c.sf.rx[n], t, before && before.state, alive(c, n, t) && StoreFwd.isOffline(node, t));
      c.sf.health[n] = Object.assign(h, { offline: StoreFwd.isOffline(node, t), buffered_s: Math.round(StoreFwd.bufferedS(node, t) * 10) / 10 });
      if (before && before.state !== h.state) noteHealthChange(c, n, before.state, h.state, t);
    });
    noteCatchUp(c, t);
  }
  const isDown = (state) => state === 'offline' || state === 'presumed_dead' || state === 'isolated';
  function noteHealthChange(c, n, from, to, t) {
    c.alerts.push({ t, sev: isDown(to) ? 'warn' : 'info', text: n + ' link ' + from.replace('_', ' ') + ' to ' + to.replace('_', ' ') });
    if (isDown(to) || isDown(from)) c.timeline.push({ t, label: n + ' ' + to.replace('_', ' '), color: isDown(to) ? 'red' : 'amber' });
  }
  // after an outage ends: how long until the node holds nothing from before the end (all resent and acknowledged)
  function noteCatchUp(c, t) {
    c.faults.forEach((f) => {
      const key = f.node + '@' + f.t_end;
      if (f.kind === 'dropout' || f.t_end === undefined || t < f.t_end || c.sf.done[key]) return;
      if (c.sf.nodes[f.node].store.some((m) => m.t <= f.t_end)) return;
      c.sf.done[key] = true;
      c.sf.outages.push({ node: f.node, kind: f.kind, t_start: f.t_start, t_end: f.t_end, catch_up_s: Math.round((t - f.t_end) * 10) / 10 });
    });
  }
  function storeForwardSummary(c) {
    const nodes = {};
    c.nodes.forEach((n) => {
      const s = c.sf.nodes[n].stats;
      nodes[n] = { stored: s.stored, resent: s.resent, expired: s.expired, late_arrivals: c.sf.late[n], still_held: c.sf.nodes[n].store.length };
    });
    const readings = LateData.lateReadings(c.late, StoreFwd.LATE_S);
    return { nodes, duplicates: c.sf.dups, outages: c.sf.outages, late_s: StoreFwd.LATE_S, readings, revisions: c.lite ? [] : LateData.revise(readings, c.frames, DT, fixFromRangeAz) };
  }
  function faultTimeline(c) {
    c.faults.forEach((f) => {
      c.timeline.push({ t: f.t_start, label: f.node + ' ' + f.kind.replace('_', ' '), color: 'red' });
      if (f.t_end !== undefined) c.timeline.push({ t: f.t_end, label: f.node + ' ' + f.kind.replace('_', ' ') + ' ends', color: 'amber' });
    });
  }

  // ------------------------------------------------------------------- tracker
  function trackFrame(c, t, arrived) {
    c.tracks.forEach((tr) => { predict(tr, DT); tr.updated = false; });
    const frameMeas = [];
    arrived.forEach((m) => {
      if (m.type === 'friendly_beacon') { applyBeacon(c, m, t); return; }
      frameMeas.push(m.z);
      associate(c, m.z, t);
    });
    c.pending = c.pending.filter((p) => t - p.t <= 1.0);
    noteEmitters(c, t, frameMeas);
    return frameMeas;
  }
  // An RF receiver only hears a transmitter, and the birds and vehicles do not transmit. One receiver gives a bearing and
  // any track on that line could take it, so the bearings of two receivers are crossed into a fix and the fix goes to the
  // one track it agrees with best, unless that is a friendly. Three fixes in 6 s make the track a hostile emitter.
  // The same rule as pipeline/identify.py. It is a run parameter (`emitterHostile`, set by the viewer, off for the tests):
  // sensor evidence that an object transmits is not evidence of hostile intent, which the behaviour module alone decides.
  const EMIT = { fixes: 3, window: 6, pair: 0.3, keep: 1.0, gate: 9.21 };
  function noteEmitters(c, t, recs) {
    const rf = recs.filter((r) => r.k === 'RF' && r.m === 'bearing');
    rf.forEach((r) => c.rfRecent.forEach((o) => {
      if (o.node === r.node || Math.abs(o.t - r.t) > EMIT.pair) return;
      const fix = triangulate(o, r);
      if (!fix) return;
      let best = null, bestD2 = EMIT.gate;
      c.tracks.forEach((tr) => { const d2 = innov(tr, fix).d2; if (d2 <= bestD2) { bestD2 = d2; best = tr; } });
      if (best && best.kind !== 'frd') (best.emitFixes = best.emitFixes || []).push(t);
    }));
    c.rfRecent = c.rfRecent.concat(rf).filter((r) => t - r.t <= EMIT.keep);
    c.tracks.forEach((tr) => { if (tr.emitFixes) tr.emitFixes = tr.emitFixes.filter((u) => t - u <= EMIT.window); });
  }
  const isEmitter = (tr) => tr.kind !== 'frd' && (tr.emitFixes || []).length >= EMIT.fixes;
  function applyBeacon(c, m, t) {
    const id = m.friend_id, z = { x: m.position[0], y: m.position[1], R: [9, 0, 9], t, node: id };
    let tr = c.friends[id];
    if (!tr) {
      tr = c.friends[id] = newTrack(id, 'frd', z, 6, 100);
      tr.cls = 'friendly';
      c.tracks.push(tr);
    } else update(tr, z, innov(tr, z));
    tr.lastUpd = t; tr.srcs.self = t; tr.beaconT = Math.max(tr.beaconT || 0, m.header.t_sent);
    tr.observedT = Math.max(tr.observedT ?? -Infinity, m.header.t_sent);
    if (!c.beacons[id] || m.header.t_sent > c.beacons[id].t) c.beacons[id] = {
      friend_id: id, t: m.header.t_sent, position: [m.position[0], m.position[1], 0],
      velocity: [m.velocity[0], m.velocity[1], 0], pos_sigma: Math.sqrt(Math.max(m.covariance[0][0], m.covariance[1][1])),
    };
  }
  function bestTrack(c, rec) {
    let best = null, bs = Infinity;
    c.tracks.forEach((tr) => {
      const sc = gateRecord(tr, rec);
      if (sc !== null && sc < bs) { bs = sc; best = tr; }
    });
    return best;
  }
  function associate(c, rec, t) {
    const best = bestTrack(c, rec);
    if (best && best.kind === 'frd') return; // the detection is a friendly we already know about
    if (best) feedTrack(best, rec, t);
    else if (rec.m === 'rangeaz') spawnTrack(c, fixFromRangeAz(rec), t, [rec], true); // radar: range and bearing start a track alone
    else if (rec.m === 'bearing') pairBearing(c, rec, t);
  }
  function feedTrack(tr, rec, t) {
    applyRecord(tr, rec);
    if (rec.m !== 'bearing') tr.rangeT = t;
    tr.updated = true; tr.lastUpd = t;
    recordSource(tr, rec);
  }
  function recordSource(tr, rec) {
    const key = rec.node + ' ' + rec.k;
    tr.srcs[key] = Math.max(tr.srcs[key] ?? -Infinity, rec.t);
    if (!tr.firstSources) tr.firstSources = {};
    tr.firstSources[rec.node] = Math.min(tr.firstSources[rec.node] ?? Infinity, rec.t);
    tr.observedT = Math.max(tr.observedT ?? -Infinity, rec.t);
    const bucket=Math.floor(rec.t*2+1e-8);
    tr.observations=(tr.observations||[]).filter((r)=>rec.t-r.t<=6 && !(r.node===rec.node && r.k===rec.k && r.bucket===bucket));
    tr.observations.push({node:rec.node,k:rec.k,t:rec.t,sx:rec.sx,sy:rec.sy,m:rec.m,merged:rec.merged,bucket});
  }
  // bearing only: needs a second bearing from another node to fix a position
  function pairBearing(c, rec, t) {
    const mate = c.pending.find((p) => p.node !== rec.node && t - p.t <= 1.0 && triangulate(p, rec));
    if (!mate) { c.pending.push(rec); return; }
    const fix = triangulate(mate, rec);
    c.pending.splice(c.pending.indexOf(mate), 1);
    spawnTrack(c, fix, t, [mate, rec], false);
  }
  function spawnTrack(c, fix, t, recs, hasRange) {
    const near = c.tracks.some((tr) => tr.kind !== 'frd' && Math.hypot(tr.s[0] - fix.x, tr.s[1] - fix.y) < 60);
    if (near) return;
    const tr = newTrack('U' + (++c.n.unk), 'trk', fix, 3, 225);
    if (hasRange) tr.rangeT = t;
    tr.updated = true;
    recs.forEach((r) => recordSource(tr, r));
    c.tracks.push(tr);
  }

  // ------------------------------------------------------------------ lifecycle
  function updateLifecycle(c, t) {
    c.tracks.forEach((tr) => {
      if (tr.kind === 'frd') { setCoasting(tr, t); return; }
      if (tr.updated) tr.hitFrames++;
      confirmTrack(c, tr, t);
      announceTentative(c, tr, t);
      setCoasting(tr, t);
      checkSupport(tr, t);
    });
  }
  // confirm only with enough hits, a pinned-down position, and either range data or three viewpoints (rules out ghost crossings)
  function confirmTrack(c, tr, t) {
    const supported = hasRangeSource(tr, t) || recentNodes(tr, t) >= 3;
    if (tr.status !== 'tentative' || tr.hitFrames < 6 || Math.sqrt(Math.max(tr.P[0], tr.P[5])) >= 30 || !supported) return;
    tr.status = 'confirmed';
    tr.unsup = null;
    if (tr.confirmedOnce) return;
    tr.confirmedOnce = true;
    c.alerts.push({ t, sev: 'info', text: tr.id + ' track confirmed; assessing behavior' });
    c.timeline.push({ t, label: tr.id + ' seen', color: 'amber' });
  }
  function announceTentative(c, tr, t) {
    if (tr.status !== 'tentative' || tr.alerted || tr.hitFrames < 3) return;
    tr.alerted = true;
    c.alerts.push({ t, sev: 'info', text: 'New unknown drone in range: ' + tr.id + ' (' + Object.keys(tr.srcs)[0] + ')' });
  }
  function setCoasting(tr, t) {
    if (tr.status === 'confirmed') tr.status = t - tr.lastUpd > 1.0 ? 'coasting' : 'confirmed';
    if (tr.status === 'coasting' && t - tr.lastUpd <= 1.0) tr.status = 'confirmed';
  }
  // a confirmed track must keep its support (range data or three viewpoints); without it, back to 'unknown'
  function checkSupport(tr, t) {
    if (tr.status === 'tentative') return;
    if (hasRangeSource(tr, t) || recentNodes(tr, t) >= 3) tr.unsup = null;
    else if (tr.unsup === null || tr.unsup === undefined) tr.unsup = t;
    else if (t - tr.unsup > 4) { tr.status = 'tentative'; tr.hitFrames = 0; tr.unsup = null; }
  }

  // ---------------------------------------------------------------------- pruning
  function removeWhere(list, pred) {
    for (let i = list.length - 1; i >= 0; i--) if (pred(list[i])) list.splice(i, 1);
  }
  function pruneTracks(c, t) {
    removeWhere(c.tracks, (tr) => tr.kind !== 'frd' && isStale(tr, t));
    removeWhere(c.tracks, (tr) => {
      if (tr.kind === 'frd' || !ridesOnFriend(c, tr, t)) return false;
      tr.cls = 'friendly'; return true;
    });
    for (let dup = findDuplicate(c.tracks); dup; dup = findDuplicate(c.tracks)) {
      const keep = dup.replacement;
      Object.entries(dup.srcs).forEach(([key, time]) => { keep.srcs[key] = Math.max(keep.srcs[key] ?? -Infinity, time); });
      keep.observations=(keep.observations||[]).concat(dup.observations||[]).filter((r)=>t-r.t<=6);
      if (!keep.firstSources) keep.firstSources = {};
      Object.entries(dup.firstSources || {}).forEach(([key, time]) => { keep.firstSources[key] = Math.min(keep.firstSources[key] ?? Infinity, time); });
      keep.observedT = Math.max(keep.observedT ?? -Infinity, dup.observedT ?? -Infinity);
      keep.emitFixes = (keep.emitFixes || []).concat(dup.emitFixes || []);
      c.tracks.splice(c.tracks.indexOf(dup), 1);
    }
  }
  function isStale(tr, t) {
    const silent = t - tr.lastUpd;
    const tentative = tr.status === 'tentative';
    // a track that was confirmed once and lost its support is a real object going back to tentative: it lives as long as a confirmed one
    return (tentative && silent > (tr.confirmedOnce ? 8 : 1.5)) || (!tentative && silent > 8) || tr.P[0] + tr.P[5] > 40000;
  }
  // a track riding on a beacon-known friendly is that friendly, not a new object
  function ridesOnFriend(c, tr, t) {
    return Object.keys(c.friends).some((id) => {
      const f = c.friends[id];
      const n = innov(f, { x: tr.s[0], y: tr.s[1], R: [tr.P[0], tr.P[1], tr.P[5]] });
      const radius = Math.min(60, Math.max(20, 2 * Math.sqrt(Math.max(tr.P[0], tr.P[5]))));
      const onFreshBeacon = t - (f.beaconT || 0) <= 2 && Math.hypot(f.s[0] - tr.s[0], f.s[1] - tr.s[1]) < radius;
      return n.d2 < GATE && (onFreshBeacon || (tr.status !== 'confirmed' && Math.hypot(f.s[2] - tr.s[2], f.s[3] - tr.s[3]) < 5));
    });
  }
  // two confirmed tracks on top of each other moving alike are one object: returns the one to drop
  function findDuplicate(tracks) {
    for (let i = 0; i < tracks.length; i++) {
      for (let j = i + 1; j < tracks.length; j++) {
        const a = tracks[i], b = tracks[j];
        if (a.kind === 'frd' || b.kind === 'frd' || a.status === 'tentative' || b.status === 'tentative') continue;
        if (sameObject(a, b)) {
          const drop = a.hitFrames >= b.hitFrames ? b : a;
          drop.replacement = drop === a ? b : a;
          return drop;
        }
      }
    }
    return null;
  }
  function sameObject(a, b) {
    const n = innov(a, { x: b.s[0], y: b.s[1], R: [b.P[0], b.P[1], b.P[5]] });
    const close = Math.hypot(a.s[0] - b.s[0], a.s[1] - b.s[1]) < 30;
    return (n.d2 < 6 || close) && Math.hypot(a.s[2] - b.s[2], a.s[3] - b.s[3]) < 6;
  }

  // --------------------------------------------------------------------- snapshot
  function classifyFrame(c, t) {
    // Only tracker estimates and received beacons cross this boundary. The viewer
    // tracker is 2D, so project BOTH tracks and beacons to the same plane.
    const inputs = c.tracks.map((tr) => ({ track_id: tr.id, t, position: [tr.s[0], tr.s[1], 0],
      velocity: [tr.s[2], tr.s[3], 0], observed_t: tr.observedT ?? 0,
      pos_sigma: Math.sqrt(Math.max(0, (tr.P[0] + tr.P[5]) / 2 + Math.hypot((tr.P[0] - tr.P[5]) / 2, tr.P[1]))),
      existence_prob: tr.status === 'tentative' ? 0.5 : 0.95 }));
    const beacons = Object.values(c.beacons).filter((b) => t - b.t <= 2);
    const found = c.classifier.update(t, inputs, beacons);
    const byId = new Map(c.tracks.map((tr) => [tr.id, tr]));
    found.forEach((original) => {
      let v=original;
      const tr = byId.get(v.track_id), prev = tr.cls;
      const reviewed=c.assessment.update(t,tr,v); v=reviewed.decision;
      if (c.P.emitterHostile && v.cls !== 'friendly' && isEmitter(tr)) v = { ...v, cls: 'hostile', class_prob: Math.max(v.class_prob || 0, 0.9), p_hostile: Math.max(v.p_hostile || 0, 0.9) };
      tr.assessment=reviewed.review;
      tr.classification = v; tr.cls = v.cls; tr.behavior = c.classifier.explain(v.track_id);
      if(reviewed.reasons.length)tr.behavior={...tr.behavior,reasons:[...(tr.behavior.reasons||[]),...reviewed.reasons]};
      if(tr.kind!=='frd' && tr.status!=='tentative' && tr.assessment.state==='insufficient_evidence' && !tr.reviewAlerted) {
        tr.reviewAlerted=true;c.alerts.push({t,sev:'warn',text:tr.id+' review overdue: insufficient independent observations; coverage retained'});
      }
      if (v.cls !== prev && ['hostile', 'peaceful', 'suspicious'].includes(v.cls)) {
        c.alerts.push({ t, sev: v.cls === 'hostile' ? 'warn' : 'info',
          text: tr.id + ' assessed ' + v.cls + ': ' + (v.cls === 'suspicious' ? 'identity unverified; ' : '') +
            (tr.behavior.reasons || ['insufficient_history']).join(', ').replace(/_/g, ' ') });
      }
    });
  }
  function snapTrack(tr, t) {
    const v = tr.classification || { cls: 'unknown', class_prob: 0.5, p_hostile: 0.5, p_friendly: 0.5 };
    const cls = v.cls, pH = v.p_hostile, pF = v.p_friendly;
    return {
      id: tr.id, cls, st: tr.status, once: !!tr.confirmedOnce, x: tr.s[0], y: tr.s[1], vx: tr.s[2], vy: tr.s[3],
      pxx: tr.P[0], pyy: tr.P[5], pxy: tr.P[1], pvv: tr.P[10] + tr.P[15],
      conf: v.class_prob, behavior: tr.behavior || {},
      assessment:tr.assessment?{...tr.assessment,source_nodes:tr.assessment.source_nodes.slice()}:null,
      age: t - tr.lastUpd, nodes: Object.keys(tr.srcs).filter((n) => t - tr.srcs[n] <= 2), pH, pF, born: tr.born,
    };
  }
  function snapshot(c, t) {
    const snap = c.tracks.map((tr) => snapTrack(tr, t));
    return { snap, hostileTracks: snap.filter((o) => o.cls === 'hostile') };
  }

  // ---------------------------------------------------------- scoring against truth
  function scoreFrame(c, t, truth, hostileTracks, tracks) {
    const trueHost = truth.filter((o) => o.kind === 'hostile');
    // First associate all confirmed/coasting tracks with ALL real objects.
    // Assessments and scenario roles do not select the geometric assignment;
    // only afterwards do we measure coverage/errors of the threat-scenario targets.
    const eligible = tracks.filter((o) => o.st === 'confirmed' || o.st === 'coasting');
    const paired = Metrics.assign(eligible, truth);
    paired.forEach(({track, distance}) => { track.err = distance; });
    const targetPairs = paired.filter((p) => p.truth.kind === 'hostile');
    const match = targetPairs.map(({track, truth:target, distance}) => {
      noteSwap(c, t, target.id, track.id);
      c.lastMatch[target.id] = track.id;
      return [track.id, target.id, distance];
    });
    const errors = Metrics.errors(targetPairs);
    c.sqHist.push(errors);
    if (c.sqHist.length > 100) c.sqHist.shift();
    const rolling = Metrics.aggregate(c.sqHist);

    // Hostile-label correctness is a separate assessment metric. In particular,
    // an unidentified target still contributes to tracking position/identity
    // quality, while the hostile count correctly reports that missing label.
    const strictPairs = Metrics.assign(hostileTracks, truth);
    flagFriendlies(c, t, strictPairs);
    flagClutter(c, t, strictPairs);
    falseHostiles(c, strictPairs, 'benign', 'bfa').forEach(([a, o]) => {
      c.n.bfa++;
      c.alerts.push({ t, sev: 'warn', text: 'Benign drone ' + o.id + ' assessed hostile (' + a.id + ')' });
    });
    const countErr = hostileTracks.length - trueHost.length;
    if (t >= c.EVAL[0] && t <= c.EVAL[1]) addToSummary(c.n, errors, trueHost.length, countErr);
    return { trueHost, match, rolling, countErr };
  }
  function addToSummary(n, errors, targets, countErr) {
    n.evalSq += errors.positionSq; n.evalN += errors.n; n.evalVelocitySq += errors.velocitySq;
    n.evalHeadingSq += errors.headingSq; n.evalHeadingN += errors.headingN;
    n.evalTruthN += targets; n.evalExactN += countErr === 0 ? 1 : 0;
    n.evalCnt += Math.abs(countErr); n.evalCntN++;
  }
  function noteSwap(c, t, trueId, trackId) {
    const prev = c.lastMatch[trueId];
    if (!prev || prev === trackId) return;
    c.n.swaps++;
    c.alerts.push({ t, sev: 'crit', text: 'Identity swap on ' + trueId + ': ' + prev + ' → ' + trackId });
    c.timeline.push({ t, label: 'swap', color: 'red' });
  }
  // A hostile label on an object of this kind; each track is reported once.
  // Mixed-kind assignment prevents a nearby hostile hiding a friendly alarm.
  function falseHostiles(c, pairs, kind, flag) {
    const found = [];
    pairs.forEach(({track:a, truth:o, distance}) => {
      if (o.kind !== kind || distance >= 40) return;
      const tr = c.tracks.find((x) => x.id === a.id);
      if (!tr || tr[flag]) return;
      tr[flag] = true; found.push([a, o]);
    });
    return found;
  }
  function flagFriendlies(c, t, pairs) {
    falseHostiles(c, pairs, 'friendly', 'ffa').forEach(([a, fr]) => {
      c.n.ffa++;
      c.alerts.push({ t, sev: 'crit', text: 'Friendly ' + fr.id + ' flagged as hostile (' + a.id + ')' });
      c.timeline.push({ t, label: 'FFA', color: 'red' });
    });
  }
  // a bird or vehicle tracked as hostile is a false alarm
  function flagClutter(c, t, pairs) {
    falseHostiles(c, pairs, 'clutter', 'cfa').forEach(([a, o]) => {
      c.n.cfa++;
      c.alerts.push({ t, sev: 'warn', text: 'Clutter ' + o.type + ' ' + o.id + ' tracked as hostile (' + a.id + ')' });
      c.timeline.push({ t, label: 'clutter', color: 'amber' });
    });
  }

  // ------------------------------------------------------------ crossing prediction
  // the pair of hostile tracks that will come within 60 m soonest (closest approach within 15 s)
  function findCrossing(hostileTracks) {
    let cross = null;
    for (let i = 0; i < hostileTracks.length; i++) {
      for (let j = i + 1; j < hostileTracks.length; j++) {
        const x = closestApproach(hostileTracks[i], hostileTracks[j]);
        if (x && (!cross || x.tca < cross.tca)) cross = x;
      }
    }
    return cross;
  }
  function closestApproach(a, b) {
    const dx = b.x - a.x, dy = b.y - a.y, dvx = b.vx - a.vx, dvy = b.vy - a.vy, v2 = dvx * dvx + dvy * dvy;
    if (v2 < 0.5) return null;
    const tca = -(dx * dvx + dy * dvy) / v2;
    if (tca <= 0 || tca > 15) return null;
    const dmin = Math.hypot(dx + dvx * tca, dy + dvy * tca);
    if (dmin > 60) return null;
    return {
      a: a.id, b: b.id, tca, dmin, sep: Math.hypot(dx, dy),
      x: (a.x + a.vx * tca + b.x + b.vx * tca) / 2, y: (a.y + a.vy * tca + b.y + b.vy * tca) / 2,
    };
  }
  function announceCrossing(c, t, cross) {
    const key = cross.a + cross.b;
    if (c.crossAlerted[key] && t - c.crossAlerted[key] <= 25) return;
    c.crossAlerted[key] = t;
    c.alerts.push({ t, sev: 'warn', text: 'Crossing predicted ' + cross.a + ' × ' + cross.b + ' in ' + cross.tca.toFixed(1) + ' s: identity risk' });
    c.timeline.push({ t: t + cross.tca, label: 'crossing?', color: 'amber', dashed: true });
  }

  // ------------------------------------------------------- drones and commands
  // The shared mission controller flies coverage patrols and investigations. C2 sends a drone_command over the lossy channel
  // and repeats it until the drone's drone_state ack arrives; the drone ignores repeats of a command_id it has seen.
  const ACK_TIMEOUT_S = 1.5, MAX_ATTEMPTS = 5; // assumed
  const AREA_M = 1000;
  const flightOf = (c, f) => PLATFORMS[c.assign[f.id]].spec.flight;
  function friendlyState(c, f, t) {
    return c.missions.state(f.id, t);
  }
  function stepDrones(c, t) {
    c.world.friendlies.forEach((f) => {
      const d = c.drones[f.id];
      if (!d || !alive(c, f.id, t)) return;
      repeatMilestone(c, f, d, t);
      if (d.pendingPatrol) { d.pendingPatrol = false; sendMilestone(c, f, d, 'patrolling', t); }
      if (d.mode === 'patrol') return;
      Object.assign(d, friendlyState(c, f, t));
      const goal = d.mode === 'goto' ? { x: d.target[0], y: d.target[1] } : d;
      if (Drones.arrived(d, goal)) reachGoal(c, f, d, goal, t);
    });
  }
  function reachGoal(c, f, d, goal, t) {
    if (d.mode === 'goto') {
      d.mode = 'hold'; d.reported = false;
      c.missions.command(f.id, { command: 'hold', face: d.face }, flightOf(c, f));
    }
    if (d.mode === 'hold' && !d.reported) { d.reported = true; sendMilestone(c, f, d, 'on_station', t); }
  }
  // arriving or rejoining is sent once and repeated twice more, 2 s apart, because a state message has no ack of its own
  function sendMilestone(c, f, d, state, t) {
    d.milestone = { state, repeats: 2, next: t + 2 };
    sendState(c, f, d, state, t);
  }
  function repeatMilestone(c, f, d, t) {
    const m = d.milestone;
    if (!m || m.repeats <= 0 || t < m.next - 1e-9) return;
    m.repeats--; m.next += 2;
    sendState(c, f, d, m.state, t);
  }

  // ---- the drone side
  const patrolling = { mode: 'patrol' };
  function onCommand(c, m, t) {
    const f = c.world.friendlies.find((x) => x.id === m.drone_id);
    if (!f || !alive(c, f.id, t)) return; // no such drone, or it is dead: silence
    const known = c.cmd.seen[m.command_id] || judge(c, f, m, t);
    sendState(c, f, c.drones[f.id] || patrolling, known.state, t, { command_id: m.command_id, reason: known.reason });
  }
  // the first time a command_id arrives it is accepted or rejected; a repeat only gets the same answer again
  function judge(c, f, m, t) {
    const reason = Drones.invalid(m, AREA_M);
    if (!reason) applyCommand(c, f, m, t);
    return (c.cmd.seen[m.command_id] = reason ? { state: 'rejected', reason } : { state: 'accepted' });
  }
  function applyCommand(c, f, m, t) {
    const prev = c.drones[f.id];
    const d = prev || (c.drones[f.id] = Drones.newDrone(friendlyState(c, f, t)));
    d.mode = { goto: 'goto', hold: 'hold', return_to_patrol: 'patrol' }[m.command];
    d.target = m.command === 'goto' ? m.target : null;
    d.cap = m.speed_mps || null;
    d.face = Drones.faceOf(m);
    d.cmdId = m.command_id; d.trackId = m.track_id; d.reported = false; d.milestone = null;
    c.missions.command(f.id, { ...m, face: d.face }, flightOf(c, f));
    d.pendingPatrol = d.mode === 'patrol';
  }
  function sendState(c, f, d, state, t, extra) {
    const p = friendlyState(c, f, t);
    const body = Object.assign({
      drone_id: f.id, command_id: d.cmdId, state, mode: d.mode || 'patrol', position: [p.x, p.y, f.alt],
      heading_deg: compass(p.heading), track_id: d.trackId,
    }, extra);
    sendMessage(c, f.id, stamped(c, f.id, 'drone_state', body, t), t);
  }

  // ---- the C2 side
  function issueCommands(c, t) {
    const todo = c.cmd.script;
    while (todo.length && todo[0].t <= t + 1e-9) startCommand(c, todo.shift(), t);
    Object.keys(c.cmd.open).forEach((id) => {
      const o = c.cmd.open[id];
      if (t < o.next - 1e-9) return;
      if (o.rec.attempts < MAX_ATTEMPTS) transmit(c, o, t);
      else giveUp(c, o, t);
    });
  }
  function startCommand(c, cmd, t) {
    const id = cmd.command_id || 'cmd-' + (++c.cmd.count);
    const body = Object.assign({}, cmd, { command_id: id });
    delete body.t;
    const rec = { command_id: id, drone_id: cmd.drone_id, command: cmd.command, t_issued: t, attempts: 0, t_acked: null, status: 'sent', reports: [] };
    c.cmd.records[id] = rec;
    const o = c.cmd.open[id] = { body, rec, next: t };
    transmit(c, o, t);
  }
  function transmit(c, o, t) {
    o.rec.attempts++;
    o.next = t + ACK_TIMEOUT_S;
    sendMessage(c, o.body.drone_id, stamped(c, 'C2', 'drone_command', o.body, t), t);
  }
  function giveUp(c, o, t) {
    o.rec.status = 'lost';
    delete c.cmd.open[o.rec.command_id];
    c.alerts.push({ t, sev: 'warn', text: 'No ack from ' + o.rec.drone_id + ' for ' + o.rec.command + ' after ' + o.rec.attempts + ' tries' });
  }
  function onState(c, m, t) {
    const rec = c.cmd.records[m.command_id];
    if (!rec) return;
    const last = rec.reports[rec.reports.length - 1];
    if (!last || last.state !== m.state) rec.reports.push({ t, state: m.state, mode: m.mode }); // repeats of a state are not new news
    if (m.state !== 'accepted' && m.state !== 'rejected') return;
    if (rec.t_acked === null) {
      rec.t_acked = t; rec.status = m.state;
      c.alerts.push({ t, sev: 'info', text: rec.drone_id + ' ' + m.state + ' ' + rec.command });
    }
    delete c.cmd.open[m.command_id];
  }
  // control messages are handled here; the rest go on to the tracker
  function handleControl(c, t, arrived) {
    arrived.forEach((m) => {
      if (m.type === 'drone_command') onCommand(c, m, t);
      else if (m.type === 'drone_state') onState(c, m, t);
      else if (m.type === 'c2_ack') onAck(c, m, t);
    });
    return arrived.filter((m) => m.type !== 'drone_command' && m.type !== 'drone_state' && m.type !== 'c2_ack');
  }

  // ------------------------------------------------------------ native records
  // The record a sensor reports for one detection: only its native fields, with noise.
  function makeRecord(s, d, sp, t, isGround, rand, clutter) {
    const rec = { k: s.kind, node: s.node, module: s.module, t, sx: sp.x, sy: sp.y, svx: sp.vx || 0, svy: sp.vy || 0, rmax: s.range, latency: s.latency, merged: d.n > 1, clutter: !!clutter };
    const ctx = {
      s, d, sp, rand, nz: s.noise, nm: s.nm, r: d.r,
      tgtAlt: d.o.alt || (d.o.kind === 'friendly' ? ALT.friendly : ALT.hostile),
      own: isGround ? ALT.ground : (sp.alt || ALT.friendly),
    };
    (RECORD_BUILDERS[s.native] || buildRangeAzimuth)(rec, ctx);
    return rec;
  }
  // the bearing every bearing-type sensor reports, with its noise
  // rec.sd = 1-sigma noise of each native field, which becomes the observation's covariance
  function addBearing(rec, x) {
    const sigB = x.nz.bearing_deg * D2R * x.nm;
    rec.m = 'bearing'; rec.b = x.d.az + gauss(x.rand) * sigB; rec.sigB = sigB;
    rec.sd = { bearing_deg: sigB * RAD2DEG };
  }
  const logRange = (r) => 20 * Math.log10(Math.max(r, 1));
  function buildBearingElevation(rec, x) {
    const { s, d, nz, nm, r, rand } = x;
    addBearing(rec, x);
    const elev = Math.atan2(x.tgtAlt - x.own, r) * RAD2DEG + gauss(rand) * nz.elevation_deg * nm;
    const pRight = Math.max(0.5, 0.95 - 0.45 * (r / s.range)); // the classifier gets worse with distance
    const truthClass = d.o.kind === 'friendly' ? 'friendly' : 'unknown';
    const hint = rand() < pRight ? truthClass : (truthClass === 'friendly' ? 'unknown' : 'friendly');
    const extra = s.kind === 'IR' ? { intensity: Math.max(0, 1 - 0.5 * r / s.range + gauss(rand) * 0.05) } : { class_hint: hint };
    rec.fields = Object.assign({ bearing_deg: compass(rec.b), elevation_deg: elev }, extra);
    rec.sd.elevation_deg = nz.elevation_deg * nm;
  }
  function buildBearingLevel(rec, x) {
    addBearing(rec, x);
    rec.fields = { bearing_deg: compass(rec.b), level_db: 90 - logRange(x.r) + gauss(x.rand) * x.nz.level_db * x.nm, presence: true };
    rec.sd.level_db = x.nz.level_db * x.nm;
  }
  function buildLevel(rec, x) {
    const { nz, nm } = x;
    const lv = nz.source_level_db - logRange(x.r) + gauss(x.rand) * nz.level_db * nm; // a single microphone only hears how loud it is
    rec.m = 'range'; rec.r = Math.pow(10, (nz.source_level_db - lv) / 20);
    rec.sigR = rec.r * (Math.LN10 / 20) * nz.level_db * nm;
    rec.fields = { level_db: lv, presence: true };
    rec.sd = { level_db: nz.level_db * nm };
  }
  function buildBearingRssi(rec, x) {
    addBearing(rec, x);
    rec.fields = {
      bearing_deg: compass(rec.b), rssi_dbm: -40 - logRange(x.r) + gauss(x.rand) * x.nz.rssi_db * x.nm,
      center_freq_mhz: x.d.o.kind === 'friendly' ? 5745 : 2437,
    };
    rec.sd.rssi_dbm = x.nz.rssi_db * x.nm;
  }
  function buildRangeAzimuth(rec, x) {
    const { nz, nm, d, sp, rand } = x;
    const sigR = nz.range_m * nm, sigB = nz.azimuth_deg * D2R * nm, sigRR = nz.radial_mps * nm;
    rec.m = 'rangeaz'; rec.r = x.r + gauss(rand) * sigR; rec.b = d.az + gauss(rand) * sigB;
    rec.sigR = sigR; rec.sigB = sigB; rec.sigRR = sigRR;
    const ux = Math.cos(d.az), uy = Math.sin(d.az);
    rec.rr = (d.vx - (sp.vx || 0)) * ux + (d.vy - (sp.vy || 0)) * uy + gauss(rand) * sigRR;
    rec.fields = { range_m: rec.r, azimuth_deg: compass(rec.b), radial_mps: rec.rr, snr_db: 20 - 20 * Math.log10(Math.max(x.r, 1) / 100) + gauss(rand) };
    rec.sd = { range_m: sigR, azimuth_deg: sigB * RAD2DEG, radial_mps: sigRR };
  }
  const RECORD_BUILDERS = {
    bearing_elevation: buildBearingElevation, bearing_level: buildBearingLevel, level: buildLevel,
    bearing_rssi: buildBearingRssi, range_azimuth_doppler: buildRangeAzimuth,
  };

  // targets closer than the cell in range and azimuth merge into one detection at their centroid
  function mergeCells(seen, cell) {
    const out = [], used = new Array(seen.length).fill(false);
    for (let i = 0; i < seen.length; i++) {
      if (used[i]) continue;
      const grp = [seen[i]];
      used[i] = true;
      for (let j = i + 1; j < seen.length; j++) {
        if (used[j]) continue;
        if (Math.abs(seen[j].r - seen[i].r) < cell.range_m && Math.abs(wrapPi(seen[j].az - seen[i].az)) < cell.azimuth_deg * D2R) {
          grp.push(seen[j]); used[j] = true;
        }
      }
      const n = grp.length, avg = (key) => grp.reduce((acc, g) => acc + g[key], 0) / n;
      // Bearings on either side of -pi/pi have a mean near west, not east.
      const az = Math.atan2(grp.reduce((sum,g)=>sum+Math.sin(g.az),0), grp.reduce((sum,g)=>sum+Math.cos(g.az),0));
      out.push({ x: avg('x'), y: avg('y'), vx: avg('vx'), vy: avg('vy'), r: avg('r'), az, n, sq: grp[0].sq, o: grp[0].o });
    }
    return out;
  }

  const SCEN = prepare(DEFAULT_SCENARIO), DEFAULT_ASSIGN = SCEN.assign;
  global.Sim = { run, prepare, DT, T_END, NF, EVAL, PLATFORMS, MODULES, DEFAULT_SCENARIO, SCEN, DEFAULT_ASSIGN };
  if (typeof module !== 'undefined') module.exports = global.Sim;
})(typeof window !== 'undefined' ? window : globalThis);
