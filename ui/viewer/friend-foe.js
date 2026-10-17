/* Two-axis estimator port; friend_foe/estimator.py is the reference.
 * The shared Python cases check probabilities, flags and motion evidence. */
(function (global) {
  'use strict';
  const B = typeof window !== 'undefined' ? window.Behavior : require('./behavior.js');
  const DEFAULTS = { beacon_max_age_s: 2, beacon_clock_tolerance_s: 0.5, gate_sigmas: 3, gate_min_m: 5,
    min_existence: 0.3, min_updates: 5, match_step: 1, no_beacon_per_s: 0.2, no_beacon_floor: -1.5,
    beacon_rate_hz: 2, delivery_prior: 0.8, delivery_prior_n: 10, delivery_tau_s: 30, delivery_min: 0.05,
    max_dt_s: 2, llr_limit: 4, friendly_enter: 0.9, friendly_exit: 0.7, suspicious_enter: 0.3, suspicious_exit: 0.4,
    suspicious_requires_behavior: false, suspicious_threat_enter: 0.65, suspicious_threat_exit: 0.55,
    hostile_enter: 0.9, hostile_exit: 0.7, peaceful_min_updates: 0, peaceful_enter: 0.1, peaceful_exit: 0.3, threat_tau_s: 20, memory_ttl_s: 30 };
  const sigmoid = (x) => 1 / (1 + Math.exp(-x));
  class AutomaticEstimator {
    constructor(behaviorConfig, config, verifiedIds = []) {
      this.config = Object.assign({}, DEFAULTS, config || {}, { suspicious_requires_behavior: true });
      const c = this.config;
      this.behavior = new B.Model(Object.assign({}, behaviorConfig || {}, { memory_ttl_s: c.memory_ttl_s }), c.threat_tau_s, c.max_dt_s, c.llr_limit);
      this.memory = new Map(); this.seenBeacons = new Map(); this.lastT = null;
      this.received = c.delivery_prior * c.delivery_prior_n; this.expected = c.delivery_prior_n;
      verifiedIds.forEach((id) => this.memory.set(id, { llr: c.llr_limit, threat: 0, n: c.min_updates, cls: 'friendly', lastT: 0 }));
    }
    get deliveryRate() { return Math.max(this.config.delivery_min, Math.min(1, this.received / this.expected)); }
    update(t, tracks, beacons) {
      this.behavior.begin(t);
      if (this.lastT !== null && t <= this.lastT) return this.lastResult.slice();
      const c = this.config, dt = this.lastT === null ? 0.5 : Math.max(0, Math.min(t - this.lastT, c.max_dt_s));
      this.memory.forEach((m, id) => { if (t - m.lastT > c.memory_ttl_s) this.memory.delete(id); });
      const usable = tracks.filter((tr) => tr.existence_prob >= c.min_existence), matches = this.match(t, usable, beacons);
      const out = usable.map((tr) => {
        if (!this.memory.has(tr.track_id)) this.memory.set(tr.track_id, { llr: 0, threat: 0, n: 0, cls: 'unknown', lastT: 0 });
        const m = this.memory.get(tr.track_id), elapsed = m.n ? Math.max(0, Math.min(t - m.lastT, c.max_dt_s)) : dt;
        const match = matches.get(tr.track_id);
        if (match && match.fresh) m.llr += c.match_step;
        else if (!match && m.llr > c.no_beacon_floor) m.llr = Math.max(m.llr - c.no_beacon_per_s * elapsed * this.deliveryRate, c.no_beacon_floor);
        m.llr = Math.max(-c.llr_limit, Math.min(c.llr_limit, m.llr));
        m.threat = Math.max(-c.llr_limit, Math.min(c.llr_limit, m.threat * Math.exp(-elapsed / c.threat_tau_s) + this.behavior.evidence(tr)));
        m.n++; m.lastT = t;
        const p = sigmoid(m.llr), q = sigmoid(m.threat), prev = m.cls;
        const riskSupported = !c.suspicious_requires_behavior || q >= (prev === 'suspicious' ? c.suspicious_threat_exit : c.suspicious_threat_enter);
        m.cls = m.n < c.min_updates ? 'unknown' :
          p >= (prev === 'friendly' ? c.friendly_exit : c.friendly_enter) ? 'friendly' :
            q >= (prev === 'hostile' ? c.hostile_exit : c.hostile_enter) ? 'hostile' :
              m.n >= c.peaceful_min_updates && q <= (prev === 'peaceful' ? c.peaceful_exit : c.peaceful_enter) ? 'peaceful' :
                riskSupported && p <= (prev === 'suspicious' ? c.suspicious_exit : c.suspicious_enter) ? 'suspicious' : 'unknown';
        const prob = m.cls === 'friendly' ? p : m.cls === 'hostile' ? q : m.cls === 'peaceful' ? 1 - q : m.cls === 'suspicious' ? (c.suspicious_requires_behavior ? q : 1 - p) : Math.max(p, 1 - p);
        return { track_id: tr.track_id, t, cls: m.cls, class_prob: prob, p_friendly: p, matched_beacon: match?.id ?? null, p_hostile: q };
      });
      const forget = Math.exp(-dt / c.delivery_tau_s), friendly = out.filter((v) => v.cls === 'friendly');
      this.received = this.received * forget + friendly.filter((v) => matches.get(v.track_id)?.fresh).length;
      this.expected = this.expected * forget + friendly.length * c.beacon_rate_hz * dt;
      this.memory.forEach((m, id) => { if (t - m.lastT > c.memory_ttl_s) this.memory.delete(id); });
      this.behavior.verified = new Set(out.filter((v) => v.cls === 'friendly').map((v) => v.track_id));
      this.lastT = t; this.lastResult = out;
      return out;
    }
    match(t, tracks, beacons) {
      const c = this.config, pairs = [], matches = new Map();
      this.seenBeacons.forEach((seen, key) => { if (t - seen > c.memory_ttl_s) this.seenBeacons.delete(key); });
      const newest = new Map();
      beacons.forEach((b) => {
        if (t - b.t >= -c.beacon_clock_tolerance_s && t - b.t <= c.beacon_max_age_s)
          newest.set(b.friend_id, Math.max(newest.get(b.friend_id) ?? -Infinity, b.t));
      });
      tracks.forEach((tr, i) => beacons.forEach((b, j) => {
        const age = t - b.t;
        if (age < -c.beacon_clock_tolerance_s || age > c.beacon_max_age_s || b.t !== newest.get(b.friend_id)) return;
        const pred = b.position.map((p, k) => p + b.velocity[k] * Math.max(0, age));
        const gate = Math.max(c.gate_min_m, c.gate_sigmas * Math.hypot(tr.pos_sigma, b.pos_sigma));
        const d = Math.hypot(...tr.position.map((p, k) => p - pred[k]));
        if (d <= gate) pairs.push([d, i, j]);
      }));
      pairs.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2]);
      const usedT = new Set(), usedB = new Set(), usedF = new Set();
      pairs.forEach(([, i, j]) => {
        if (usedT.has(i) || usedB.has(j) || usedF.has(beacons[j].friend_id)) return;
        usedT.add(i); usedB.add(j); usedF.add(beacons[j].friend_id);
        const b = beacons[j], key = JSON.stringify([b.friend_id, b.t]), fresh = !this.seenBeacons.has(key);
        if (fresh) this.seenBeacons.set(key, t);
        matches.set(tracks[i].track_id, { id: b.friend_id, fresh });
      });
      return matches;
    }
    explain(id) { return this.behavior.explain(id); }
    forget(id) { this.memory.delete(id); this.behavior.memory.delete(id); }
  }
  global.FriendFoe = { AutomaticEstimator, DEFAULTS };
  if (typeof module !== 'undefined') module.exports = global.FriendFoe;
})(typeof window !== 'undefined' ? window : globalThis);
