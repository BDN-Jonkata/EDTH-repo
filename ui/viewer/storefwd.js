/*
 * Store-and-forward and link health for the mock channel (docs/data-formats.md, "Store-and-forward").
 *
 * Node side: every message a node sends is kept until C2 acknowledges it (at most BUFFER_S seconds). C2
 * broadcasts a `c2_ack` once a second; a node that hears no ack for OFFLINE_ACKS seconds counts itself offline.
 * After each ack the node resends what C2 says is missing, oldest first, within a byte budget.
 *
 * C2 side: per node, which `seq` numbers arrived. From that come the ack (everything up to `upto`, plus the
 * ranges still missing) and the node's health: ok, degraded, offline, presumed_dead. A node reports the oldest
 * `seq` it still holds; C2 stops asking for anything older, so lost messages that expired do not block the ack.
 */
(function (global) {
  const ACK_EVERY_S = 1;       // ASSUMED: how often C2 broadcasts its ack
  const OFFLINE_ACKS = 3;      // ASSUMED: acks a node may miss before it counts itself offline
  const BUFFER_S = 60;         // ASSUMED: seconds of unacknowledged messages a node keeps
  const RESEND_SHARE = 0.5;    // ASSUMED: share of a capped link that resends may use
  const RESEND_AGAIN_S = 2;    // a message resent this recently is not resent again yet
  const RESEND_MIN_AGE_S = 1;  // younger messages may still be on their way: not resent yet
  const LATE_S = 3;            // older than this on arrival: history, not a live reading
  const OFFLINE_S = 4;         // ASSUMED: C2 heard nothing from a node for this long
  const DEAD_S = 15;           // ASSUMED: ... and for this long: presumed dead (or jammed: C2 cannot tell)
  const ISOLATED_S = 30;       // ASSUMED: silent this long, yet the node itself is alive and holding data: isolated, not dead
  const DEGRADED_LOSS = 0.3;   // ASSUMED: share of recent messages missing that makes a link degraded
  const RECOVERED_LOSS = 0.2;  // ... and below this it is ok again (hysteresis, so the state does not flap)
  const LOSS_WINDOW = 50;      // recent seq numbers the loss share is measured over
  const IN_FLIGHT = 5;         // the newest seq numbers may still be on their way: not counted as missing
  const MIN_SAMPLES = 20;      // fewer seq numbers than this: too little to call a link degraded
  const MAX_RANGES = 32;       // missing ranges one ack entry lists

  // ------------------------------------------------------------------ node side
  const createNode = (cfg) => ({ bufferS: (cfg && cfg.buffer_s) || BUFFER_S, store: [], lastAck: 0, stats: { stored: 0, expired: 0, resent: 0 } });

  // keep a copy of what was sent, without the channel's arrival time
  function remember(node, payload, t) {
    const { arr, ...copy } = payload; // eslint-disable-line no-unused-vars
    node.store.push({ seq: payload.header.seq, t, payload: copy, resentAt: -Infinity });
    node.stats.stored++;
    while (node.store.length && node.store[0].t < t - node.bufferS) { node.store.shift(); node.stats.expired++; }
  }
  const isMissing = (entry, seq) => entry.missing.some(([a, b]) => seq >= a && seq <= b);
  // drop what C2 has; return what it is missing, oldest first, within `budget` bytes (Infinity: no cap)
  function onAck(node, entry, t, budget, sizeOf) {
    node.lastAck = t;
    node.store = node.store.filter((m) => m.seq > entry.max || isMissing(entry, m.seq));
    const out = [];
    let left = budget;
    for (const m of node.store) {
      if (m.seq > entry.max || t - m.t < RESEND_MIN_AGE_S || t - m.resentAt < RESEND_AGAIN_S) continue;
      const bytes = sizeOf(m.payload);
      if (bytes > left) break;
      left -= bytes; m.resentAt = t; node.stats.resent++;
      out.push(Object.assign({}, m.payload));
    }
    return out;
  }
  const isOffline = (node, t) => t - node.lastAck > OFFLINE_ACKS * ACK_EVERY_S + 1e-9;
  const bufferedS = (node, t) => (node.store.length ? t - node.store[0].t : 0);
  function status(node, t) {
    return { offline: isOffline(node, t), buffered_s: Math.round(bufferedS(node, t) * 10) / 10, oldest_seq: node.store.length ? node.store[0].seq : null };
  }

  // ------------------------------------------------------------------ C2 side
  const createReceiver = () => ({ upto: 0, max: 0, got: new Set(), lastT: null, floor: 0 });
  // false when this seq already arrived (the original got through and so did a resend)
  function receive(r, seq, t) {
    if (seq <= r.upto || r.got.has(seq)) return false;
    r.got.add(seq);
    r.max = Math.max(r.max, seq);
    r.lastT = t;
    advance(r);
    return true;
  }
  // the node no longer holds anything older than `oldest`: stop waiting for it
  function skipBelow(r, oldest) {
    if (oldest === null || oldest === undefined || oldest - 1 <= r.upto) return;
    r.floor = Math.max(r.floor, oldest - 1);
    advance(r);
  }
  function advance(r) {
    if (r.floor > r.upto) {
      for (const s of r.got) if (s <= r.floor) r.got.delete(s);
      r.upto = r.floor;
    }
    while (r.got.has(r.upto + 1)) { r.got.delete(r.upto + 1); r.upto++; }
  }
  // { upto, max, missing: [[from, to], ...] } for one node
  function ackEntry(r) {
    const missing = [];
    let start = null;
    for (let s = r.upto + 1; s <= r.max && missing.length < MAX_RANGES; s++) {
      if (!r.got.has(s)) { if (start === null) start = s; } else if (start !== null) { missing.push([start, s - 1]); start = null; }
    }
    if (start !== null && missing.length < MAX_RANGES) missing.push([start, r.max]);
    return { upto: r.upto, max: r.max, missing };
  }
  // share of the recent seq numbers (old enough to have arrived) that are still missing
  function lossShare(r) {
    const to = r.max - IN_FLIGHT, from = Math.max(1, to - LOSS_WINDOW + 1);
    if (to - from + 1 < MIN_SAMPLES) return 0;
    let gone = 0;
    for (let s = Math.max(from, r.upto + 1); s <= to; s++) if (!r.got.has(s)) gone++;
    return gone / (to - from + 1);
  }
  // `before`: the previous state, so a degraded link must recover clearly before it counts as ok.
  // `holding`: the node itself is alive and cut off (its own store says so); C2 could only learn that afterwards.
  function health(r, t, before, holding) {
    const silent = r.lastT === null ? t : t - r.lastT, loss = lossShare(r);
    const lossy = loss >= (before === 'degraded' ? RECOVERED_LOSS : DEGRADED_LOSS);
    const state = holding && silent >= ISOLATED_S ? 'isolated' : silent >= DEAD_S ? 'presumed_dead' : silent >= OFFLINE_S ? 'offline' : lossy ? 'degraded' : 'ok';
    return { state, silent_s: Math.round(silent * 10) / 10, loss: Math.round(loss * 100) / 100 };
  }

  const api = {
    ACK_EVERY_S, OFFLINE_ACKS, BUFFER_S, RESEND_SHARE, LATE_S, OFFLINE_S, DEAD_S, ISOLATED_S, DEGRADED_LOSS,
    createNode, remember, onAck, isOffline, bufferedS, status, createReceiver, receive, skipBelow, ackEntry, health,
  };
  global.StoreFwd = api;
  if (typeof module !== 'undefined') module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
