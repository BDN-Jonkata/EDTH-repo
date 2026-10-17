/*
 * The map legend: what each symbol on the map means, drawn with the viewer's own drawing code (so it can never
 * disagree with the map) and filled from the scenario and the run result (docs/data-formats.md): the track classes
 * and states on screen now, the sensor kinds the nodes carry with their range in the current weather, the links, the
 * jamming zones, clutter and crossing the scenario has. "All symbols" shows every symbol, present or not.
 * app.js passes what it draws with in `init`, and calls `render(frame)` after each frame.
 */
(function (global) {
  const $ = (id) => document.getElementById(id);
  const STORE_KEY = 'dds.legend';
  const CLASS_TEXT = {
    friendly: 'Our drones; a trusted beacon verifies the identity.',
    peaceful: 'Observed safe behaviour. Still tracked and counted.',
    unknown: 'Detected, no behaviour evidence yet.',
    suspicious: 'Behaviour of concern; may send a drone to look. Not a confirmed threat.',
    hostile: 'Established threat; counted in the hostile count.',
  };
  const STATE_TEXT = {
    tentative: ['Tentative', 'Dashed uncertainty ellipse and dashed ID tag: not confirmed yet.'],
    confirmed: ['Confirmed', 'Solid outline and filled ID tag.'],
    coasting: ['Coasting', 'Faded: no recent reading, the position is predicted.'],
  };
  const KIND_NAME = { EO: 'EO camera', IR: 'Thermal camera', MIC: 'Microphone', RAD: 'Radar', RF: 'RF receiver' };
  let ctx = null;
  let showAll = false;
  let lastHtml = '';

  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const icon = (inner) => '<svg class="lg-ico" width="36" height="36" viewBox="-16 -16 32 32" aria-hidden="true">' + inner + '</svg>';
  const row = (ico, name, text, extra) => '<div class="lg-row">' + ico + '<div><div class="lg-nm">' + name + '</div>' + (text ? '<div class="lg-tx">' + text + '</div>' : '') + (extra || '') + '</div></div>';
  const section = (title, rows) => (rows.length ? '<div class="lg-sec"><p class="h">' + title + '</p>' + rows.join('') + '</div>' : '');
  const count = (n) => '<span class="lg-n mono">' + n + ' now</span>';

  function classRows(f) {
    return Object.keys(ctx.className).map((cls) => {
      const n = f.tracks.filter((t) => t.cls === cls).length;
      if (!n && !showAll) return null;
      return row(icon(ctx.glyph(cls)), ctx.className[cls], CLASS_TEXT[cls], count(n));
    }).filter(Boolean);
  }

  // a state is drawn on the hostile symbol, as the map does
  function stateIcon(state) {
    const g = ctx.glyph('hostile'), col = ctx.classColor('hostile');
    if (state === 'tentative') return icon('<ellipse rx="14" ry="9" fill="none" stroke="' + col + '" stroke-width="1" stroke-dasharray="2.5 2"/>' + g);
    if (state === 'coasting') return icon('<g opacity="0.55">' + g + '</g>');
    return icon('<ellipse rx="12" ry="7" fill="' + col + '" fill-opacity="0.1" stroke="' + col + '" stroke-width="1"/>' + g);
  }
  function stateRows(f) {
    return Object.keys(STATE_TEXT).map((st) => {
      const n = f.tracks.filter((t) => t.st === st).length;
      return n || showAll ? row(stateIcon(st), STATE_TEXT[st][0], STATE_TEXT[st][1], count(n)) : null;
    }).filter(Boolean);
  }

  const dashLine = (kind) => icon('<path d="M-14 0H14" stroke="' + ctx.kcol[kind] + '" stroke-width="2.4" stroke-dasharray="' + ctx.kdash[kind] + '"/>');
  // one row per sensor kind: its map style, the nodes that carry it and the range now (reduced by weather: ▼)
  function sensorRows(f) {
    return Object.keys(KIND_NAME).map((kind) => {
      const list = ctx.state.res.sensors.filter((s) => s.kind === kind);
      if (!list.length && !showAll) return null;
      const now = list.map((s) => Math.round(ctx.rangeNow(s, f))), nominal = list.map((s) => ctx.nominalRange(s));
      const weak = list.some((s, i) => now[i] < nominal[i] * 0.999);
      const fields = list.length ? ' · reports ' + esc(list[0].fields.map(ctx.shortField).filter(Boolean).join(' ')) : '';
      const text = list.length ? esc(list.map((s) => s.node).filter((n, i, a) => a.indexOf(n) === i).join(', ')) + ' · ' + Math.min.apply(null, now) + '–' + Math.max.apply(null, now) + ' m' + (weak ? ' ▼ weather' : '') + fields : 'Not in this scenario.';
      return row(dashLine(kind), KIND_NAME[kind], text);
    }).filter(Boolean);
  }

  function nodeRows() {
    return [
      row(icon(ctx.glyph('friendly')), 'Friendly drone', 'Patrols and can be sent to look; carries sensors.'),
      row(icon(ctx.marks.ground), 'Ground sensor', 'Fixed node with its own sensors.'),
      row(icon(ctx.marks.c2), 'C2', 'Command and control: where messages arrive and the picture is fused.'),
    ];
  }

  const linkIcon = (q) => {
    const st = ctx.linkStyle(q);
    return icon('<path d="M-14 0H14" stroke="' + st.col + '" stroke-width="2" stroke-dasharray="' + st.dash + '"/>');
  };
  function linkRows() {
    if (!ctx.state.layers.net) return [];
    return [[1, 'Link up', 'Solid. Under 10 % of messages lost.'], [0.7, 'Degraded', 'Dashed amber, with the % lost.'], [0.2, 'Poor', 'Dotted red, with the % lost.']].map((r) => row(linkIcon(r[0]), r[1], r[2]));
  }

  // symbols only the scenario's own JSON asks for
  function scenarioRows(f) {
    const sc = ctx.state.scenario, net = (sc.degradations && sc.degradations.network) || {}, rows = [];
    const zones = (net.jamming_zones || []).length, clutter = (sc.clutter || []).length;
    if (zones || showAll) rows.push(row(icon('<circle r="12" fill="#FF5A5F" fill-opacity="0.07" stroke="#FF5A5F" stroke-width="1.4" stroke-dasharray="3 4"/>'), 'Jamming zone', zones + ' in this scenario; messages from nodes inside are lost more often.'));
    if (clutter || showAll) rows.push(row(icon('<circle r="5" fill="none" stroke="#8B96A5" stroke-width="1.4" stroke-dasharray="2 2"/>'), 'Clutter', clutter + ' bird or vehicle objects: not threats; a hostile track on one is a false alarm.'));
    if (f.cross || showAll) rows.push(row(icon('<circle r="12" fill="#F5B13D" fill-opacity="0.07" stroke="#F5B13D" stroke-width="1.6" stroke-dasharray="6 4"/>'), 'Predicted crossing', 'Where two hostile predictions meet: identity risk.'));
    return rows;
  }

  function layerChips() {
    const chips = ctx.layers.map((l) => '<span class="lg-chip' + (ctx.state.layers[l[0]] ? ' on' : '') + '"><svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">' + l[3] + '</svg>' + esc(l[1]) + '</span>').join('');
    return '<div class="lg-sec"><p class="h">Layers (switch them on the left)</p><div class="lg-chips">' + chips + '</div></div>';
  }

  function html(f) {
    return section('Track class', classRows(f)) + section('Track state', stateRows(f)) + section('Sensors', sensorRows(f)) +
      section('Nodes', nodeRows()) + section('Links', linkRows()) + section('This scenario', scenarioRows(f)) + layerChips();
  }

  function render(f) {
    if ($('legend').hidden) return;
    const out = html(f);
    if (out !== lastHtml) $('legendBody').innerHTML = lastHtml = out;
  }
  function setOpen(open) {
    $('legend').hidden = !open;
    $('legendBtn').setAttribute('aria-expanded', String(open));
    try { localStorage.setItem(STORE_KEY, JSON.stringify({ open, showAll })); } catch (e) { /* private window: not remembered */ }
    if (open) ctx.redraw();
  }
  function init(context) {
    ctx = context;
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(STORE_KEY)) || {}; } catch (e) { saved = {}; }
    const q = new URLSearchParams(location.search); // ?legend=1 opens it, ?legend=all shows every symbol
    if (q.has('legend')) saved = { open: true, showAll: q.get('legend') === 'all' };
    showAll = !!saved.showAll;
    $('legendAll').checked = showAll;
    $('legendBtn').addEventListener('click', () => setOpen($('legend').hidden));
    $('legendClose').addEventListener('click', () => { setOpen(false); $('legendBtn').focus(); });
    $('legend').addEventListener('keydown', (e) => { if (e.key === 'Escape') { setOpen(false); $('legendBtn').focus(); } });
    $('legendAll').addEventListener('change', (e) => { showAll = e.target.checked; setOpen(true); });
    setOpen(!!saved.open);
  }

  global.Legend = { init, render };
})(typeof window !== 'undefined' ? window : globalThis);
