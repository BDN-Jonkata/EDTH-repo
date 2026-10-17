/*
 * Link capacity for the mock channel: each node has one link to C2 that carries `kbps`. A message occupies the
 * link for bytes / rate seconds, so what a link delivers in any window can never exceed the cap. Messages wait
 * in order; when more than QUEUE_S seconds of data are waiting, the oldest are dropped. Sizes are the JSON
 * length without the mock-only fields (`z`, `arr`), unrounded, so an upper bound (docs/data-formats.md).
 */
(function (global) {
  const QUEUE_S = 2; // ASSUMED: seconds of backlog a node keeps before dropping its oldest messages

  function sizeOf(payload) {
    const { z, arr, ...sent } = payload; // eslint-disable-line no-unused-vars
    return JSON.stringify(sent).length;
  }
  const create = (kbps) => ({ bytesPerS: kbps * 125, links: {}, stats: {} });
  const stat = (net, type) => net.stats[type] || (net.stats[type] = { count: 0, bytes: 0, dropped: 0 });

  // put a message on the sender's link; the oldest waiting messages are dropped when the backlog is too long
  function enqueue(net, node, payload, t, latency) {
    const link = net.links[node] || (net.links[node] = { busyUntil: 0, waiting: [], waitingBytes: 0 });
    const msg = { node, payload, t, latency, bytes: sizeOf(payload), type: payload.type };
    const s = stat(net, msg.type);
    s.count++; s.bytes += msg.bytes;
    link.waiting.push(msg); link.waitingBytes += msg.bytes;
    while (link.waitingBytes > QUEUE_S * net.bytesPerS && link.waiting.length > 1) {
      const old = link.waiting.shift();
      link.waitingBytes -= old.bytes;
      stat(net, old.type).dropped++;
    }
  }
  // send every message the links can start by time t; send(msg, finish) gets the moment its last byte leaves
  function drain(net, t, send) {
    Object.keys(net.links).forEach((node) => {
      const link = net.links[node];
      while (link.waiting.length && link.busyUntil <= t) {
        const msg = link.waiting.shift();
        link.waitingBytes -= msg.bytes;
        link.busyUntil = Math.max(link.busyUntil, msg.t) + msg.bytes / net.bytesPerS;
        send(msg, link.busyUntil);
      }
    });
  }
  // per message type: how many were offered, their bytes, the average size, how many were dropped
  function summary(net) {
    const out = {};
    Object.keys(net.stats).forEach((type) => {
      const s = net.stats[type];
      out[type] = { count: s.count, bytes: s.bytes, avg_bytes: s.bytes / s.count, dropped: s.dropped };
    });
    return out;
  }

  const api = { QUEUE_S, sizeOf, create, enqueue, drain, summary };
  global.LinkCap = api;
  if (typeof module !== 'undefined') module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
