/*
 * Runs a full simulation off the page's thread and remembers finished runs.
 *
 * A run takes 6 to 10 s and its frames are 25 to 40 MB, so the page asks a worker (degworker.js) for it, and keeps the
 * last few results in IndexedDB. The key holds every option, the scenario and a hash of the page's own scripts, so a
 * code change never shows an old run. Without a worker or storage (file://, private window) it simulates on a timer tick.
 */
(function (global) {
  const DB = 'dds-runs', STORE = 'runs', KEEP = 6;
  let worker = null, pending = null, version = null;

  const hash = (text) => { let h = 2166136261; for (let i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619); } return (h >>> 0).toString(36); };
  const scriptsHash = () => version || (version = Promise.all([].slice.call(document.scripts).filter((s) => s.src).map((s) => fetch(s.src).then((r) => r.text())))
    .then((texts) => hash(texts.join('\u0000'))).catch(() => null));
  const keyOf = (opts, ver) => ver && hash(JSON.stringify(opts)) + '-' + ver;

  function openDb() {
    return new Promise((resolve, reject) => {
      if (typeof indexedDB === 'undefined') return reject(new Error('no storage'));
      const req = indexedDB.open(DB, 1);
      req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: 'key' }).createIndex('t', 't');
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }
  const request = (r) => new Promise((resolve, reject) => { r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });
  const done = (tx) => new Promise((resolve, reject) => { tx.oncomplete = resolve; tx.onerror = () => reject(tx.error); tx.onabort = () => reject(tx.error); });

  const load = (db, key) => request(db.transaction(STORE).objectStore(STORE).get(key)).then((row) => (row ? row.res : null));
  function save(db, key, res) {
    const tx = db.transaction(STORE, 'readwrite'), store = tx.objectStore(STORE);
    store.put({ key, t: Date.now(), res });
    request(store.index('t').getAllKeys()).then((keys) => keys.slice(0, Math.max(0, keys.length - KEEP)).forEach((k) => store.delete(k)));
    return done(tx);
  }

  // one run at a time: a newer request makes the one still computing obsolete
  function simulate(opts) {
    if (pending) pending.reject(new Error('replaced'));
    if (worker) worker.terminate();
    return new Promise((resolve, reject) => {
      pending = { reject };
      let w = null;
      try { w = location.protocol === 'file:' || typeof Worker === 'undefined' ? null : new Worker('degworker.js'); } catch (e) { w = null; }
      worker = w;
      if (!w) return setTimeout(() => { try { resolve(global.Sim.run(opts)); } catch (e) { reject(e); } }, 0);
      w.onmessage = (e) => { pending = null; resolve(e.data.res); };
      // a worker that cannot start must not leave the page without a run: simulate here instead
      w.onerror = () => { worker = null; pending = null; setTimeout(() => { try { resolve(global.Sim.run(opts)); } catch (e) { reject(e); } }, 0); };
      w.postMessage({ full: true, options: opts });
    });
  }

  // opts is what Sim.run takes (scenario included); resolves with its result
  function run(opts) {
    return Promise.all([scriptsHash(), openDb().catch(() => null)]).then(([ver, db]) => {
      const key = keyOf(opts, ver);
      const cached = db && key ? load(db, key).catch(() => null) : Promise.resolve(null);
      return cached.then((hit) => hit || simulate(opts).then((res) => { if (db && key) save(db, key, res).catch(() => {}); return res; }));
    });
  }

  const api = { run };
  global.RunCache = api;
  if (typeof module !== 'undefined') module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
