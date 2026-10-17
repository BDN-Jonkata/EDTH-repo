/* DDS viewer: replays a precomputed Sim.run() result on the map. */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const NS = 'http://www.w3.org/2000/svg';
  const scen = () => (S.res && S.res.scen) || S.world; // the scenario of the current run
  const COL = { h: '#FF5A5F', f: '#5B9BFF', u: '#F5B13D', line: '#C9D1DB', cyan: '#3FC1D9' };
  const CLASS_NAME = { friendly: 'Friendly', hostile: 'Hostile', suspicious: 'Suspicious', peaceful: 'Peaceful', unknown: 'Unknown' };
  const PATTERN_NAME = { hover: 'Hovering', transit: 'Transit', orbit: 'Orbit / survey', pursuit: 'Responsive pursuit', maneuvering: 'Maneuvering', insufficient_history: 'Collecting history' };
  const REASON_NAME = { insufficient_history: 'Collecting enough observed history', ambiguous_motion: 'No clear risk pattern',
    sustained_safe_transit: 'Sustained steady transit', consistent_orbit: 'Consistent orbit',
    developing_transit_pattern: 'Transit pattern still developing', authorized_corridor_transit: 'Consistent authorized transit',
    resembles_verified_patrol_only: 'Similar movement does not verify identity', converging_traffic: 'Course converges with observed traffic',
    sustained_collision_course: 'Sustained predicted intercept with a moving ally', repeated_intercept_approaches: 'Repeated intercept approaches',
    responsive_pursuit: 'Follows repeated course changes made by an ally', pursuit_with_intercept_risk: 'Responsive pursuit with aggressive closure / intercept risk',
    recent_encounter_evidence: 'Earlier encounter evidence is decaying' };
  const classColor = (cls) => ({ friendly: COL.f, hostile: COL.h, suspicious: COL.u, peaceful: '#5FD0C0', unknown: '#A9B3BF' }[cls] || COL.u);
  const percent = (value) => (Math.max(0, Math.min(1, value)) * 100).toFixed(1) + '%';
  const Y = (n) => 1000 - n; // world North -> svg y

  const clone = (p) => Object.assign({}, p, { assign: Object.assign({}, p.assign) });
  const nodeIds = () => S.world.friendlies.map((f) => f.id).concat(S.world.ground.map((g) => g.id));
  // a scenario asks for its own weather, platforms and degradations; they become the starting settings
  function defaultsFor(sc) {
    const d = sc.degradations, net = d.network, lat = net.latency_ms || [0, 0];
    const anyDeg = net.enabled || d.clock.enabled || d.pose.enabled || (d.dropout || []).length > 0;
    return {
      preset: sc.preset || 'challenge', seed: sc.seed, name: sc.name, mode: anyDeg ? 'realistic' : 'optimistic', weather: sc.environment.weather, sky: sc.environment.sky || null,
      loss: net.enabled ? Math.round(net.loss * 100) : 0, delayMs: net.enabled ? Math.round((lat[0] + lat[1]) / 2) : 0,
      driftMs: d.clock.enabled ? d.clock.offset_ms[1] : 0, bandwidthKbps: net.enabled ? (net.bandwidth_kbps || null) : null, assign: Sim.prepare(sc).assign,
    };
  }
  const KINDS = { eo_camera: 'EO', thermal_camera: 'IR', microphone: 'MIC', rf_receiver: 'RF', radar: 'RAD' };
  const LAYERS = [
    ['terrain', 'Terrain / height', true, '<path d="M1 11c3-6 5-8 6-8s3 2 6 8" fill="none" stroke="#9AA4B2" stroke-width="1.4"/>'],
    ['truth', 'Ground truth', true, '<circle cx="7" cy="7" r="4" fill="none" stroke="#E6EAF0" stroke-width="1.4"/>'],
    ['tracks', 'Fused tracks', true, '<path d="M7 1l6 6-6 6-6-6z" fill="none" stroke="#FF5A5F" stroke-width="1.4"/>'],
    ['unc', 'Uncertainty', true, '<ellipse cx="7" cy="7" rx="6" ry="3.5" fill="none" stroke="#C9D1DB" stroke-width="1.2"/>'],
    ['pred', 'Predictions', true, '<path d="M1 7h12" stroke="#C9D1DB" stroke-width="1.4" stroke-dasharray="1.5 2"/>'],
    ['raw', 'Raw observations', false, '<path d="M1 13L13 3M1 13L13 8" stroke="#C9D1DB" stroke-width="1"/>'],
    ['cover', 'Sensor coverage', true, '<path d="M2 12L7 2l5 10z" fill="none" stroke="#9AA4B2" stroke-width="1.2" stroke-dasharray="2 1.5"/>'],
    ['coverageAge', 'Coverage age', false, '<rect x="2" y="2" width="10" height="10" fill="#3FC1D9" opacity="0.5"/>'],
    ['missions', 'Mission destinations', true, '<path d="M1 12L12 2M7 2h5v5" fill="none" stroke="#5B9BFF"/>'],
    ['net', 'Network links', true, '<circle cx="2.5" cy="11.5" r="1.8" fill="#9AA4B2"/><circle cx="11.5" cy="2.5" r="1.8" fill="#9AA4B2"/><path d="M3.5 10.5l7-7" stroke="#9AA4B2" stroke-width="1.2"/>'],
  ];

  const S = {
    applied: null, staged: null, scenario: null, world: null, res: null,
    idx: 0, playing: true, speed: 1, acc: 0, last: 0, sel: null, tab: 'time', deg: null,
    layers: {}, view: { x: 0, y: 0, w: 1000, h: 1000 },
  };
  LAYERS.forEach((l) => { S.layers[l[0]] = l[2]; });
  S.scenario = SCENARIOS[new URLSearchParams(location.search).get('preset')] || SCENARIOS.challenge;
  S.world = Sim.prepare(S.scenario);
  S.staged = defaultsFor(S.scenario);

  // ------------------------------------------------------------- helpers
  const fmtT = (t) => { const m = Math.floor(t / 60), s = t - m * 60; return String(m).padStart(2, '0') + ':' + s.toFixed(1).padStart(4, '0'); };
  const pad4 = (v) => String(Math.round(Math.max(0, v))).padStart(4, '0');
  const hdg = (vx, vy) => (((Math.atan2(vx, vy) * 180) / Math.PI) + 360) % 360;
  const spd = (vx, vy) => Math.hypot(vx, vy);
  function elev(x, y) {
    const g = (cx, cy, sx, sy, a) => a * Math.exp(-(((x - cx) / sx) ** 2 + ((y - cy) / sy) ** 2));
    return 205 + g(730, 748, 300, 225, 38) + g(160, 180, 120, 90, 15);
  }
  function eig(pxx, pyy, pxy) {
    const tr = (pxx + pyy) / 2, d = Math.sqrt(Math.max(0, ((pxx - pyy) / 2) ** 2 + pxy * pxy));
    return { a: Math.sqrt(Math.max(0.01, tr + d)), b: Math.sqrt(Math.max(0.01, tr - d)), th: 0.5 * Math.atan2(2 * pxy, pxx - pyy) };
  }
  const frame = () => S.res.frames[S.idx];
  const el = (tag, attrs) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); return e; };

  // ---------------------------------------------------------- static map
  const TERRAIN = `
<ellipse cx="700" cy="225" rx="330" ry="250" fill="#FFF" opacity="0.022"/><ellipse cx="775" cy="290" rx="330" ry="250" fill="#000" opacity="0.22"/>
<ellipse cx="712" cy="236" rx="190" ry="140" fill="#FFF" opacity="0.03"/><ellipse cx="752" cy="272" rx="190" ry="140" fill="#000" opacity="0.18"/>
<ellipse cx="150" cy="805" rx="170" ry="125" fill="#FFF" opacity="0.02"/><ellipse cx="185" cy="840" rx="170" ry="125" fill="#000" opacity="0.18"/>
<g stroke="#FFF" stroke-opacity="0.045"><path d="M100 0V1000M200 0V1000M300 0V1000M400 0V1000M500 0V1000M600 0V1000M700 0V1000M800 0V1000M900 0V1000M0 100H1000M0 200H1000M0 300H1000M0 400H1000M0 500H1000M0 600H1000M0 700H1000M0 800H1000M0 900H1000"/></g>
<g class="t" style="font-size:9px;fill:#6F7B89"><text x="103" y="12">E100</text><text x="303" y="12">E300</text><text x="503" y="12">E500</text><text x="703" y="12">E700</text><text x="4" y="197">N800</text><text x="4" y="397">N600</text><text x="4" y="597">N400</text><text x="4" y="797">N200</text></g>
<path d="M1000 840C900 880 820 900 760 940S650 990 620 1000" fill="none" stroke="#24404A" stroke-width="5"/><text class="t" x="820" y="925" style="font-style:italic;fill:#6F8A94">brook</text>
<g transform="rotate(-12 730 252)" fill="none"><ellipse cx="730" cy="252" rx="410" ry="310" stroke="#2E3944" stroke-width="1.1"/><ellipse cx="730" cy="252" rx="300" ry="225" stroke="#3B4855" stroke-width="1.6"/><ellipse cx="730" cy="252" rx="200" ry="150" stroke="#2E3944" stroke-width="1.1"/><ellipse cx="730" cy="252" rx="110" ry="80" stroke="#3B4855" stroke-width="1.6"/>
<text class="t" x="730" y="175" text-anchor="middle">240</text><text class="t" x="730" y="105" text-anchor="middle">230</text><text class="t" x="430" y="256" text-anchor="middle">220</text><text class="t" x="320" y="256" text-anchor="middle">210</text></g>
<g fill="none"><ellipse cx="160" cy="820" rx="150" ry="110" stroke="#2E3944" stroke-width="1.1"/><ellipse cx="160" cy="820" rx="70" ry="50" stroke="#3B4855" stroke-width="1.6"/></g>
<text class="t" x="160" y="713" text-anchor="middle">210</text><text class="t" x="160" y="773" text-anchor="middle">220</text><path d="M724 246l6-10 6 10z" fill="#9AA4B2"/><text class="t" x="742" y="250">243 m</text>
<g fill="none" stroke-linecap="round"><path d="M0 610C220 590 400 520 540 500S820 460 1000 420" stroke="#2C3642" stroke-width="15"/><path d="M505 0C510 180 520 340 528 500S545 800 560 1000" stroke="#2C3642" stroke-width="12"/><path d="M0 610C220 590 400 520 540 500S820 460 1000 420" stroke="#161D25" stroke-width="11"/><path d="M505 0C510 180 520 340 528 500S545 800 560 1000" stroke="#161D25" stroke-width="8"/></g>
<text class="t" x="70" y="590" transform="rotate(-4 70 590)">MAIN RD</text>
<g fill="#1C242E" stroke="#4A5664"><rect x="410" y="440" width="40" height="26"/><rect x="460" y="430" width="30" height="34"/><rect x="560" y="440" width="46" height="30"/><rect x="615" y="450" width="30" height="24"/><rect x="400" y="520" width="36" height="30"/><rect x="445" y="535" width="50" height="28"/><rect x="565" y="520" width="40" height="40"/><rect x="612" y="515" width="28" height="22"/><rect x="420" y="580" width="30" height="30"/><rect x="470" y="590" width="44" height="26"/><rect x="560" y="580" width="36" height="28"/><rect x="606" y="574" width="40" height="30"/><rect x="652" y="480" width="28" height="22"/><rect x="360" y="470" width="28" height="24"/><rect x="480" y="360" width="30" height="26"/><rect x="580" y="380" width="34" height="24"/><rect x="700" y="430" width="40" height="28"/><rect x="330" y="560" width="30" height="26"/></g>
<g class="t" text-anchor="middle" style="font-size:9px;fill:#A9B3BF;stroke-width:0"><text x="430" y="456">8 m</text><text x="475" y="450">6 m</text><text x="583" y="458">12 m</text><text x="630" y="465">7 m</text><text x="418" y="538">6 m</text><text x="470" y="552">9 m</text><text x="585" y="543">15 m</text><text x="492" y="606">7 m</text><text x="626" y="592">10 m</text><text x="495" y="376">6 m</text><text x="597" y="395">8 m</text><text x="720" y="447">12 m</text></g>`;
  const FURNITURE = `
<g transform="translate(958 54)"><circle r="22" fill="#0F141A" stroke="#2C3644"/><path d="M0 -15L7 8L0 3L-7 8Z" fill="#E6EAF0"/><text class="tb" y="-26" text-anchor="middle" fill="#E6EAF0" style="font-size:10px">N</text></g>
<g transform="translate(28 958)"><rect x="-8" y="-24" width="232" height="40" rx="3" fill="#0F141A" fill-opacity="0.9" stroke="#2C3644"/><rect x="0" y="0" width="100" height="6" fill="#E6EAF0"/><rect x="100" y="0" width="100" height="6" fill="#0F141A" stroke="#E6EAF0"/>
<text class="tb" x="0" y="-8" fill="#C9D1DB" style="font-size:10px;font-weight:400">0</text><text class="tb" x="100" y="-8" text-anchor="middle" fill="#C9D1DB" style="font-size:10px;font-weight:400">100</text><text class="tb" x="200" y="-8" text-anchor="middle" fill="#C9D1DB" style="font-size:10px;font-weight:400">200 m</text></g>`;

  // ------------------------------------------------------------- run / apply
  function runSim(p) {
    S.applied = clone(p);
    S.wx = Weather.providerFor(S.scenario.environment, p.weather, p.sky !== undefined ? p.sky : S.scenario.environment.sky).provider; // as in Sim.run
    S.res = Sim.run({ seed: p.seed, mode: p.mode, weather: p.weather, sky: p.sky, loss: p.loss, delayMs: p.delayMs, driftMs: p.driftMs, bandwidthKbps: p.bandwidthKbps, assign: p.assign, scenario: S.scenario });
    S.deg = null; S.idx = 0; S.acc = 0; S.last = 0; S.playing = true; S.sel = null; S.userSel = false;
    $('runTitle').textContent = scen().id + ' · ' + p.name + ' · seed ' + p.seed;
    $('tTotal').textContent = fmtT(S.res.T_END);
    $('scrub').max = S.res.NF;
    $('modeChip').textContent = p.mode.toUpperCase();
    $('modeChip').className = 'chip ' + (p.mode === 'optimistic' ? 'cyan' : 'amber');
    buildTimeline();
    render();
  }
  function degradation() {
    if (S.deg) return S.deg;
    const p = S.applied, out = [];
    for (let l = 0; l <= 90; l += 10) {
      const r = Sim.run({ seed: p.seed, mode: 'realistic', weather: p.weather, sky: p.sky, loss: l, delayMs: p.delayMs, driftMs: p.driftMs, bandwidthKbps: p.bandwidthKbps, assign: p.assign, scenario: S.scenario }, { lite: true });
      out.push({ loss: l, rmse: r.summary.rmse, count: r.summary.countErr, swaps: r.summary.swaps, ffa: r.summary.ffa });
    }
    S.deg = out;
    return out;
  }

  // --------------------------------------------------------------- left panel
  // ---- models per node (platforms come from the catalog)
  function buildLoadout() {
    const box = $('loadout');
    box.innerHTML = '';
    nodeIds().forEach((id) => {
      const ground = id.startsWith('GS');
      const opts = Object.values(Sim.PLATFORMS).filter((p) => p.platform === (ground ? 'ground' : 'uas'));
      const row = document.createElement('div');
      row.className = 'node-row';
      row.innerHTML = '<label><b>' + id + '</b><select aria-label="Platform for ' + id + '" data-node="' + id + '">' +
        opts.map((p) => '<option value="' + p.id + '">' + p.name + '</option>').join('') + '</select></label><div class="mods" id="mods-' + id + '"></div>';
      box.appendChild(row);
    });
    renderLoadout();
  }
  function renderLoadout() {
    const wx = S.staged.weather, effects = Weather.activeEffects(Weather.providerFor({}, wx, S.staged.sky).provider.at([0, 0], 0));
    nodeIds().forEach((id) => {
      const sel = document.querySelector('select[data-node="' + id + '"]');
      if (sel) sel.value = S.staged.assign[id];
      const plat = Sim.PLATFORMS[S.staged.assign[id]];
      $('mods-' + id).innerHTML = plat.modules.filter((l) => KINDS[Sim.MODULES[l.module_id].kind]).map((l) => {
        const m = Sim.MODULES[l.module_id], q = Weather.sensorQuality(m, effects);
        const bad = q.range < 0.7 || q.pd < 0.8;
        return '<span class="mod' + (bad ? ' warn' : '') + '" title="' + m.name + (bad ? ' (degraded in ' + wx + ')' : '') + '">' + KINDS[m.kind] + (bad ? ' ▼' : '') + '</span>';
      }).join('');
    });
  }

  // ?weather=fog+wind (a '+' in a URL reads as a space)
  function setWeatherFromUrl(text) {
    if (!text) return;
    try { Weather.parseWeather(text.replace(/ /g, '+')); S.staged.weather = text.replace(/ /g, '+'); } catch (e) { /* not a weather: keep the preset's */ }
  }
  function buildLeft() {
    const box = $('layers');
    LAYERS.forEach((l) => {
      const lab = document.createElement('label');
      lab.className = 'lyr';
      lab.innerHTML = '<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">' + l[3] + '</svg><span class="n">' + l[1] + '</span><input class="sw" type="checkbox"' + (l[2] ? ' checked' : '') + '>';
      lab.querySelector('input').addEventListener('change', (e) => { S.layers[l[0]] = e.target.checked; render(); });
      box.appendChild(lab);
    });
    $('loadout').addEventListener('change', (e) => {
      const sel = e.target.closest('select');
      if (sel) { S.staged.assign[sel.dataset.node] = sel.value; renderLoadout(); }
    });
    $('preset').innerHTML = Object.keys(SCENARIOS).map((id) => '<option value="' + id + '">' + id + '</option>').join('');
    $('preset').addEventListener('change', (e) => choosePreset(e.target.value));
    buildLoadout();
    seg('modeSeg', (v) => { S.staged.mode = v; syncStaged(); });
    WeatherUI.init((weather, sky) => { S.staged.weather = weather; S.staged.sky = sky; syncStaged(); renderLoadout(); });
    seg('speedSeg', (v) => { S.speed = parseFloat(v); });
    $('seed').addEventListener('input', (e) => { S.staged.seed = Math.max(1, parseInt(e.target.value, 10) || 1); });
    $('name').addEventListener('input', (e) => { S.staged.name = e.target.value; });
    $('newSeed').addEventListener('click', () => { S.staged.seed = 1 + Math.floor(Math.random() * 9999); $('seed').value = S.staged.seed; });
    $('loss').addEventListener('input', (e) => { S.staged.loss = +e.target.value; syncStaged(); });
    $('delay').addEventListener('input', (e) => { S.staged.delayMs = Math.max(0, +e.target.value || 0); });
    $('drift').addEventListener('input', (e) => { S.staged.driftMs = Math.max(0, +e.target.value || 0); });
    $('cap').addEventListener('input', (e) => { S.staged.bandwidthKbps = +e.target.value > 0 ? +e.target.value : null; });
    $('apply').addEventListener('click', applyStaged);
    $('reset').addEventListener('click', () => choosePreset(S.staged.preset));
  }
  // ---- scenarios: generated by the seeder; serve.py makes any preset and seed, otherwise only the default seeds are available
  function loadScenario(preset, seed) {
    return fetch('/api/scenario?preset=' + encodeURIComponent(preset) + '&seed=' + seed)
      .then((r) => r.json().then((j) => { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; }))
      .catch((e) => {
        if (!(e instanceof TypeError || e instanceof SyntaxError)) throw e; // a real error from the generator
        const fixed = SCENARIOS[preset]; // no generator here (opened as a file, or plain http.server)
        $('presetNote').textContent = fixed.seed === seed ? fixed.description : 'Run serve.py to change the seed. Showing the default seed ' + fixed.seed + '.';
        return fixed;
      });
  }
  function useScenario(sc) {
    S.scenario = sc; S.world = Sim.prepare(sc);
  }
  function choosePreset(id) {
    loadScenario(id, SCENARIOS[id].seed).then((sc) => {
      useScenario(sc);
      S.staged = defaultsFor(sc);
      fillInputs(); syncStaged(); buildLoadout();
      $('presetNote').textContent = sc.description;
      runSim(S.staged);
    }).catch((e) => { $('presetNote').textContent = 'Could not generate: ' + e.message; });
  }
  function applyStaged() {
    loadScenario(S.staged.preset, S.staged.seed).then((sc) => {
      useScenario(sc);
      S.staged.seed = sc.seed; $('seed').value = sc.seed;
      buildLoadout();
      runSim(S.staged);
    }).catch((e) => { $('presetNote').textContent = 'Could not generate: ' + e.message; });
  }
  function seg(id, fn) {
    const box = $(id);
    box.addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (!b) return;
      box.querySelectorAll('button').forEach((x) => { x.classList.toggle('on', x === b); x.setAttribute('aria-checked', x === b); });
      fn(b.dataset.v);
    });
  }
  function setSeg(id, v) {
    $(id).querySelectorAll('button').forEach((x) => { const on = x.dataset.v === String(v); x.classList.toggle('on', on); x.setAttribute('aria-checked', on); });
  }
  function fillInputs() {
    const s = S.staged;
    $('preset').value = s.preset; $('seed').value = s.seed; $('name').value = s.name; $('loss').value = s.loss; $('delay').value = s.delayMs; $('drift').value = s.driftMs; $('cap').value = s.bandwidthKbps || '';
    setSeg('modeSeg', s.mode); WeatherUI.show(s.weather, s.sky);
  }
  function syncStaged() {
    const s = S.staged, opt = s.mode === 'optimistic';
    $('comms').disabled = opt;
    $('commsLegend').textContent = opt ? 'Comms impairments, locked in Optimistic' : 'Comms impairments';
    $('modeNote').textContent = opt
      ? 'Ideal comms: no loss, no delay, synced clocks. Sensor noise still on.'
      : 'Lossy, delayed links and drifting node clocks. Press Apply & restart to run.';
    $('lossVal').textContent = s.loss + '%';
    $('wxNote').textContent = WeatherUI.describe(s.weather);
  }

  // --------------------------------------------------------------- map layers
  const KCOL = { EO: '#C9D1DB', IR: '#E58C5B', MIC: '#F5B13D', RAD: '#3FC1D9', RF: '#B58CFF' };
  const KDASH = { EO: '5 4', IR: '4 3', MIC: '1 4', RAD: '8 3', RF: '2 5' };
  // Patrol drones face their motion; followers and searchers can yaw to observe.
  function nodeState(f, id) {
    const g = scen().ground.find((q) => q.id === id);
    if (g) return { x: g.x, y: g.y, heading: g.heading };
    const o = f.truth.find((q) => q.id === id);
    return o ? { x: o.x, y: o.y, heading: o.heading === undefined ? Math.atan2(o.vy, o.vx) : o.heading } : null;
  }
  // each sensor's real coverage: a wedge for pointed sensors, a ring for 360-degree ones
  function coverageSvg(f) {
    const out = [];
    S.res.sensors.forEach((s) => {
      const n = nodeState(f, s.node);
      if (!n) return;
      const col = KCOL[s.kind], r = Math.round(rangeNow(s, f));
      const common = 'fill="' + col + '" fill-opacity="0.045" stroke="' + col + '" stroke-opacity="0.45" stroke-dasharray="' + KDASH[s.kind] + '" stroke-width="1.2"';
      let labelAt;
      if (s.fovDeg >= 360) {
        out.push('<circle cx="' + n.x + '" cy="' + Y(n.y) + '" r="' + r + '" ' + common.replace('fill-opacity="0.045"', 'fill-opacity="0.015"') + '/>');
        labelAt = [n.x + r * Math.cos(2.4), Y(n.y) - r * Math.sin(2.4)];
      } else {
        const h = s.fovDeg * Math.PI / 360, a0 = n.heading - h, a1 = n.heading + h;
        const p0 = [n.x + r * Math.cos(a0), Y(n.y + r * Math.sin(a0))], p1 = [n.x + r * Math.cos(a1), Y(n.y + r * Math.sin(a1))];
        out.push('<path d="M' + n.x + ' ' + Y(n.y) + 'L' + p0[0].toFixed(1) + ' ' + p0[1].toFixed(1) + 'A' + r + ' ' + r + ' 0 ' + (s.fovDeg > 180 ? 1 : 0) + ' 0 ' + p1[0].toFixed(1) + ' ' + p1[1].toFixed(1) + 'Z" ' + common + '/>');
        labelAt = [n.x + r * Math.cos(n.heading), Y(n.y + r * Math.sin(n.heading))];
      }
      if (s.node.startsWith('GS')) out.push('<text class="t" x="' + labelAt[0].toFixed(0) + '" y="' + labelAt[1].toFixed(0) + '" text-anchor="middle">' + s.kind + ' ' + Math.round(r) + ' m' + (s.fovDeg < 360 ? ' ∠' + s.fovDeg + '°' : '') + '</text>');
    });
    return out.join('');
  }
  function drawLinks(f, out) {
    const c2 = scen().c2;
    const nodes = scen().ground.map((g) => ({ id: g.id, x: g.x, y: g.y })).concat(f.truth.filter((o) => o.kind === 'friendly').map((o) => ({ id: o.id, x: o.x, y: o.y })));
    nodes.forEach((n) => {
      const q = f.links[n.id] === undefined ? 1 : f.links[n.id];
      const col = q > 0.9 ? '#7D8794' : q > 0.5 ? '#F5B13D' : '#FF5A5F';
      const dash = q > 0.9 ? '' : q > 0.5 ? '6 4' : '2 5';
      out.push('<path d="M' + n.x + ' ' + Y(n.y) + 'L' + c2.x + ' ' + Y(c2.y) + '" stroke="' + col + '" stroke-width="1.2" stroke-opacity="0.8" stroke-dasharray="' + dash + '" fill="none"/>');
      out.push('<text class="t" text-anchor="middle" style="font-size:9px;fill:#8B96A5" x="' + ((n.x + c2.x) / 2) + '" y="' + (Y((n.y + c2.y) / 2) - 4) + '">' + Math.round((1 - q) * 100) + '%</text>');
    });
  }
  function ellipseSvg(x, y, p, color, dash, k) {
    const e = eig(p.pxx, p.pyy, p.pxy);
    const a = Math.min(150, e.a * k), b = Math.min(150, e.b * k);
    return '<ellipse cx="' + x + '" cy="' + Y(y) + '" rx="' + a.toFixed(1) + '" ry="' + b.toFixed(1) + '" transform="rotate(' + (-e.th * 180 / Math.PI).toFixed(1) + ' ' + x + ' ' + Y(y) + ')" fill="' + color + '" fill-opacity="0.08" stroke="' + color + '" stroke-opacity="0.75"' + (dash ? ' stroke-dasharray="4 3"' : '') + '/>';
  }
  function trackSvg(t, f, sel) {
    const x = t.x, y = Y(t.y);
    const col = classColor(t.cls);
    const sp = spd(t.vx, t.vy);
    const coast = t.st === 'coasting';
    const o = ['<g' + (coast ? ' opacity="0.55"' : '') + '>'];
    if (S.layers.unc && t.cls !== 'friendly') o.push(ellipseSvg(t.x, t.y, t, col, t.st === 'tentative' || coast, 2.45));
    if (S.layers.pred && t.cls === 'hostile') o.push(predictionSvg(t, col));
    if (t.cls !== 'friendly') o.push(trailSvg(t, f, col));
    if (sp > 0.5) o.push(headingSvg(t, sp, col));
    o.push(glyphSvg(t, col));
    if (sel) o.push('<circle cx="' + x + '" cy="' + y + '" r="20" fill="none" stroke="#8FE3F2" stroke-width="1.4"/>');
    o.push(labelSvg(t, col, sp, sel));
    o.push('</g>');
    return o.join('');
  }
  // where a hostile will be in 10 s: a widening cone around its velocity
  function predictionSvg(t, col) {
    const x = t.x, y = Y(t.y);
    const L = 10, ex = t.x + t.vx * L, ey = t.y + t.vy * L;
    const w = Math.min(120, 2.45 * Math.sqrt(Math.max(t.pxx, t.pyy)) + 3 * L);
    const n = Math.hypot(t.vx, t.vy) || 1, nx = -t.vy / n, ny = t.vx / n;
    return '<path d="M' + x + ' ' + y + 'L' + (ex + nx * w) + ' ' + Y(ey + ny * w) + 'L' + (ex - nx * w) + ' ' + Y(ey - ny * w) + 'Z" fill="' + col + '" fill-opacity="0.06"/>' +
      '<path d="M' + x + ' ' + y + 'L' + ex + ' ' + Y(ey) + '" stroke="' + col + '" stroke-width="1.6" stroke-dasharray="1.5 4" stroke-linecap="round" fill="none"/>';
  }
  // the last 4 s of the track, one fading segment per second
  function trailSvg(t, f, col) {
    let px = t.x, py = t.y, out = '';
    for (let j = 1; j <= 4; j++) {
      const pf = S.res.frames[Math.max(0, f.k - j * 10)];
      const pt = pf && pf.tracks.find((q) => q.id === t.id);
      if (!pt) break;
      out += '<path d="M' + px + ' ' + Y(py) + 'L' + pt.x + ' ' + Y(pt.y) + '" stroke="' + col + '" stroke-width="2" stroke-linecap="round" stroke-opacity="' + (0.65 - j * 0.14).toFixed(2) + '" fill="none"/>';
      px = pt.x; py = pt.y;
    }
    return out;
  }
  function headingSvg(t, sp, col) {
    const x = t.x, y = Y(t.y), mk = { hostile: 'm-r', friendly: 'm-b', suspicious: 'm-a', peaceful: 'm-p', unknown: 'm-n' }[t.cls];
    const L = t.cls === 'friendly' ? 30 : 12 + Math.min(30, sp * 2.4), ux = t.vx / sp, uy = t.vy / sp;
    return '<path d="M' + (x + ux * 12) + ' ' + (y - uy * 12) + 'L' + (x + ux * L) + ' ' + (y - uy * L) + '" stroke="' + col + '" stroke-width="2" marker-end="url(#' + mk + ')"/>';
  }
  // Each flag has its own shape/color; uncertainty does not imply suspicion.
  function glyphSvg(t, col) {
    const x = t.x, y = Y(t.y);
    if (t.cls === 'hostile') return '<path d="M' + x + ' ' + (y - 12) + 'L' + (x + 12) + ' ' + y + 'L' + x + ' ' + (y + 12) + 'L' + (x - 12) + ' ' + y + 'Z" fill="#2A1012" stroke="' + col + '" stroke-width="2"/>';
    if (t.cls === 'friendly') return '<circle cx="' + x + '" cy="' + y + '" r="10" fill="#0E1A2E" stroke="' + col + '" stroke-width="2"/><path d="M' + (x - 4) + ' ' + (y - 4) + 'L' + (x + 4) + ' ' + (y + 4) + 'M' + (x + 4) + ' ' + (y - 4) + 'L' + (x - 4) + ' ' + (y + 4) + '" stroke="' + col + '" stroke-width="1.6"/>';
    if (t.cls === 'suspicious') return '<path d="M' + x + ' ' + (y - 9) + 'L' + (x + 9) + ' ' + (y + 7) + 'L' + (x - 9) + ' ' + (y + 7) + 'Z" fill="#241A08" stroke="' + col + '" stroke-width="2"/>';
    return '<circle cx="' + x + '" cy="' + y + '" r="7" fill="' + (t.cls === 'peaceful' ? '#0B2724' : '#1B222C') + '" stroke="' + col + '" stroke-width="2.2"' + (t.cls === 'unknown' ? ' stroke-dasharray="3 2"' : '') + '/>';
  }
  function labelSvg(t, col, sp, sel) {
    const x = t.x, y = Y(t.y);
    if (t.cls === 'friendly') return '<text class="t tb" x="' + (x + 13) + '" y="' + (y - 11) + '" style="fill:#8DB8FF">' + t.id + '</text>';
    if (t.cls === 'hostile') {
      return '<rect x="' + (x - 13) + '" y="' + (y - 38) + '" width="26" height="16" rx="2" fill="' + col + '"' + (sel ? ' stroke="#E6EAF0" stroke-width="1.5"' : '') + '/><text class="tb" x="' + x + '" y="' + (y - 26) + '" text-anchor="middle" fill="#14080A">' + t.id + '</text>' +
        '<text class="t" x="' + (x + 17) + '" y="' + (y - 26) + '">' + sp.toFixed(0) + ' m/s</text>';
    }
    return '<rect x="' + (x - 13) + '" y="' + (y - 34) + '" width="26" height="16" rx="2" fill="#0D1318" stroke="' + col + '" stroke-dasharray="3 2"/><text class="tb" x="' + x + '" y="' + (y - 22) + '" text-anchor="middle" fill="' + col + '">' + t.id + '</text><text class="t" x="' + (x + 17) + '" y="' + (y - 22) + '" style="fill:' + col + '">' + t.cls.toUpperCase() + '</text>';
  }

  function renderMap(f) {
    $('terrain').innerHTML = S.layers.terrain ? TERRAIN : '';
    $('terrain').style.display = '';
    $('cover').innerHTML = S.layers.cover ? coverageSvg(f) : '';
    $('coverageAge').innerHTML = S.layers.coverageAge && f.coverage ? f.coverage.map((last, i) => {
      const age = last < 0 ? 1 : Math.min(1, (f.t - last) / 60);
      const color = last < 0 ? '#FF5A5F' : age > 0.5 ? '#F5B13D' : '#3FC1D9';
      return '<rect x="' + (i % 40 * 25) + '" y="' + (975 - Math.floor(i / 40) * 25) + '" width="25" height="25" fill="' + color + '" opacity="' + (0.08 + age * 0.22) + '"/>';
    }).join('') : '';
    $('missions').innerHTML = S.layers.missions ? (f.missions || []).map((m) => {
      const d = f.truth.find((q) => q.id === m.id);
      if (!d || !m.destination) return '';
      const g = m.destination, color = m.mode === 'follow' ? '#F5B13D' : m.mode === 'search' ? '#B58CFF' : '#5B9BFF';
      return '<path d="M' + d.x + ' ' + Y(d.y) + 'L' + g.x + ' ' + Y(g.y) + '" fill="none" stroke="' + color + '" stroke-dasharray="3 5" stroke-opacity="0.6"/><circle cx="' + g.x + '" cy="' + Y(g.y) + '" r="4" fill="none" stroke="' + color + '"/><text class="t" x="' + (d.x + 12) + '" y="' + (Y(d.y) + 18) + '" style="fill:' + color + '">' + m.id + ' ' + m.mode.toUpperCase() + (m.target ? ' → ' + m.target : '') + '</text>';
    }).join('') : '';
    $('missionStatus').innerHTML = (f.missions || []).map((m) => '<div><b>' + m.id + '</b> · ' + m.mode.toUpperCase() +
      (m.target ? ' → ' + m.target : '') + (m.destination ? ' · E' + pad4(m.destination.x) + ' N' + pad4(m.destination.y) : '') +
      (m.blocked ? ' · yielding' : '') + '</div>').join('');
    const observed = f.coverage ? f.coverage.filter((last) => last >= 0).length : 0;
    $('coverageStatus').textContent = (observed / 16).toFixed(1) + '% observed · ' + S.res.missionConfig.separation + ' m minimum separation' +
      (S.layers.coverageAge ? ' · red: unvisited · amber: older · cyan: recent (60 s scale)' : '');
    $('jam').innerHTML = S.layers.net ? jammingSvg(f) : '';
    const links = [];
    if (S.layers.net) drawLinks(f, links);
    $('links').innerHTML = links.join('');
    $('fixed').innerHTML = fixedSvg();
    $('furniture').innerHTML = FURNITURE;
    $('raw').innerHTML = S.layers.raw ? f.meas.map(measSvg).join('') : '';
    $('truth').innerHTML = S.layers.truth ? truthSvg(f) : '';
    $('cross').innerHTML = f.cross ? crossSvg(f.cross) : '';
    $('trk').innerHTML = S.layers.tracks ? tracksSvg(f) : '';
  }
  // fixed infrastructure: the C2 node and the ground sensors
  function fixedSvg() {
    const c2 = scen().c2;
    const fx = ['<g transform="translate(' + c2.x + ' ' + Y(c2.y) + ')"><path d="M-9 -9H9V9H-9Z" fill="#141A22" stroke="#9AA4B2" stroke-width="1.5"/><path d="M-5 0H5M0 -5V5" stroke="#9AA4B2" stroke-width="1.5"/></g><text class="t" x="' + (c2.x + 14) + '" y="' + (Y(c2.y) + 18) + '">C2</text>'];
    scen().ground.forEach((g) => {
      const kinds = S.res.sensors.filter((q) => q.node === g.id).map((q) => q.kind).join('·');
      fx.push('<g transform="translate(' + g.x + ' ' + Y(g.y) + ')"><rect x="-8" y="-8" width="16" height="16" fill="#141A22" stroke="#C9D1DB" stroke-width="1.6"/><circle r="3" fill="#C9D1DB"/></g><text class="t" x="' + (g.x + 12) + '" y="' + (Y(g.y) + 22) + '" style="fill:#C9D1DB">' + g.id + ' ' + kinds + '</text>');
    });
    return fx.join('');
  }
  // one raw observation in its native form: a ray (bearing), a ring (range) or a point (range + bearing)
  function measSvg(m) {
    const c = KCOL[m.k], dash = m.clutter ? ' stroke-dasharray="1 3"' : '';
    if (m.m === 'bearing') {
      const L = Math.min(m.rmax, 450);
      return '<path d="M' + m.sx + ' ' + Y(m.sy) + 'L' + (m.sx + L * Math.cos(m.b)).toFixed(1) + ' ' + Y(m.sy + L * Math.sin(m.b)).toFixed(1) + '" stroke="' + c + '" stroke-opacity="0.4" stroke-width="1"' + dash + '/>';
    }
    if (m.m === 'range') {
      return '<circle cx="' + m.sx + '" cy="' + Y(m.sy) + '" r="' + m.r.toFixed(1) + '" fill="none" stroke="' + c + '" stroke-opacity="0.35" stroke-width="1" stroke-dasharray="2 3"/>';
    }
    const x = m.sx + m.r * Math.cos(m.b), y = Y(m.sy + m.r * Math.sin(m.b));
    return '<path d="M' + m.sx + ' ' + Y(m.sy) + 'L' + x.toFixed(1) + ' ' + y.toFixed(1) + '" stroke="' + c + '" stroke-opacity="0.25" stroke-width="1"/>' +
      '<path d="M' + (x - 3).toFixed(1) + ' ' + (y - 3).toFixed(1) + 'l6 6m0 -6l-6 6" stroke="' + c + '" stroke-width="1.4"' + (m.merged ? ' stroke-dasharray="2 1"' : '') + '/>' +
      (m.merged ? '<circle cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="9" fill="none" stroke="' + c + '" stroke-width="1"/>' : '');
  }
  // truth markers, with a residual line to the track matched with each
  function truthSvg(f) {
    const mp = {};
    f.match.forEach((m) => { mp[m[1]] = m[0]; });
    return f.truth.map((o) => {
      if (o.kind === 'clutter') return clutterSvg(o);
      const t = mp[o.id] && f.tracks.find((q) => q.id === mp[o.id]);
      const line = t ? '<path d="M' + o.x + ' ' + Y(o.y) + 'L' + t.x + ' ' + Y(t.y) + '" stroke="#E6EAF0" stroke-width="1" stroke-opacity="0.7"/>' : '';
      return line + '<circle cx="' + o.x + '" cy="' + Y(o.y) + '" r="' + (o.kind === 'hostile' ? 6 : 5) + '" fill="none" stroke="#E6EAF0" stroke-width="1.3"/>';
    }).join('');
  }
  // a bird or vehicle: grey dashed ring with its id, so a track on it reads as a false alarm
  function clutterSvg(o) {
    return '<circle cx="' + o.x + '" cy="' + Y(o.y) + '" r="4" fill="none" stroke="#8B96A5" stroke-width="1.2" stroke-dasharray="2 2"/>' +
      '<text class="t" x="' + (o.x + 7) + '" y="' + (Y(o.y) + 3) + '" style="fill:#8B96A5">' + o.id + '</text>';
  }
  // jamming zones in force at this moment (a comms degradation, so only in Realistic mode)
  function jammingSvg(f) {
    const zones = S.applied.mode === 'realistic' ? ((S.res.scen.deg.network || {}).jamming_zones || []) : [];
    return Jamming.activeZones(zones, f.t).map((z) =>
      '<circle cx="' + z.x + '" cy="' + Y(z.y) + '" r="' + z.radius_m + '" fill="#FF5A5F" fill-opacity="0.07" stroke="#FF5A5F" stroke-width="1.4" stroke-dasharray="3 4"/>' +
      '<text class="t" x="' + z.x + '" y="' + (Y(z.y) - z.radius_m - 6) + '" text-anchor="middle" style="fill:#FF5A5F">JAMMING ' + Math.round(z.loss * 100) + ' % loss</text>').join('');
  }
  function crossSvg(cross) {
    return '<circle class="pulse" cx="' + cross.x + '" cy="' + Y(cross.y) + '" r="48" fill="#F5B13D" fill-opacity="0.07" stroke="#F5B13D" stroke-width="1.6" stroke-dasharray="6 4"/><text class="t" x="' + cross.x + '" y="' + (Y(cross.y) + 66) + '" text-anchor="middle" style="fill:#F5B13D">PRED. CROSSING T−' + cross.tca.toFixed(1) + ' s</text>';
  }
  function tracksSvg(f) {
    const order = { friendly: 0, peaceful: 1, unknown: 2, suspicious: 3, hostile: 4 };
    return f.tracks.slice().sort((a, b) => order[a.cls] - order[b.cls]).map((t) => trackSvg(t, f, t.id === S.sel)).join('');
  }

  // -------------------------------------------------------------- right panel
  function renderRight(f) {
    $('cntEst').textContent = f.m.est; $('cntTrue').textContent = f.m.tru;
    const ok = f.m.est === f.m.tru;
    const chip = $('cntChip');
    chip.className = 'chip ' + (ok ? 'cyan' : 'amber');
    chip.textContent = ok ? '✓ MATCH' : '▲ MISMATCH ' + (f.m.countErr > 0 ? '+' : '') + f.m.countErr;

    const order = { hostile: 0, suspicious: 1, unknown: 2, peaceful: 3, friendly: 4 };
    const list = f.tracks.slice().sort((a, b) => order[a.cls] - order[b.cls] || a.id.localeCompare(b.id, undefined, { numeric: true }));
    const cur = list.find((t) => t.id === S.sel);
    const firstHostile = list.find((t) => t.cls === 'hostile');
    // keep the user's pick; otherwise follow the first hostile once there is one
    if (!cur || (!S.userSel && firstHostile && cur.cls !== 'hostile')) S.sel = (list.find((t) => t.cls === 'hostile') || list[0] || {}).id || null;
    $('trkCount').textContent = list.length + ' active';
    $('assessmentCounts').innerHTML = ['friendly', 'peaceful', 'unknown', 'suspicious', 'hostile'].map((cls) =>
      '<span data-class="' + cls + '" style="padding:3px 5px;border:1px solid #2C3644;border-radius:3px;color:' + classColor(cls) + '">' +
      CLASS_NAME[cls] + ' ' + list.filter((t) => t.cls === cls).length + '</span>').join('');
    $('trkBody').innerHTML = list.map((t) => {
      const cls = { hostile: '◆ HOS', friendly: '● FRD', peaceful: '○ PCF', suspicious: '▲ SUS', unknown: '✣ UNK' }[t.cls];
      const ccol = classColor(t.cls);
      const b = { hostile: 'h', suspicious: 'u', unknown: 'n', peaceful: 'p', friendly: 'f' }[t.cls];
      return '<tr data-id="' + t.id + '"' + (t.id === S.sel ? ' class="sel"' : '') + '><td><button class="idb ' + b + '" aria-label="Select ' + t.id + '">' + t.id + '</button></td><td style="color:' + ccol + '">' + cls + (t.cls === 'unknown' ? '' : ' ' + percent(t.conf)) + '</td><td data-score="identity">' + percent(t.pF) + '</td><td data-score="risk">' + percent(t.pH) + '</td><td>' + pad4(t.x) + ' ' + pad4(t.y) + '</td><td>' + spd(t.vx, t.vy).toFixed(1) + '</td><td>' + String(Math.round(hdg(t.vx, t.vy))).padStart(3, '0') + '</td><td>' + t.age.toFixed(1) + 's</td><td>' + (t.cls === 'friendly' ? 'self' : t.nodes.map((n) => n.split(' ')[0]).filter((v, i, a) => a.indexOf(v) === i).join(' ')) + '</td></tr>';
    }).join('');

    const al = S.res.alerts.filter((a) => a.t <= f.t + 1e-6);
    const warn = al.filter((a) => a.sev === 'warn').length, crit = al.filter((a) => a.sev === 'crit').length;
    $('alertCount').textContent = warn + ' warn · ' + crit + ' crit';
    const sev = { info: ['● INFO', '#C9D1DB'], warn: ['▲ WARN', '#F5B13D'], crit: ['■ CRIT', '#FF5A5F'] };
    const recent = al.slice(-8).reverse();
    $('alerts').innerHTML = recent.length ? recent.map((a) => '<div class="al"><span class="sev" style="color:' + sev[a.sev][1] + '">' + sev[a.sev][0] + '</span><span style="flex:1 1 auto">' + a.text + '</span><span class="mono" style="font-size:11px;color:#8B96A5">' + fmtT(a.t).slice(0, 7) + '</span></div>').join('') : '<div class="empty">No alerts yet.</div>';

    renderFeed(f);
    renderDetail(f);
  }
  const SHORT = { bearing_deg: 'brg', elevation_deg: 'el', level_db: 'lvl', rssi_dbm: 'rssi', center_freq_mhz: 'f', range_m: 'rng', azimuth_deg: 'az', radial_mps: 'vr', snr_db: 'snr', intensity: 'int', class_hint: '' };
  function fieldText(rec) {
    const mod = Sim.MODULES[rec.module], units = {};
    ((mod && mod.native && mod.native.fields) || []).forEach((q) => { units[q.name] = q.unit; });
    return Object.keys(rec.fields).filter((k) => k !== 'presence').map((k) => {
      const v = rec.fields[k];
      if (typeof v === 'string') return '[' + v + ']';
      const u = units[k] === 'deg' ? '°' : units[k] && units[k] !== 'a.u.' ? ' ' + units[k] : '';
      return SHORT[k] + ' ' + v.toFixed(Math.abs(v) < 10 ? 2 : 1) + u;
    }).join('  ');
  }
  function renderFeed(f) {
    const rows = [];
    for (let j = f.k; j >= Math.max(0, f.k - 20) && rows.length < 10; j--) {
      const fr = S.res.frames[j];
      for (let q = fr.meas.length - 1; q >= 0 && rows.length < 10; q--) rows.push(fr.meas[q]);
    }
    $('feed').innerHTML = rows.length ? rows.map((m) =>
      '<div style="display:flex;gap:8px"><span style="color:#8B96A5;flex:none">' + fmtT(m.t).slice(0, 7) + '</span><span style="flex:none;width:76px;color:' + KCOL[m.k] + '">' + m.node + ' ' + m.k + '</span><span style="color:#D5DBE3">' + fieldText(m) + (m.merged ? ' (2 merged)' : '') + (m.clutter ? ' (clutter)' : '') + '</span></div>').join('')
      : '<div style="color:#8B96A5">Nothing detected in the last 2 s.</div>';
  }
  // a sensor's range in the weather at its own position now: weather events and the sky move it during the run
  function rangeNow(s, f) {
    const n = nodeState(f, s.node), m = Sim.MODULES[s.module];
    if (!n) return s.range;
    return m.sim.range_m * Weather.sensorQuality(m, Weather.activeEffects(S.wx.at([n.x, n.y], f.t))).range;
  }
  function buildLimits(f) {
    const html = S.res.sensors.map((s) => {
      const range = rangeNow(s, f), nominal = Sim.MODULES[s.module].sim.range_m, weak = range < nominal * 0.999;
      return '<tr><td>' + s.node + '</td><td style="color:' + KCOL[s.kind] + '">' + s.kind + '</td><td' + (weak ? ' style="color:#F5B13D"' : '') + '>' + Math.round(s.minRange) + '–' + Math.round(range) + (weak ? ' ▼' : '') + '</td><td>' + (s.fovDeg >= 360 ? '360°' : s.fovDeg + '°') + '</td><td>' + (s.pointing === 'omni' ? 'all' : 'ahead') + '</td><td>' + s.rateHz + '</td><td style="white-space:normal">' + s.fields.map((n) => SHORT[n] === undefined ? n : (SHORT[n] || 'class')).join(' ') + '</td></tr>';
    }).join('');
    if (html !== S.limitsHtml) $('limits').innerHTML = S.limitsHtml = html; // rows change only when the weather does
  }
  const HEALTH_COL = { ok: '#C9D1DB', degraded: '#F5B13D', offline: '#FF5A5F', presumed_dead: '#FF5A5F' };
  // store-and-forward runs only: each node's link as C2 sees it, and what the node itself still holds
  function buildHealth(f) {
    $('healthSec').style.display = f.health ? '' : 'none';
    if (!f.health) return;
    $('health').innerHTML = Object.keys(f.health).map((n) => {
      const h = f.health[n];
      return '<tr><td>' + n + '</td><td style="color:' + HEALTH_COL[h.state] + '">' + h.state.replace('_', ' ') + '</td><td>' + Math.round(h.loss * 100) + '%</td><td>' + h.silent_s.toFixed(1) + '</td><td' + (h.offline ? ' style="color:#FF5A5F">yes' : '>no') + '</td><td>' + h.buffered_s.toFixed(1) + '</td></tr>';
    }).join('');
  }
  function renderDetail(f) {
    const box = $('detail');
    const t = f.tracks.find((q) => q.id === S.sel);
    if (!t) { box.innerHTML = '<div class="empty">No track selected.</div>'; return; }
    const e = eig(t.pxx, t.pyy, t.pxy);
    const rho = t.pxy / Math.sqrt(t.pxx * t.pyy);
    const label = CLASS_NAME[t.cls] + ' · ' + (t.cls === 'friendly' ? ((Sim.PLATFORMS[S.applied.assign[t.id]] || {}).name || 'verified identity') : t.st);
    const b = t.cls === 'hostile' ? 'background:#FF5A5F;color:#14080A' : t.cls === 'friendly' ? 'background:#5B9BFF;color:#06101F' : 'border:1px dashed ' + classColor(t.cls) + ';color:' + classColor(t.cls);
    // position error sparkline over last 30 s
    const pts = [];
    for (let j = 0; j <= 30; j++) {
      const pf = S.res.frames[f.k - j * 10 >= 0 ? f.k - j * 10 : -1];
      if (!pf) break;
      const pt = pf.tracks.find((q) => q.id === t.id);
      if (pt && pt.err !== undefined) pts.unshift([(30 - j) * 11.33, pt.err]);
    }
    const now = t.err !== undefined ? t.err : null;
    const path = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + (46 - Math.min(20, p[1]) * 2).toFixed(1)).join('');
    const sources = t.nodes.length ? t.nodes.map((n) => '<span class="tag">' + n + '</span>').join('') : '<span style="color:#8B96A5">none in last 2 s</span>';
    const cfg = S.res.estimatorConfig;
    const rules = [
      ['friendly', 'Identity ≥ ' + percent(cfg.friendly_enter), 'retain ≥ ' + percent(cfg.friendly_exit)],
      ['hostile', 'Risk ≥ ' + percent(cfg.hostile_enter), 'retain ≥ ' + percent(cfg.hostile_exit)],
      ['peaceful', 'Risk ≤ ' + percent(cfg.peaceful_enter), 'retain ≤ ' + percent(cfg.peaceful_exit)],
      ['suspicious', 'Identity ≤ ' + percent(cfg.suspicious_enter) + ' and risk ≥ ' + percent(cfg.suspicious_threat_enter),
        'retain identity ≤ ' + percent(cfg.suspicious_exit) + ', risk ≥ ' + percent(cfg.suspicious_threat_exit)],
      ['unknown', 'No decisive label / insufficient history', 'Needs fresh, usable observations'],
    ];
    box.innerHTML =
      '<div class="row" style="align-items:center"><span class="mono" style="padding:1px 6px;font-size:12px;font-weight:600;border-radius:2px;' + b + '">' + t.id + '</span><span style="font-size:13px;font-weight:600">' + label + '</span><span class="grow"></span><button class="ibtn" id="centre" aria-label="Centre map on ' + t.id + '"><svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="5" fill="none" stroke="currentColor" stroke-width="1.4"/><circle cx="8" cy="8" r="1.5" fill="currentColor"/></svg></button></div>' +
      '<div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px">' +
      [['σ east', Math.sqrt(t.pxx).toFixed(1) + ' m'], ['σ north', Math.sqrt(t.pyy).toFixed(1) + ' m'], ['ρ', rho.toFixed(2)], ['95% ellipse', (e.a * 2.45).toFixed(0) + '×' + (e.b * 2.45).toFixed(0) + ' m']]
        .map((c) => '<div style="display:flex;flex-direction:column;gap:2px"><span style="font-size:11px;color:#8B96A5">' + c[0] + '</span><span class="mono" style="font-size:13px">' + c[1] + '</span></div>').join('') + '</div>' +
      '<div style="display:flex;flex-direction:column;gap:6px"><span style="font-size:11px;color:#8B96A5">Contributing sensors (last 2 s)</span><div class="mono" style="display:flex;flex-wrap:wrap;gap:6px;font-size:11px">' + sources + '</div></div>' +
      '<div style="display:flex;flex-direction:column;gap:6px"><span style="font-size:11px;color:#8B96A5">Automatic assessment · independent scores</span>' +
      [['Verified identity', t.pF, '#5B9BFF'], ['Behavior risk', t.pH, '#FF5A5F'], ['Peaceful evidence', 1-t.pH, '#5FD0C0'], ['Observation quality', t.behavior.quality || 0, '#A9B3BF']].map(([name, value, color]) =>
        '<div style="display:flex;justify-content:space-between;font-size:11px"><span>' + name + '</span><span class="mono">' + (value * 100).toFixed(1) + '%</span></div>' +
        '<div role="meter" aria-label="' + name + '" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + (value * 100).toFixed(1) + '" style="height:7px;background:#1B222C"><div style="height:100%;width:' + value * 100 + '%;background:' + color + '"></div></div>').join('') +
      '<span style="font-size:11px;color:#C9D1DB">Observed pattern: ' + (PATTERN_NAME[t.behavior.pattern] || 'Collecting history') +
      ' · ' + (t.behavior.observed_s || 0).toFixed(1) + ' s usable history</span>' +
      (t.behavior.features?.reference_track_id ? '<span style="font-size:11px;color:#C9D1DB">Compared with ' + t.behavior.features.reference_track_id + ' · ' + t.behavior.features.response_count + ' matched responses · ' + t.behavior.features.response_lag_s + ' s response lag · ' + t.behavior.features.closing_m.toFixed(1) + ' m closed</span>' : '') +
      '<span style="font-size:11px;color:#8B96A5">' + ((t.behavior.reasons || ['insufficient_history']).map((v) => REASON_NAME[v] || v.replace(/_/g, ' ')).join(' · ')) + '</span>' +
      (t.behavior.retained_risk ? '<span style="font-size:11px;color:#C9D1DB">Earlier encounter · ' + t.behavior.retained_risk.age_s.toFixed(1) + ' s ago · ' + t.behavior.retained_risk.reasons.map((v) => REASON_NAME[v] || v.replace(/_/g, ' ')).join(' · ') + ' · score decaying</span>' : '') +
      '<div aria-label="Assessment thresholds" style="display:flex;flex-direction:column;gap:5px;font-size:11px">' + rules.map(([cls, enter, retain]) => '<div data-rule="' + cls + '" style="padding:5px;border-left:2px solid ' + classColor(cls) + ';background:' + (t.cls === cls ? '#1B2833' : '#10161D') + '"><b style="color:' + classColor(cls) + '">' + CLASS_NAME[cls] + '</b> · ' + enter + '<br><span style="color:#8B96A5">' + retain + '</span></div>').join('') + '</div>' +
      '<span style="font-size:10px;color:#8B96A5">Independent simulation scores, not five probabilities that sum to 100%. 50% risk means no directional evidence. Verified identity takes priority; peaceful movement does not verify identity.</span></div>' +
      '<div style="display:flex;flex-direction:column;gap:4px"><div style="display:flex;justify-content:space-between;font-size:11px;color:#8B96A5"><span>Position error vs truth, last 30 s</span><span class="mono" style="color:#C9D1DB">' + (now === null ? 'no truth match' : 'now ' + now.toFixed(1) + ' m') + '</span></div>' +
      '<svg viewBox="0 0 340 56" width="100%" role="img" aria-label="Position error sparkline"><path d="M0 46H340M0 6H340" stroke="#222A35"/>' + (path ? '<path d="' + path + '" fill="none" stroke="#3FC1D9" stroke-width="1.6"/>' : '') + '<text x="0" y="55" class="mono" style="font-size:9px;fill:#8B96A5">0 m</text><text x="0" y="14" class="mono" style="font-size:9px;fill:#8B96A5">20 m</text></svg></div>';
    $('centre').addEventListener('click', () => centreOn(t));
  }

  // ------------------------------------------------------------------ footer
  function buildTimeline() {
    const r = S.res, W = 1000;
    const x = (t) => (t / r.T_END) * W;
    const marks = r.timeline.filter((m, i, a) => a.findIndex((q) => q.label === m.label && Math.abs(q.t - m.t) < 1) === i);
    S.marks = marks;
    const col = { red: '#FF5A5F', amber: '#F5B13D' };
    const labels = [];
    marks.slice().sort((a, b) => a.t - b.t).forEach((m) => {
      if (!/^H\d seen$/.test(m.label) && labels.every((q) => Math.abs(q.t - m.t) >= 15)) labels.push(m);
    });
    $('tlSvg').innerHTML = '<rect x="0" y="22" width="1000" height="6" rx="3" fill="#1B222C"/><rect id="tlFill" x="0" y="22" width="0" height="6" rx="3" fill="#1D6A79"/>' +
      marks.map((m) => '<path d="M' + x(m.t) + ' 14V28" stroke="' + col[m.color] + '" stroke-width="2"' + (m.dashed ? ' stroke-dasharray="2 2"' : '') + '><title>' + m.label + '</title></path>').join('') +
      '<path id="tlHead" d="M0 6V36" stroke="#E6EAF0" stroke-width="2"/>';
    $('tlLabels').innerHTML = labels.map((m) => '<span style="position:absolute;left:' + (m.t / r.T_END * 100) + '%;transform:translateX(-50%);color:' + (m.color === 'amber' ? '#F5B13D' : '#8B96A5') + '">' + m.label + '</span>').join('');
  }
  function renderFooter(f) {
    const r = S.res;
    $('tNow').textContent = fmtT(f.t);
    $('scrub').value = S.idx;
    $('tlFill').setAttribute('width', (f.t / r.T_END) * 1000);
    $('tlHead').setAttribute('d', 'M' + (f.t / r.T_END) * 1000 + ' 6V36');
    $('play').innerHTML = S.playing
      ? '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 3h3v10H4zM9 3h3v10H9z" fill="currentColor"/></svg>'
      : '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2l10 6-10 6z" fill="currentColor"/></svg>';
    $('play').setAttribute('aria-label', S.playing ? 'Pause' : 'Play');
    const set = (id, v, bad) => { const m = $(id); m.querySelector('b').textContent = v; m.classList.toggle('bad', !!bad); };
    set('mCount', (f.m.countErr > 0 ? '+' : '') + f.m.countErr, f.m.countErr !== 0);
    set('mRmse', f.m.rmse10 === null ? '-' : f.m.rmse10.toFixed(1) + ' m', false);
    set('mSwap', f.m.swaps, f.m.swaps > 0);
    set('mFfa', f.m.ffa, f.m.ffa > 0);
    renderChart(f);
  }
  function renderChart(f) {
    const svg = $('chart');
    const X0 = 40, X1 = 790;
    if (S.tab === 'time') {
      $('chartLegend').innerHTML = '<span style="color:#3FC1D9">━</span> RMSE (m) &nbsp; <span style="color:#F5B13D">┅</span> |count error| ×5';
      $('chartNote').textContent = 'Position RMSE (10 s window) and absolute hostile-count error up to the playhead.';
      const xs = (t) => X0 + (t / S.res.T_END) * (X1 - X0);
      let rm = '', ce = '';
      for (let k = 0; k <= S.idx; k += 3) {
        const fr = S.res.frames[k];
        if (fr.m.rmse10 !== null) rm += (rm ? 'L' : 'M') + xs(fr.t).toFixed(1) + ' ' + (100 - Math.min(20, fr.m.rmse10) * 4).toFixed(1);
        ce += (ce ? 'L' : 'M') + xs(fr.t).toFixed(1) + ' ' + (100 - Math.min(20, Math.abs(fr.m.countErr) * 5) * 4).toFixed(1);
      }
      svg.innerHTML = '<path d="M40 20H800M40 60H800M40 100H800" stroke="#1B222C"/>' +
        [['20', 24], ['10', 64], ['0', 104]].map((l) => '<text x="32" y="' + l[1] + '" text-anchor="end" class="mono" style="font-size:10px;fill:#8B96A5">' + l[0] + '</text>').join('') +
        (rm ? '<path d="' + rm + '" fill="none" stroke="#3FC1D9" stroke-width="1.8"/>' : '') + (ce ? '<path d="' + ce + '" fill="none" stroke="#F5B13D" stroke-width="1.8" stroke-dasharray="4 3"/>' : '') +
        '<path d="M' + xs(f.t) + ' 10V106" stroke="#E6EAF0" stroke-dasharray="2 2"/>' +
        '<text x="40" y="124" class="mono" style="font-size:10px;fill:#8B96A5">0 s</text><text x="415" y="124" text-anchor="middle" class="mono" style="font-size:10px;fill:#8B96A5">60 s</text><text x="790" y="124" text-anchor="end" class="mono" style="font-size:10px;fill:#8B96A5">120 s</text>';
    } else {
      const d = degradation();
      const xs = (l) => X0 + 20 + (l / 90) * (X1 - X0 - 40);
      const ys = (v) => 100 - Math.min(20, v) * 4;
      const line = (key, dash) => 'M' + d.filter((p) => p[key] !== null).map((p) => xs(p.loss).toFixed(1) + ' ' + ys(key === 'count' ? p[key] * 5 : p[key]).toFixed(1)).join('L');
      $('chartLegend').innerHTML = '<span style="color:#3FC1D9">━</span> RMSE (m) &nbsp; <span style="color:#F5B13D">┅</span> mean |count err| ×5 &nbsp; <span style="color:#FF5A5F">╌</span> ID swaps + friendly FAs';
      $('chartNote').textContent = 'Realistic mode, same seed and weather, message loss 0-90 %, scored over t = ' + S.res.EVAL[0] + '-' + S.res.EVAL[1] + ' s (around the crossing); swaps/FAs over the whole run.';
      svg.innerHTML = '<path d="M40 20H800M40 60H800M40 100H800" stroke="#1B222C"/>' +
        [['20', 24], ['10', 64], ['0', 104]].map((l) => '<text x="32" y="' + l[1] + '" text-anchor="end" class="mono" style="font-size:10px;fill:#8B96A5">' + l[0] + '</text>').join('') +
        '<path d="' + line('rmse') + '" fill="none" stroke="#3FC1D9" stroke-width="1.8"/><path d="' + line('count') + '" fill="none" stroke="#F5B13D" stroke-width="1.8" stroke-dasharray="4 3"/>' +
        '<path d="M' + d.map((p) => xs(p.loss).toFixed(1) + ' ' + ys((p.swaps + p.ffa) * 2).toFixed(1)).join('L') + '" fill="none" stroke="#FF5A5F" stroke-width="1.6" stroke-dasharray="1.5 3"/>' +
        d.map((p) => '<text x="' + xs(p.loss) + '" y="124" text-anchor="middle" class="mono" style="font-size:10px;fill:#8B96A5">' + p.loss + '%</text>').join('');
    }
    $('tabTime').setAttribute('aria-selected', S.tab === 'time');
    $('tabDeg').setAttribute('aria-selected', S.tab === 'deg');
  }

  // ------------------------------------------------------------------ render
  function render() {
    const f = frame();
    $('clock').textContent = 'T+' + fmtT(f.t);
    $('frameInfo').textContent = 'frame ' + f.k + ' · fused @ 10 Hz';
    const cb = $('crossBanner');
    if (f.cross) {
      cb.style.display = 'inline-flex';
      cb.innerHTML = '▲ Crossing in ' + f.cross.tca.toFixed(1) + ' s: identity risk <span class="mono" style="font-weight:500;color:#F5D9A0">' + f.cross.a + ' × ' + f.cross.b + ' · sep ' + f.cross.sep.toFixed(0) + ' m</span>';
    } else cb.style.display = 'none';
    renderRight(f); // first: it settles the selected track the map highlights
    renderMap(f);
    renderFooter(f);
    buildLimits(f);
    buildHealth(f);
    applyView();
  }

  // ----------------------------------------------------------------- view
  function applyView() {
    const v = S.view;
    $('map').setAttribute('viewBox', v.x + ' ' + v.y + ' ' + v.w + ' ' + v.h);
  }
  const clampV = (x, size) => Math.min(1300 - size, Math.max(-300, x)); // the view may move a little past the area edge
  function zoom(k, cx, cy) {
    const v = S.view;
    const w = Math.min(1000, Math.max(120, v.w * k)), h = w;
    cx = cx === undefined ? v.x + v.w / 2 : cx; cy = cy === undefined ? v.y + v.h / 2 : cy;
    v.x = clampV(cx - ((cx - v.x) / v.w) * w, w); v.y = clampV(cy - ((cy - v.y) / v.h) * h, h);
    v.w = w; v.h = h;
    applyView();
  }
  function centreOn(t) {
    const v = S.view;
    v.x = clampV(t.x - v.w / 2, v.w); v.y = clampV(Y(t.y) - v.h / 2, v.h);
    applyView();
  }
  function wireMap() {
    const svg = $('map');
    const pt = (e) => { const p = svg.createSVGPoint(); p.x = e.clientX; p.y = e.clientY; return p.matrixTransform(svg.getScreenCTM().inverse()); };
    svg.addEventListener('wheel', (e) => { e.preventDefault(); const p = pt(e); zoom(e.deltaY > 0 ? 1.15 : 1 / 1.15, p.x, p.y); }, { passive: false });
    let drag = null;
    svg.addEventListener('pointerdown', (e) => { drag = { p: pt(e), x: S.view.x, y: S.view.y }; svg.setPointerCapture(e.pointerId); svg.style.cursor = 'grabbing'; });
    svg.addEventListener('pointerup', () => { drag = null; svg.style.cursor = 'grab'; });
    svg.addEventListener('pointermove', (e) => {
      const p = pt(e);
      $('coord').textContent = 'E' + pad4(p.x) + ' N' + pad4(Y(p.y)) + ' · elev ' + Math.round(elev(p.x, Y(p.y))) + ' m';
      if (drag) {
        const q = { x: drag.p.x - p.x, y: drag.p.y - p.y };
        S.view.x = clampV(S.view.x + q.x, S.view.w); S.view.y = clampV(S.view.y + q.y, S.view.h);
        applyView();
      }
    });
    $('zin').addEventListener('click', () => zoom(1 / 1.3));
    $('zout').addEventListener('click', () => zoom(1.3));
    $('zfit').addEventListener('click', () => { S.view = { x: 0, y: 0, w: 1000, h: 1000 }; applyView(); });
  }

  // ---------------------------------------------------------------- playback
  function setIdx(i) { S.idx = Math.max(0, Math.min(S.res.NF, i)); render(); }
  function wirePlayback() {
    $('play').addEventListener('click', () => { if (S.idx >= S.res.NF) S.idx = 0; S.playing = !S.playing; S.last = 0; render(); });
    $('back').addEventListener('click', () => { S.playing = false; setIdx(S.idx - 1); });
    $('fwd').addEventListener('click', () => { S.playing = false; setIdx(S.idx + 1); });
    $('scrub').addEventListener('input', (e) => { S.playing = false; setIdx(+e.target.value); });
    $('tabTime').addEventListener('click', () => { S.tab = 'time'; renderChart(frame()); });
    $('tabDeg').addEventListener('click', () => { S.tab = 'deg'; renderChart(frame()); });
    $('trkBody').addEventListener('click', (e) => { const tr = e.target.closest('tr'); if (tr) { S.sel = tr.dataset.id; S.userSel = true; render(); } });
    document.addEventListener('keydown', (e) => {
      if (/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName) || e.target.closest('button')) return;
      if (e.key === ' ') { e.preventDefault(); $('play').click(); }
      else if (e.key === 'ArrowLeft') { S.playing = false; setIdx(S.idx - (e.shiftKey ? 10 : 1)); }
      else if (e.key === 'ArrowRight') { S.playing = false; setIdx(S.idx + (e.shiftKey ? 10 : 1)); }
    });
    function tick(ts) {
      // A queued animation-frame timestamp can predate synchronous simulation
      // computation. Start timing after that work so reset does not skip ahead.
      ts = performance.now();
      if (S.playing && S.res) {
        if (S.last) {
          S.acc += ((ts - S.last) / 1000) * S.speed * 10;
          const steps = Math.floor(S.acc);
          if (steps > 0) {
            S.acc -= steps;
            S.idx = Math.min(S.res.NF, S.idx + steps);
            if (S.idx >= S.res.NF) S.playing = false;
            render();
          }
        }
        S.last = ts;
      } else S.last = 0;
      requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }

  // -------------------------------------------------------------------- init
  buildLeft();
  fillInputs();
  syncStaged();
  wireMap();
  wirePlayback();
  const q = new URLSearchParams(location.search); // ?weather=night&seed=7&t=49.5&tab=deg
  setWeatherFromUrl(q.get('weather'));
  if (q.get('seed')) S.staged.seed = parseInt(q.get('seed'), 10) || S.staged.seed;
  fillInputs(); syncStaged(); renderLoadout();
  $('presetNote').textContent = S.scenario.description;
  runSim(S.staged); // ?t=45 opens paused at 45 s; ?tab=deg opens the degradation chart
  if (q.has('t')) { S.playing = false; setIdx(Math.round(parseFloat(q.get('t')) * 10) || 0); }
  if (q.get('tab') === 'deg') { S.tab = 'deg'; renderChart(frame()); }
  window.__dds = S; // handy for debugging in the console
})();
