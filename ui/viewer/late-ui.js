/*
 * Late data and cut-off nodes in the viewer (docs/data-formats.md, "Late readings"). Store-and-forward runs only.
 *
 * - Bursts: sensor readings that reached C2 long after they were taken (a delay burst, a resend after an outage), or
 *   never did. They are drawn on the timeline from when they were taken to when they arrived, and on the map where and
 *   when they were taken, so the gap in the picture can be played back.
 * - Revised view: with "Late data loaded" on, tracks carry the correction the late readings give (`LateData.shiftAt`);
 *   off, the picture is exactly what C2 had.
 * - Cut-off nodes: a ring on the map (isolated = silent 30 s or more while alive, holding data) and, on request,
 *   what the node itself saw while cut off, with what has not reached C2 yet.
 * app.js passes what it draws with in `init` and calls `render(frame)` and `mapSvg(frame)` after each frame.
 */
(function (global) {
  const $ = (id) => document.getElementById(id);
  const ISO = '#9B7BFF', LATE = '#F5B13D', DOWN = '#FF5A5F';
  const MIN_BURST = 5;   // fewer late readings together are loss and resends, not a burst
  const SHOW_S = 3;      // a reading stays on the map this long
  const MAX_DRAWN = 90;
  const BURST_GAP_S = 3; // readings taken further apart start a new burst
  let ctx = null, cache = null, shown = new Map();

  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const fmt = (t) => t.toFixed(1) + ' s';
  const storeForward = () => ctx.state.res.storeForward || null;

  // ------------------------------------------------------------------ bursts
  function groupBursts(readings) {
    const list = [], open = {};
    readings.forEach((r) => {
      let b = open[r.node];
      if (!b || r.t - b.to > BURST_GAP_S) { b = open[r.node] = { node: r.node, from: r.t, to: r.t, n: 0, undelivered: 0, arrFirst: Infinity, arrLast: -Infinity, list: [] }; list.push(b); }
      b.to = r.t; b.n++; b.list.push(r);
      if (r.arr === null) b.undelivered++;
      else { b.arrFirst = Math.min(b.arrFirst, r.arr); b.arrLast = Math.max(b.arrLast, r.arr); }
    });
    return list.filter((b) => b.n >= MIN_BURST).sort((a, b) => a.from - b.from);
  }
  // bursts of the current run, with the set of readings that belong to one
  function bursts() {
    const res = ctx.state.res;
    if (cache && cache.res === res) return cache;
    const sf = storeForward();
    const list = sf ? groupBursts(sf.readings) : [];
    const inBurst = new Set();
    list.forEach((b) => b.list.forEach((r) => inBurst.add(r)));
    cache = { res, list, inBurst };
    shown = new Map();
    return cache;
  }

  // ------------------------------------------------------------ revised frame
  // the frame as it is shown: with the late readings' corrections on the tracks, when "Late data loaded" is on
  function frameAt(f) {
    const sf = ctx && storeForward();
    if (!ctx || !ctx.state.revised || !sf || !sf.revisions.length) return f;
    const key = f.k;
    if (!shown.has(key)) {
      const tracks = f.tracks.map((tr) => {
        const s = LateData.shiftAt(sf.revisions, tr.id, f.t);
        return s.dx || s.dy ? Object.assign({}, tr, { x: tr.x + s.dx, y: tr.y + s.dy, revised: true }) : tr;
      });
      shown.set(key, Object.assign({}, f, { tracks }));
    }
    return shown.get(key);
  }

  // --------------------------------------------------------------------- map
  function readingSvg(r, style) {
    const col = style.local ? ISO : ctx.kcol[r.k], Y = ctx.Y;
    const dash = style.held ? '5 3' : '', op = style.faded ? 0.35 : 0.85;
    const title = '<title>' + esc(r.node + ' ' + r.k + ' taken ' + fmt(r.t) + (r.arr === null ? ', not at C2' : ', reached C2 ' + fmt(r.arr))) + '</title>';
    if (r.m === 'bearing') {
      const L = Math.min(r.rmax, 450);
      return '<path d="M' + r.sx + ' ' + Y(r.sy) + 'L' + (r.sx + L * Math.cos(r.b)).toFixed(1) + ' ' + Y(r.sy + L * Math.sin(r.b)).toFixed(1) + '" stroke="' + col + '" stroke-width="1.3" stroke-opacity="' + op + '" stroke-dasharray="' + (dash || '1 0') + '" fill="none">' + title + '</path>';
    }
    if (r.m === 'range') {
      return '<circle cx="' + r.sx + '" cy="' + Y(r.sy) + '" r="' + r.r + '" fill="none" stroke="' + col + '" stroke-opacity="' + op + '" stroke-width="1.3" stroke-dasharray="' + (dash || '2 3') + '">' + title + '</circle>';
    }
    const x = r.sx + r.r * Math.cos(r.b), y = Y(r.sy + r.r * Math.sin(r.b));
    return '<path d="M' + r.sx + ' ' + Y(r.sy) + 'L' + x.toFixed(1) + ' ' + y.toFixed(1) + '" stroke="' + col + '" stroke-opacity="0.3" stroke-width="1"/>' +
      '<path d="M' + x.toFixed(1) + ' ' + (y - 6).toFixed(1) + 'l6 6l-6 6l-6 -6z" fill="' + (style.held ? 'none' : col) + '" fill-opacity="0.35" stroke="' + col + '" stroke-opacity="' + op + '" stroke-width="1.5">' + title + '</path>';
  }
  // which late readings are on the map now: when they were taken (revised), or just after they reached C2 (as C2 had it)
  function visible(f) {
    const b = bursts(), revised = ctx.state.revised;
    const out = [];
    b.list.forEach((burst) => burst.list.forEach((r) => {
      if (revised ? r.t <= f.t && f.t <= r.t + SHOW_S : r.arr !== null && r.arr <= f.t && f.t <= r.arr + SHOW_S) out.push(r);
    }));
    return out.slice(-MAX_DRAWN);
  }
  // what a cut-off node holds that C2 does not have yet, at this moment
  function undelivered(f, node) {
    const sf = storeForward();
    const list = sf ? sf.readings.filter((r) => r.node === node && r.t <= f.t && (r.arr === null || r.arr > f.t)) : [];
    return list.slice(-MAX_DRAWN * 2);
  }
  function nodeRings(f) {
    if (!f.health) return '';
    return Object.keys(f.health).map((n) => {
      const h = f.health[n], at = ctx.nodeXY(f, n);
      if (!at || !(h.state === 'isolated' || h.state === 'offline' || h.state === 'presumed_dead')) return '';
      const iso = h.state === 'isolated', col = iso ? ISO : DOWN;
      const text = n + ' ' + (iso ? 'ISOLATED ' + Math.round(h.silent_s) + ' s' : h.state === 'offline' ? 'OFFLINE' : 'SILENT') + (h.buffered_s > 0 && iso ? ' · holds ' + Math.round(h.buffered_s) + ' s' : '');
      return '<circle data-node-health="' + esc(n) + '" cx="' + at.x + '" cy="' + ctx.Y(at.y) + '" r="' + (iso ? 33 : 28) + '" fill="' + col + '" fill-opacity="0.08" stroke="' + col + '" stroke-width="1.6" stroke-dasharray="' + (iso ? '2 3' : '5 4') + '"/>' +
        '<text class="t" x="' + (at.x > 650 ? at.x - 36 : at.x + 36) + '" y="' + (ctx.Y(at.y) - 26) + '" text-anchor="' + (at.x > 650 ? 'end' : 'start') + '" style="fill:' + col + '">' + esc(text) + '</text>';
    }).join('');
  }
  function lateBadges(f) {
    return bursts().list.filter((b) => b.arrLast >= f.t - 6 && b.arrFirst <= f.t && b.arrFirst > -Infinity).map((b) => {
      const at = ctx.nodeXY(f, b.node);
      return at ? '<text class="t" x="' + (at.x > 650 ? at.x - 30 : at.x + 30) + '" y="' + (ctx.Y(at.y) + 50) + '" text-anchor="' + (at.x > 650 ? 'end' : 'start') + '" style="fill:' + LATE + '">' + esc(b.node) + ' late data in: ' + b.n + ' readings</text>' : '';
    }).join('');
  }
  function mapSvg(f) {
    if (!ctx || !f.health) return '';
    const local = ctx.state.localNode ? undelivered(f, ctx.state.localNode).map((r) => readingSvg(r, { local: true, held: true, faded: true })).join('') : '';
    const late = visible(f).map((r) => readingSvg(r, { held: r.arr === null || r.arr > f.t })).join('');
    return local + late + nodeRings(f) + lateBadges(f);
  }

  // ---------------------------------------------------------------- timeline
  // one bar per burst, from when its readings were taken to when they reached C2 (violet: still held)
  function timelineSvg(x) {
    return !ctx ? '' : bursts().list.map((b) => {
      const end = b.arrLast > -Infinity ? b.arrLast : b.to, col = b.undelivered ? ISO : LATE;
      const tip = b.node + ': ' + b.n + ' readings taken ' + fmt(b.from) + '–' + fmt(b.to) + (b.arrLast > -Infinity ? ', at C2 ' + fmt(b.arrFirst) + '–' + fmt(b.arrLast) : '') + (b.undelivered ? ', ' + b.undelivered + ' never arrived' : '');
      return '<rect x="' + x(b.from) + '" y="31" width="' + Math.max(2, x(end) - x(b.from)) + '" height="4" rx="2" fill="' + col + '" fill-opacity="0.75"><title>' + esc(tip) + '</title></rect>';
    }).join('');
  }

  // ------------------------------------------------------------------- panel
  function nodeCards(f) {
    return Object.keys(f.health).filter((n) => ['isolated', 'offline', 'presumed_dead'].includes(f.health[n].state)).map((n) => {
      const h = f.health[n], open = ctx.state.localNode === n, held = undelivered(f, n).length;
      const what = h.state === 'isolated' ? 'isolated ' + Math.round(h.silent_s) + ' s, alive, holds ' + Math.round(h.buffered_s) + ' s of data' : h.state.replace('_', ' ') + ' ' + Math.round(h.silent_s) + ' s';
      return '<div class="late-card' + (h.state === 'isolated' ? ' iso' : '') + '"><b>' + esc(n) + '</b> ' + esc(what) + (held ? ' · ' + held + ' readings not at C2' : '') +
        '<button class="late-btn" data-local="' + esc(n) + '" aria-pressed="' + open + '">' + (open ? 'Hide' : 'Show') + ' what it saw</button></div>';
    }).join('');
  }
  function localList(f) {
    const n = ctx.state.localNode;
    if (!n) return '';
    const list = undelivered(f, n);
    if (!list.length) return '<div class="late-note">' + esc(n) + ' holds nothing C2 lacks at this moment.</div>';
    const by = {};
    list.forEach((r) => { by[r.k] = (by[r.k] || 0) + 1; });
    const kinds = Object.keys(by).map((k) => '<span style="color:' + ctx.kcol[k] + '">' + by[k] + ' ' + k + '</span>').join(' · ');
    const rows = list.slice(-6).reverse().map((r) => '<tr><td>' + fmt(r.t) + '</td><td style="color:' + ctx.kcol[r.k] + '">' + r.k + '</td><td>' + esc(readingText(r)) + '</td><td>' + (r.arr === null ? 'held' : 'in transit') + '</td></tr>').join('');
    return '<div class="late-note">' + esc(n) + ' saw, not yet at C2 (violet on the map): ' + kinds + '</div>' +
      '<table class="tbl mono"><thead><tr><th>Taken</th><th>Sensor</th><th>Reading</th><th>State</th></tr></thead><tbody>' + rows + '</tbody></table>';
  }
  const readingText = (r) => (r.m === 'bearing' ? 'bearing ' + Math.round((90 - r.b * 180 / Math.PI + 360) % 360) + '°' :
    r.m === 'rangeaz' ? Math.round(r.r) + ' m @ ' + Math.round((90 - r.b * 180 / Math.PI + 360) % 360) + '°' : Math.round(r.r) + ' m');
  function burstRows() {
    const list = bursts().list;
    if (!list.length) return '<div class="late-note">No late data in this run.</div>';
    const rows = list.map((b) => '<tr><td>' + esc(b.node) + '</td><td>' + fmt(b.from) + '–' + fmt(b.to) + '</td><td>' + (b.arrLast > -Infinity ? fmt(b.arrFirst) + '–' + fmt(b.arrLast) : 'never') + '</td><td>' + b.n + (b.undelivered ? ' (' + b.undelivered + ' lost)' : '') +
      '</td><td><button class="late-btn" data-jump="' + b.from + '">Go to</button></td></tr>').join('');
    return '<table class="tbl mono"><thead><tr><th>Node</th><th>Taken</th><th>At C2</th><th>Readings</th><th></th></tr></thead><tbody>' + rows + '</tbody></table>';
  }
  let lastHtml = '';
  function render(f) {
    const box = ctx && $('lateBody');
    if (!box || !f.health) return;
    const out = nodeCards(f) + localList(f) + '<p class="h" style="margin-top:6px">Late data</p>' + burstRows();
    if (out !== lastHtml) box.innerHTML = lastHtml = out;
  }

  function onClick(e) {
    const local = e.target.closest('[data-local]'), jump = e.target.closest('[data-jump]');
    if (local) { ctx.state.localNode = ctx.state.localNode === local.dataset.local ? null : local.dataset.local; ctx.redraw(); }
    if (jump) { ctx.state.revised = true; $('lateToggle').checked = true; ctx.jump(+jump.dataset.jump); }
  }
  function init(context) {
    ctx = context;
    ctx.state.revised = true;
    ctx.state.localNode = null;
    $('lateToggle').checked = true;
    $('lateToggle').addEventListener('change', (e) => { ctx.state.revised = e.target.checked; shown = new Map(); ctx.redraw(); });
    $('lateBody').addEventListener('click', onClick);
    $('health').addEventListener('click', (e) => {
      const row = e.target.closest('tr[data-node]');
      if (row) { ctx.state.localNode = ctx.state.localNode === row.dataset.node ? null : row.dataset.node; ctx.redraw(); }
    });
  }
  const reset = () => { cache = null; shown = new Map(); lastHtml = ''; if (ctx) ctx.state.localNode = null; };

  global.LateUI = { init, render, mapSvg, timelineSvg, frameAt, reset, bursts: () => bursts().list };
})(typeof window !== 'undefined' ? window : globalThis);
