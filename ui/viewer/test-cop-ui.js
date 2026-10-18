// The COP replay page's drawing code, run against a minimal fake DOM (no browser here): every function runs on a real
// exported run without throwing, and what is drawn matches the frame. Look at the page in a browser for the rest.
// node ui/viewer/test-cop-ui.js
const test = require('node:test');
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

class FakeNode {
  constructor(tag) { Object.assign(this, { tag, children: [], attrs: {}, style: {}, listeners: {}, hidden: false, checked: false, value: '', className: '', _text: '' }); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  appendChild(c) { this.children.push(c); return c; }
  append(...cs) { cs.forEach((c) => this.children.push(typeof c === 'string' ? Object.assign(new FakeNode('#text'), { _text: c }) : c)); }
  replaceChildren() { this.children = []; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  set textContent(t) { this._text = String(t); this.children = []; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(''); }
  all(tag) { return this.children.flatMap((c) => [c, ...c.all(tag)]).filter((n) => !tag || n.tag === tag); }
}

const IDS = ['map', 'clock', 'counts', 'tracks', 'summary', 'play', 'back', 'fwd', 'scrub', 'speed', 'tTrails', 'tNames', 'tTruth', 'file', 'drop', 'msg', 'engine', 'runInfo'];
const nodes = Object.fromEntries(IDS.map((id) => [id, new FakeNode(id)]));
nodes.tTrails.checked = nodes.tNames.checked = true;
globalThis.document = { getElementById: (id) => nodes[id], createElementNS: (ns, tag) => new FakeNode(tag), createElement: (tag) => new FakeNode(tag), addEventListener() {} };
globalThis.location = { search: '' };
globalThis.requestAnimationFrame = () => 0;
require('./cop.js');
require('./cop-ui.js');
const { CopUI } = globalThis;

function pythonRun() {
  const root = path.join(__dirname, '..', '..'), file = path.join(root, 'out', 'cop-ui-test-run.json');
  execFileSync('python', ['-m', 'pipeline.export_run', '--preset', 'challenge', '--index', '0', '--out', file], { cwd: root });
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}
const run = pythonRun();

test('opening a Python run labels the engine, fills the summary and draws the first frame', () => {
  CopUI.openRun(run);
  assert.equal(nodes.msg.textContent, '');
  assert.equal(nodes.engine.textContent, 'Python pipeline');
  assert.equal(nodes.drop.hidden, true);
  assert.equal(nodes.scrub.max, run.result.frames.length - 1);
  assert.match(nodes.runInfo.textContent, /challenge/);
  assert.match(nodes.summary.textContent, /Hostile tracked/);
  assert.ok(nodes.map.all('line').length >= 20, 'grid');
});

test('one circle per shown track and one count row per class on screen', () => {
  CopUI.seek(600);
  const frame = CopUI.state.run.frames[600], shown = frame.tracks.filter((t) => t.st !== 'tentative');
  assert.equal(nodes.map.all('circle').length, shown.length);
  assert.equal(nodes.tracks.all('tr').length, shown.length + 1);                  // plus the header row
  assert.match(nodes.counts.textContent, /Hostile tracks/);
  assert.match(nodes.clock.textContent, /^60\.0 s of 120 s/);
});

test('the truth overlay is off until asked for, and then draws every true object and the true hostile count', () => {
  CopUI.seek(600);
  assert.equal(nodes.map.all('path').length, 0);
  assert.doesNotMatch(nodes.counts.textContent, /True hostiles/);
  nodes.tTruth.checked = true;
  nodes.tTruth.listeners.change.forEach((f) => f());
  const frame = CopUI.state.run.frames[600];
  assert.equal(nodes.map.all('path').length, frame.truth.length);
  assert.match(nodes.counts.textContent, /True hostiles \(truth\)2/);
  nodes.tTruth.checked = false;
});

test('playing, stepping and seeking stay inside the run', () => {
  CopUI.seek(-5);
  assert.equal(CopUI.state.k, 0);
  CopUI.seek(10 ** 9);
  assert.equal(CopUI.state.k, run.result.frames.length - 1);
  nodes.back.listeners.click.forEach((f) => f());
  assert.equal(CopUI.state.k, run.result.frames.length - 11);
  CopUI.seek(0);
  CopUI.play();
  assert.equal(CopUI.state.playing, true);
  assert.equal(nodes.play.textContent, 'Pause');
  CopUI.play();
  assert.equal(CopUI.state.playing, false);
});

test('a file that is not a run is refused with a message and the old run stays', () => {
  CopUI.openRun({ nonsense: true });
  assert.match(nodes.msg.textContent, /not a saved run/);
  assert.equal(CopUI.state.run.engine, 'python-pipeline');
});
