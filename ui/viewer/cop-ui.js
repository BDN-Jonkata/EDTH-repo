/* The COP replay page: draws a saved run (cop.js reads it) on a map, with a table of tracks and playback.
 * Nothing here simulates or infers; it only shows what the run holds. Truth is an overlay for evaluation, off by default. */
(function () {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  const COLORS = { hostile: '#FF5D5D', suspicious: '#FFB454', unknown: '#9AA4B2', peaceful: '#7BD88F', friendly: '#4FC3F7', object: '#B39DDB' };
  const TRAIL_S = 8, VECTOR_S = 3, FRAME_S = 0.1;
  const S = { run: null, k: 0, playing: false, speed: 1, last: 0, carry: 0 };
  const $ = (id) => document.getElementById(id);
  const Y = (y) => 1000 - y;
  const colorOf = (cls) => COLORS[cls] || COLORS.unknown;

  function el(tag, attrs, text) {
    const e = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach((k) => e.setAttribute(k, attrs[k]));
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function html(tag, attrs, text) {
    const e = document.createElement(tag);
    Object.keys(attrs || {}).forEach((k) => e.setAttribute(k, attrs[k]));
    if (text !== undefined) e.textContent = text;
    return e;
  }

  // ---------------------------------------------------------------- the map
  function drawGrid(svg) {
    for (let v = 0; v <= 1000; v += 100) {
      svg.appendChild(el('line', { x1: v, y1: 0, x2: v, y2: 1000, stroke: '#1B2430', 'stroke-width': 1 }));
      svg.appendChild(el('line', { x1: 0, y1: v, x2: 1000, y2: v, stroke: '#1B2430', 'stroke-width': 1 }));
      if (v > 0 && v < 1000) {
        svg.appendChild(el('text', { x: v + 3, y: 996, fill: '#4B5868', 'font-size': 18 }, 'E' + v));
        svg.appendChild(el('text', { x: 4, y: Y(v) - 4, fill: '#4B5868', 'font-size': 18 }, 'N' + v));
      }
    }
  }
  function drawGround(svg, scenario) {
    (scenario.ground || []).forEach((g) => {
      const [x, y] = g.position;
      svg.appendChild(el('rect', { x: x - 7, y: Y(y) - 7, width: 14, height: 14, fill: 'none', stroke: '#6F7B89', 'stroke-width': 2 }));
      svg.appendChild(el('text', { x: x + 11, y: Y(y) + 5, fill: '#6F7B89', 'font-size': 18 }, g.id));
    });
  }
  function drawTrail(svg, tr) {
    const pts = Cop.trail(S.run.frames, S.k, tr.id, TRAIL_S);
    if (pts.length < 2) return;
    svg.appendChild(el('polyline', { points: pts.map((p) => p[0].toFixed(1) + ',' + Y(p[1]).toFixed(1)).join(' '), fill: 'none',
      stroke: colorOf(tr.cls), 'stroke-opacity': 0.45, 'stroke-width': 3 }));
  }
  function drawTrack(svg, tr) {
    const c = colorOf(tr.cls), moving = Math.hypot(tr.vx, tr.vy) > 0.5;
    if (moving) svg.appendChild(el('line', { x1: tr.x, y1: Y(tr.y), x2: tr.x + tr.vx * VECTOR_S, y2: Y(tr.y + tr.vy * VECTOR_S), stroke: c, 'stroke-width': 3 }));
    svg.appendChild(el('circle', { cx: tr.x, cy: Y(tr.y), r: 9, fill: c, 'fill-opacity': tr.st === 'coasting' ? 0.35 : 0.9, stroke: '#0B0F14', 'stroke-width': 2 }));
    if ($('tNames').checked) svg.appendChild(el('text', { x: tr.x + 13, y: Y(tr.y) - 11, fill: c, 'font-size': 20, 'font-weight': 600 }, tr.id));
  }
  function drawTruth(svg, frame) {
    frame.truth.forEach((o) => {
      const c = o.kind === 'hostile' ? '#FF5D5D' : '#6F7B89', s = 11;
      svg.appendChild(el('path', { d: `M${o.x} ${Y(o.y) - s}L${o.x + s} ${Y(o.y)}L${o.x} ${Y(o.y) + s}L${o.x - s} ${Y(o.y)}Z`, fill: 'none', stroke: c, 'stroke-width': 2.5, 'stroke-dasharray': '4 3' }));
    });
  }
  function drawMap(frame) {
    const svg = $('map');
    svg.replaceChildren();
    drawGrid(svg);
    drawGround(svg, S.run.scenario);
    const tracks = Cop.shown(frame.tracks);
    if ($('tTrails').checked) tracks.forEach((tr) => drawTrail(svg, tr));
    if ($('tTruth').checked) drawTruth(svg, frame);
    tracks.forEach((tr) => drawTrack(svg, tr));
  }

  // ------------------------------------------------------------ the side panel
  function drawCounts(frame) {
    const c = Cop.counts(frame), box = $('counts');
    box.replaceChildren();
    const table = html('table');
    const row = (label, value, hint) => {
      const tr = html('tr'), th = html('td', {}, label), td = html('td', { class: 'n' }, String(value));
      if (hint) th.title = hint;
      tr.append(th, td);
      table.appendChild(tr);
    };
    row('Hostile tracks', c.hostile, 'tracks labelled hostile');
    row('Not friendly, not peaceful', c.presumed, 'every track that is not a confirmed friend or peaceful: the count the operator would act on');
    if ($('tTruth').checked) row('True hostiles (truth)', c.truthHostile, 'evaluation only: read from the run\'s truth');
    Cop.CLASSES.filter((k) => c.byClass[k]).forEach((k) => {
      const tr = html('tr'), td = html('td'), dot = html('span', { class: 'dot' });
      dot.style.background = colorOf(k);
      td.append(dot, k);
      tr.append(td, html('td', { class: 'n' }, String(c.byClass[k])));
      table.appendChild(tr);
    });
    box.appendChild(table);
  }
  function drawTrackTable(frame) {
    const box = $('tracks'), tracks = Cop.shown(frame.tracks).slice().sort((a, b) => a.cls.localeCompare(b.cls) || a.id.localeCompare(b.id));
    box.replaceChildren();
    if (!tracks.length) { box.textContent = 'No tracks.'; box.className = 'dim'; return; }
    box.className = '';
    const table = html('table'), head = html('tr');
    ['id', 'class', 'speed', 'heading'].forEach((h) => head.appendChild(html('th', {}, h)));
    table.appendChild(head);
    tracks.forEach((tr) => {
      const r = html('tr'), id = html('td'), dot = html('span', { class: 'dot' });
      dot.style.background = colorOf(tr.cls);
      id.append(dot, tr.id);
      r.append(id, html('td', {}, tr.cls), html('td', { class: 'n' }, Math.hypot(tr.vx, tr.vy).toFixed(1) + ' m/s'), html('td', { class: 'n' }, Math.round(Cop.heading(tr.vx, tr.vy)) + '°'));
      table.appendChild(r);
    });
    box.appendChild(table);
  }
  function drawSummary() {
    const rows = Cop.summaryRows(S.run.summary), box = $('summary');
    box.replaceChildren();
    box.className = rows.length ? '' : 'dim';
    if (!rows.length) { box.textContent = 'This run has no summary.'; return; }
    const table = html('table');
    rows.forEach(([label, value]) => { const r = html('tr'); r.append(html('td', {}, label), html('td', { class: 'n' }, value)); table.appendChild(r); });
    box.appendChild(table);
  }

  function render() {
    if (!S.run) return;
    const frame = S.run.frames[S.k];
    $('clock').textContent = frame.t.toFixed(1) + ' s of ' + S.run.duration.toFixed(0) + ' s';
    $('scrub').value = S.k;
    $('play').textContent = S.playing ? 'Pause' : 'Play';
    drawMap(frame);
    drawCounts(frame);
    drawTrackTable(frame);
  }

  // ------------------------------------------------------------------ playback
  function tick(now) {
    if (!S.playing) return;
    S.carry += ((now - S.last) / 1000) * S.speed / FRAME_S;
    S.last = now;
    const steps = Math.floor(S.carry);
    if (steps > 0) {
      S.carry -= steps;
      S.k = Math.min(S.run.frames.length - 1, S.k + steps);
      if (S.k === S.run.frames.length - 1) S.playing = false;
      render();
    }
    requestAnimationFrame(tick);
  }
  function play() {
    if (!S.run) return;
    S.playing = !S.playing;
    if (S.playing && S.k >= S.run.frames.length - 1) S.k = 0;
    S.last = performance.now();
    S.carry = 0;
    render();
    if (S.playing) requestAnimationFrame(tick);
  }
  function seek(k) {
    if (!S.run) return;
    S.k = Math.max(0, Math.min(S.run.frames.length - 1, k));
    render();
  }

  // ------------------------------------------------------------------- loading
  function message(text) { $('msg').textContent = text || ''; }
  function openRun(json) {
    try { S.run = Cop.load(json); } catch (e) { message(e.message); return; }
    message('');
    S.k = 0; S.playing = false;
    $('scrub').max = S.run.frames.length - 1;
    $('drop').hidden = true;
    const p = S.run.params, js = S.run.engine !== 'python-pipeline';
    const badge = $('engine');
    badge.hidden = false;
    badge.textContent = js ? 'JavaScript simulation' : 'Python pipeline';
    badge.className = 'badge' + (js ? ' js' : '');
    $('runInfo').textContent = [p.preset || S.run.scenario.id, p.seed !== undefined ? 'seed ' + p.seed : '', p.loss !== undefined ? 'loss ' + p.loss : '', p.weather].filter(Boolean).join(' · ');
    drawSummary();
    render();
  }
  function readFile(file) {
    const reader = new FileReader();
    reader.onload = () => { try { openRun(JSON.parse(reader.result)); } catch (e) { message('Could not read ' + file.name + ': ' + e.message); } };
    reader.onerror = () => message('Could not read ' + file.name + '.');
    reader.readAsText(file);
  }
  function fetchRun(url) {
    fetch(url).then((r) => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); }).then(openRun)
      .catch((e) => message('Could not load ' + url + ': ' + e.message));
  }

  function wire() {
    $('file').addEventListener('change', (e) => { if (e.target.files[0]) readFile(e.target.files[0]); });
    $('play').addEventListener('click', play);
    $('back').addEventListener('click', () => seek(S.k - 10));
    $('fwd').addEventListener('click', () => seek(S.k + 10));
    $('scrub').addEventListener('input', (e) => seek(Number(e.target.value)));
    $('speed').addEventListener('change', (e) => { S.speed = Number(e.target.value); });
    ['tTrails', 'tNames', 'tTruth'].forEach((id) => $(id).addEventListener('change', render));
    document.addEventListener('dragover', (e) => e.preventDefault());
    document.addEventListener('drop', (e) => { e.preventDefault(); if (e.dataTransfer.files[0]) readFile(e.dataTransfer.files[0]); });
    document.addEventListener('keydown', (e) => {
      if (e.target.tagName === 'INPUT' && e.target.type !== 'range' && e.target.type !== 'checkbox') return;
      if (e.key === ' ' && e.target.tagName !== 'BUTTON') { e.preventDefault(); play(); }
      if (e.key === 'ArrowRight') seek(S.k + (e.shiftKey ? 10 : 1));
      if (e.key === 'ArrowLeft') seek(S.k - (e.shiftKey ? 10 : 1));
    });
    const url = new URLSearchParams(location.search).get('run');
    if (url) fetchRun(url);
  }
  wire();
  (typeof window !== 'undefined' ? window : globalThis).CopUI = { openRun, seek, play, state: S }; // for test-cop-ui.js
})();
