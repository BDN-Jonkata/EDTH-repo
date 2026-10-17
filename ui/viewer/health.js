/*
 * Link health and per-message trust: a line-by-line port of health/link.py and health/monitor.py (the Python is the
 * reference; health/testdata/health_cases.json is the shared test, run by test-health.js).
 * One node's link is judged from the sequence numbers and arrival times of its messages: a Bayesian two-state link
 * (p_bad), a frequentist loss rate with a Wilson interval and a CUSUM change test, and a state: ok, degraded,
 * offline (4 s of silence), presumed_dead (15 s). Trust = the state's factor times 0.5 ** (age / half-life).
 * Not wired into sim.js yet: the mock simulation keeps its own health table (storefwd.js).
 */
(function (global) {
  const DEFAULTS = {
    loss_good: 0.02, loss_bad: 0.95, stay_good: 0.97, stay_bad: 0.80, prior_bad: 0.1,
    window: 40, wilson_z: 1.96, degraded_loss: 0.30, recovered_loss: 0.20, min_outcomes: 20,
    cusum_p0: 0.10, cusum_p1: 0.50, cusum_h: Math.log(200), max_gap: 200,
    offline_s: 4.0, dead_s: 15.0, half_life_s: 10.0, late_s: 3.0, layers: 'both',
  };
  const HEALTH_FACTOR = { ok: 1.0, degraded: 0.5, offline: 0.2, presumed_dead: 0.0 };
  const SILENCE_FLOOR = { ok: 0.0, degraded: 0.7, offline: 1.0, presumed_dead: 0.5 };

  function wilson(missed, n, z) {
    if (n === 0) return [0.0, 1.0];
    const p = missed / n, z2 = z * z;
    const centre = (p + z2 / (2 * n)) / (1 + z2 / n);
    const half = z * Math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n);
    return [Math.max(0.0, centre - half), Math.min(1.0, centre + half)];
  }

  function createLink(config, t) {
    return { config, lastSeq: null, lastHeard: t || 0.0, pBad: config.prior_bad, outcomes: [], cusum: 0.0, degraded: false };
  }

  function outcome(link, lost) {
    const cfg = link.config;
    const bad = link.pBad * cfg.stay_bad + (1 - link.pBad) * (1 - cfg.stay_good);
    const likeBad = lost ? cfg.loss_bad : 1 - cfg.loss_bad;
    const likeGood = lost ? cfg.loss_good : 1 - cfg.loss_good;
    link.pBad = bad * likeBad / (bad * likeBad + (1 - bad) * likeGood);
    link.outcomes.push(lost);
    if (link.outcomes.length > cfg.window) link.outcomes.shift();
    const step = lost ? Math.log(cfg.cusum_p1 / cfg.cusum_p0) : Math.log((1 - cfg.cusum_p1) / (1 - cfg.cusum_p0));
    link.cusum = Math.min(2 * cfg.cusum_h, Math.max(0.0, link.cusum + step));
  }

  const lossRate = (link) => (link.outcomes.length ? link.outcomes.reduce((a, b) => a + b, 0) / link.outcomes.length : 0.0);
  const alarm = (link) => link.cusum > link.config.cusum_h;
  const interval = (link) => wilson(link.outcomes.reduce((a, b) => a + b, 0), link.outcomes.length, link.config.wilson_z);

  function updateDegraded(link) {
    const cfg = link.config;
    if (link.outcomes.length < cfg.min_outcomes) return;
    const rate = lossRate(link);
    const bayesBad = link.pBad > 0.5, bayesOk = link.pBad < 0.2;
    const freqBad = alarm(link) || interval(link)[0] >= cfg.degraded_loss || rate >= cfg.degraded_loss;
    const freqOk = !alarm(link) && rate < cfg.recovered_loss;
    const useBayes = cfg.layers === 'both' || cfg.layers === 'bayes';
    const useFreq = cfg.layers === 'both' || cfg.layers === 'freq';
    if ((useBayes && bayesBad) || (useFreq && freqBad)) link.degraded = true;
    else if ((bayesOk || !useBayes) && (freqOk || !useFreq)) link.degraded = false;
  }

  // a message with number seq arrived at t; the numbers skipped are messages lost
  function observeLink(link, seq, t) {
    if (link.lastSeq !== null) {
      if (seq <= link.lastSeq) return; // a duplicate or a late resend says nothing new about the link
      for (let i = 0; i < Math.min(seq - link.lastSeq - 1, link.config.max_gap); i++) outcome(link, 1);
    }
    outcome(link, 0);
    link.lastSeq = seq;
    link.lastHeard = t;
    updateDegraded(link);
  }

  function linkState(link, t) {
    const silent = t - link.lastHeard;
    if (silent >= link.config.dead_s) return 'presumed_dead';
    if (silent >= link.config.offline_s) return 'offline';
    return link.degraded ? 'degraded' : 'ok';
  }

  function create(config) {
    return { config: Object.assign({}, DEFAULTS, config || {}), nodes: {} };
  }

  function observe(monitor, message, t) {
    const h = message.header;
    if (!monitor.nodes[h.source_id]) monitor.nodes[h.source_id] = createLink(monitor.config, t);
    observeLink(monitor.nodes[h.source_id], h.seq, t);
  }

  const state = (monitor, node, t) => (monitor.nodes[node] ? linkState(monitor.nodes[node], t) : 'ok');
  const trust = (monitor, node, t, ageS) => HEALTH_FACTOR[state(monitor, node, t)] * Math.pow(0.5, Math.max(0.0, ageS || 0.0) / monitor.config.half_life_s);
  function explainsSilence(monitor, node, t) {
    const pBad = monitor.nodes[node] ? monitor.nodes[node].pBad : 0.0;
    return Math.max(SILENCE_FLOOR[state(monitor, node, t)], Math.min(pBad, 0.5));
  }
  const isLate = (monitor, ageS) => ageS > monitor.config.late_s;

  function snapshot(monitor, t) {
    const out = {};
    Object.keys(monitor.nodes).forEach((n) => {
      const h = monitor.nodes[n];
      out[n] = { state: linkState(h, t), p_bad: h.pBad, loss_rate: lossRate(h), alarm: alarm(h), silent_s: t - h.lastHeard };
    });
    return out;
  }

  const api = { DEFAULTS, wilson, create, observe, state, trust, explainsSilence, isLate, snapshot };
  global.Health = api;
  if (typeof module !== 'undefined') module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
