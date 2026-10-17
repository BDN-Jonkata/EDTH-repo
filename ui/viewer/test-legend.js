// Tests for the map legend. Run: node ui/viewer/test-legend.js
// legend.js needs a page; a tiny stand-in for the few elements it touches is enough to read what it would show.
const assert = require('assert');

const els = {};
const el = (id) => els[id] || (els[id] = { id, hidden: false, innerHTML: '', checked: false, listeners: {}, attrs: {},
  addEventListener(type, fn) { this.listeners[type] = fn; }, setAttribute(k, v) { this.attrs[k] = v; }, focus() {} });
global.document = { getElementById: el };
global.location = { search: '' };
require('./legend.js');

const sensor = (node, kind, fields) => ({ node, kind, fields, module: 'm1' });
const state = { layers: { net: true, tracks: true }, scenario: { degradations: { network: { jamming_zones: [{ x: 1 }] } }, clutter: [{ id: 'B1' }, { id: 'V1' }] },
  res: { sensors: [sensor('GS1', 'EO', ['bearing_deg', 'class_hint']), sensor('F1', 'RAD', ['range_m'])] } };
const ctx = {
  state, layers: [['tracks', 'Fused tracks', true, '<path/>'], ['raw', 'Raw observations', false, '<path/>']],
  className: { friendly: 'Friendly', hostile: 'Hostile', unknown: 'Unknown' }, classColor: () => '#fff', kcol: { EO: '#aaa', RAD: '#0cf', IR: '#e85', MIC: '#fa3', RF: '#b8f' },
  kdash: { EO: '5 4', RAD: '8 3', IR: '4 3', MIC: '1 4', RF: '2 5' }, linkStyle: (q) => ({ col: '#7D8794', dash: q > 0.9 ? '' : '6 4' }),
  glyph: (cls) => '<g data-glyph="' + cls + '"/>', marks: { c2: '<g data-mark="c2"/>', ground: '<g data-mark="ground"/>' },
  rangeNow: (s) => (s.kind === 'EO' ? 180 : 400), nominalRange: (s) => (s.kind === 'EO' ? 450 : 400), shortField: (n) => ({ bearing_deg: 'brg', class_hint: 'class', range_m: 'rng' }[n]),
  redraw: () => {},
};
const frame = { tracks: [{ cls: 'hostile', st: 'confirmed' }, { cls: 'hostile', st: 'tentative' }, { cls: 'friendly', st: 'confirmed' }], cross: null };
const shown = () => { Legend.render(frame); return el('legendBody').innerHTML; };
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

Legend.init(ctx);
assert.strictEqual(el('legend').hidden, true, 'closed until asked for');
el('legendBtn').listeners.click();
assert.strictEqual(el('legend').hidden, false);

test('only the track classes on screen are listed, each with its count', () => {
  const html = shown();
  assert.ok(html.includes('data-glyph="hostile"') && html.includes('data-glyph="friendly"'));
  assert.ok(!html.includes('data-glyph="unknown"'));
  assert.ok(html.includes('2 now') && html.includes('1 now'));
});
test('only the states that exist are listed', () => {
  const html = shown();
  assert.ok(html.includes('Tentative') && html.includes('Confirmed') && !html.includes('Coasting'));
});
test('sensors come from the run: kinds, nodes, range now and the weather mark', () => {
  const html = shown();
  assert.ok(html.includes('EO camera') && html.includes('GS1') && html.includes('180–180 m ▼ weather'));
  assert.ok(html.includes('Radar') && html.includes('400–400 m') && !html.includes('Thermal camera'));
  assert.ok(html.includes('reports brg class'));
});
test('the scenario decides jamming and clutter rows; the crossing only when there is one', () => {
  const html = shown();
  assert.ok(html.includes('Jamming zone') && html.includes('2 bird or vehicle'));
  assert.ok(!html.includes('Predicted crossing'));
  frame.cross = { tca: 5 };
  assert.ok(shown().includes('Predicted crossing'));
  frame.cross = null;
});
test('links are listed only while the network layer is on', () => {
  assert.ok(shown().includes('Degraded'));
  state.layers.net = false;
  assert.ok(!shown().includes('Degraded'));
  state.layers.net = true;
});
test('all symbols lists everything, present or not', () => {
  el('legendAll').checked = true;
  el('legendAll').listeners.change({ target: el('legendAll') });
  const html = shown();
  assert.ok(html.includes('data-glyph="unknown"') && html.includes('Coasting') && html.includes('Thermal camera') && html.includes('Not in this scenario.'));
});
test('layers show their on/off state', () => {
  const html = shown();
  assert.ok(html.includes('lg-chip on"><svg') && html.includes('lg-chip"><svg'));
});
test('a closed legend draws nothing', () => {
  el('legend').hidden = true;
  el('legendBody').innerHTML = 'untouched';
  Legend.render(frame);
  assert.strictEqual(el('legendBody').innerHTML, 'untouched');
});

let failed = 0;
tests.forEach(([name, fn]) => { try { fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + e.message); } });
if (failed) process.exit(1);
