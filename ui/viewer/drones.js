// Commanded drone motion: pure maths, no simulation state. sim.js owns the channel, acks and retries.
//
// A drone d is { mode, x, y, vx, vy, heading, target, cap, face }:
//   mode     'patrol' (the scripted loop; d is not used), 'goto', 'hold' or 'return'
//   heading  where the camera points, in maths radians (0 = east, counter-clockwise); kept when the drone stops
//   face     null, { point: [x, y] } or { heading: rad }: what the camera should point at
// lim is the platform's flight limits: { max_speed_mps, max_accel_mps2, max_turn_dps } (assumed values in the catalog).
(function (global) {
  const D2R = Math.PI / 180;
  const SCHEMA_VERSION = 1;
  const APPROACH_GAIN = 1.5; // 1/s: close to the point smoothly instead of circling it
  const COMMANDS = ['goto', 'hold', 'return_to_patrol'];
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const wrapPi = (a) => Math.atan2(Math.sin(a), Math.cos(a));

  // every message carries the same header; seq counts per source so msg_id is unique
  function makeHeader(seqs, source, tSent) {
    const seq = (seqs[source] = (seqs[source] || 0) + 1);
    return { msg_id: source + '-' + seq, source_id: source, t_sent: tSent, seq, schema_version: SCHEMA_VERSION };
  }

  // null if the command can be carried out, otherwise the reason it is rejected
  function invalid(cmd, size) {
    if (COMMANDS.indexOf(cmd.command) < 0) return 'unknown command ' + cmd.command;
    if (cmd.command === 'goto') {
      const t = cmd.target;
      if (!Array.isArray(t) || t.length < 2 || !t.slice(0, 2).every((v) => v >= 0 && v <= size)) return 'target outside the area';
    }
    if (cmd.speed_mps !== undefined && !(cmd.speed_mps > 0)) return 'speed_mps must be positive';
    return null;
  }

  // the camera direction a command asks for: face_target wins over heading_deg (compass degrees, 0 = north)
  function faceOf(cmd) {
    if (cmd.command === 'return_to_patrol') return null;
    if (Array.isArray(cmd.face_target)) return { point: [cmd.face_target[0], cmd.face_target[1]] };
    if (cmd.heading_deg !== undefined) return { heading: (90 - cmd.heading_deg) * D2R };
    return null;
  }

  function newDrone(state) {
    return { mode: 'hold', x: state.x, y: state.y, vx: state.vx, vy: state.vy, heading: Math.atan2(state.vy, state.vx), target: null, cap: null, face: null };
  }

  // How fast the drone wants to go: a goto slows down so it stops on the point; a return chases the moving scripted point.
  function wantedSpeed(d, dist, lim, chase) {
    if (d.mode === 'hold') return 0;
    const vmax = Math.min(lim.max_speed_mps, d.cap || Infinity);
    if (d.mode === 'return') return Math.min(vmax, chase + dist);
    return Math.min(vmax, Math.sqrt(lim.max_accel_mps2 * dist), APPROACH_GAIN * dist); // braking never needs more than the drone can give
  }

  // Advance one step toward goal {x, y}: the course turns at most max_turn, the speed changes at most max_accel.
  function step(d, goal, lim, dt, chase) {
    const dx = goal.x - d.x, dy = goal.y - d.y, dist = Math.hypot(dx, dy);
    const speed = Math.hypot(d.vx, d.vy), want = wantedSpeed(d, dist, lim, chase);
    const aim = Math.atan2(dy, dx);
    const maxTurn = lim.max_turn_dps * D2R * dt;
    const course = Math.atan2(d.vy, d.vx);
    const dir = speed < 0.05 ? aim : course + clamp(wrapPi(aim - course), -maxTurn, maxTurn); // a stopped drone can leave in any direction
    const next = speed + clamp(want - speed, -lim.max_accel_mps2 * dt, lim.max_accel_mps2 * dt);
    d.vx = next * Math.cos(dir); d.vy = next * Math.sin(dir);
    d.x += d.vx * dt; d.y += d.vy * dt;
    turnHeading(d, lim, dt);
  }

  // point the camera where asked; with no request, along the direction of travel; when stopped, keep the last heading
  function turnHeading(d, lim, dt) {
    let want = null;
    if (d.face && d.face.point) want = Math.atan2(d.face.point[1] - d.y, d.face.point[0] - d.x);
    else if (d.face) want = d.face.heading;
    else if (Math.hypot(d.vx, d.vy) > 0.5) want = Math.atan2(d.vy, d.vx);
    if (want === null) return;
    const max = lim.max_turn_dps * D2R * dt;
    d.heading += clamp(wrapPi(want - d.heading), -max, max);
  }

  // true when a goto has reached its point, a hold has stopped, or a return has caught up with the scripted point
  function arrived(d, goal) {
    const dist = Math.hypot(goal.x - d.x, goal.y - d.y), speed = Math.hypot(d.vx, d.vy);
    if (d.mode === 'goto') return dist < 0.1;
    if (d.mode === 'hold') return speed < 0.2;
    return dist < 4;
  }

  const api = { makeHeader, invalid, faceOf, newDrone, step, arrived, COMMANDS, SCHEMA_VERSION };
  global.Drones = api;
  if (typeof module !== 'undefined') module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
