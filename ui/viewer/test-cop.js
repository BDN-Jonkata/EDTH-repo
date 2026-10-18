// The COP replay page's logic: reads a run from either engine, counts a frame, follows a track.
// node ui/viewer/test-cop.js
const test = require('node:test');
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const path = require('node:path');
const Cop = require('./cop.js');
const Sim = require('./sim.js');

const tracks = [
  { id: 'T1', x: 10, y: 20, vx: 3, vy: 4, st: 'confirmed', cls: 'hostile' },
  { id: 'T2', x: 30, y: 40, vx: 0, vy: 0, st: 'confirmed', cls: 'friendly' },
  { id: 'T3', x: 50, y: 60, vx: 0, vy: 0, st: 'confirmed', cls: 'unknown' },
  { id: 'T4', x: 70, y: 80, vx: 0, vy: 0, st: 'tentative', cls: 'hostile' },
];
const truth = [{ id: 'H1', kind: 'hostile', x: 11, y: 21, vx: 3, vy: 4 }, { id: 'F1', kind: 'friendly', x: 30, y: 40, vx: 0, vy: 0 }];
const table = (rows) => ({ cols: Object.keys(rows[0]), rows: rows.map((r) => Object.values(r)) });
const run = (frames) => ({ engine: 'python-pipeline', params: { preset: 'challenge' }, scenario: {}, result: { frames, summary: {}, T_END: 10 } });

test('unpack turns {cols, rows} tables into lists of objects and leaves everything else alone', () => {
  assert.deepEqual(Cop.unpack(table([{ a: 1, b: 'x' }, { a: 2, b: 'y' }])), [{ a: 1, b: 'x' }, { a: 2, b: 'y' }]);
  assert.deepEqual(Cop.unpack({ k: [1, 2], cols: 3 }), { k: [1, 2], cols: 3 });
  assert.deepEqual(Cop.unpack([{ a: table([{ q: 1 }, { q: 2 }]) }]), [{ a: [{ q: 1 }, { q: 2 }] }]);
});

test('a frame is counted by class; tentative tracks are not shown; strict and presumed hostile counts differ', () => {
  const c = Cop.counts({ t: 1, tracks, truth });
  assert.equal(c.hostile, 1);
  assert.equal(c.presumed, 2);                    // the hostile and the unknown, not the friendly
  assert.equal(c.truthHostile, 1);
  assert.deepEqual([c.byClass.hostile, c.byClass.friendly, c.byClass.unknown], [1, 1, 1]);
});

test('load reads packed and plain frames and refuses a file that is not a run', () => {
  const frames = [{ k: 0, t: 0, tracks: table(tracks.slice(0, 2)), truth: [truth[0]] }, { k: 1, t: 0.1, tracks: [], truth: [] }];
  const loaded = Cop.load(run(frames));
  assert.equal(loaded.engine, 'python-pipeline');
  assert.equal(loaded.frames[0].tracks.length, 2);
  assert.equal(loaded.frames[1].tracks.length, 0);
  assert.throws(() => Cop.load({}), /not a saved run/);
  assert.throws(() => Cop.load(run([])), /no frames/);
});

test('a track is followed back in time, within the window and only while it exists', () => {
  const frames = [0, 1, 2, 3].map((k) => ({ t: k, tracks: k === 1 ? [] : [{ id: 'T1', x: k * 10, y: 0, st: 'confirmed', cls: 'hostile' }], truth: [] }));
  assert.deepEqual(Cop.trail(frames, 3, 'T1', 2), [[20, 0], [30, 0]]);
  assert.deepEqual(Cop.trail(frames, 3, 'T1', 10), [[0, 0], [20, 0], [30, 0]]);
  assert.deepEqual(Cop.trail(frames, 3, 'nobody', 10), []);
});

test('the summary rows read what either engine wrote, and nothing when there is none', () => {
  const py = Cop.summaryRows({ whole_run: { hostile_tracked_frac: 0.66, count_error_mean_abs: 0.7, pos_rmse_m: 12.34, id_swaps: 1, false_tracks_mean: 0.3, friendlies_flagged: 0 } });
  assert.deepEqual(py[0], ['Hostile tracked', '66 %']);
  assert.deepEqual(py[2], ['Position error', '12.3 m']);
  assert.equal(Cop.summaryRows({ rmse: 5.55, countErr: 0.5, swaps: 0, ffa: 0 })[0][1], '5.5 m');
  assert.deepEqual(Cop.summaryRows({}), []);
  assert.equal(Cop.summaryRows({ whole_run: { pos_rmse_m: null } })[2][1], 'n/a m');
});

test('a run of the JavaScript mock loads in the same page', () => {
  const r = Sim.run({ scenario: require('./scenarios.js').easy, seed: 1, mode: 'optimistic', weather: 'clear', loss: 0 });
  const loaded = Cop.load({ params: r.params, scenario: {}, result: { frames: r.frames.slice(0, 50), summary: r.summary, T_END: r.T_END } });
  assert.equal(loaded.engine, 'js-mock');
  const c = Cop.counts(loaded.frames[40]);
  assert.ok(c.byClass.friendly >= 1);
  assert.ok(Cop.summaryRows(loaded.summary).length > 0);
});

test('a run exported by the Python pipeline loads in the same page and its counts agree with the frame metrics', () => {
  const root = path.join(__dirname, '..', '..');
  const out = execFileSync('python', ['-m', 'pipeline.export_run', '--preset', 'easy', '--index', '0', '--out', path.join(root, 'out', 'cop-test-run.json')], { cwd: root }).toString();
  assert.match(out, /wrote/);
  const loaded = Cop.load(JSON.parse(require('node:fs').readFileSync(path.join(root, 'out', 'cop-test-run.json'), 'utf8')));
  assert.equal(loaded.engine, 'python-pipeline');
  loaded.frames.filter((f, i) => i % 53 === 0).forEach((f) => {
    const c = Cop.counts(f);
    assert.equal(c.hostile, f.m.est);
    assert.equal(c.presumed, f.m.presumed);
    assert.equal(c.truthHostile, f.m.tru);
  });
  assert.ok(Cop.summaryRows(loaded.summary).length > 0);
});
