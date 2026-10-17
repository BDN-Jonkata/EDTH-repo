/*
 * Jamming zones: circles on the map where, while active, messages sent by or to a node inside are lost more
 * often and RF receivers are noisier. A zone is { x, y, radius_m, loss, t_start?, t_end?, rf_noise_mult? }
 * (docs/data-formats.md). The sender's true position and the true time decide, not its drifted clock.
 */
(function (global) {
  const isActive = (z, t) => t >= (z.t_start || 0) && t < (z.t_end === undefined ? Infinity : z.t_end);
  const contains = (z, pos) => Math.hypot(pos.x - z.x, pos.y - z.y) <= z.radius_m;
  // the zones in force at time t, and at position pos when one is given
  const activeZones = (zones, t, pos) => zones.filter((z) => isActive(z, t) && (!pos || contains(z, pos)));
  // the higher of the base loss and the loss of every active zone that holds the node
  const lossAt = (zones, base, pos, t) => activeZones(zones, t, pos).reduce((m, z) => Math.max(m, z.loss), base);
  const rfNoiseMult = (zones, pos, t) => activeZones(zones, t, pos).reduce((m, z) => Math.max(m, z.rf_noise_mult === undefined ? 1 : z.rf_noise_mult), 1);

  const api = { activeZones, lossAt, rfNoiseMult };
  global.Jamming = api;
  if (typeof module !== 'undefined') module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
