/* In-process mock of the existing InvestigationRequest/Status contract.
 * It reads estimated tracks and catalog/weather capabilities, never truth. */
(function (global) {
  'use strict';
  const W = typeof window !== 'undefined' ? window.Weather : require('./weather.js');
  const M = typeof window !== 'undefined' ? window.Messages : require('./messages.js');
  const SAFE_STANDOFF_M = 40;
  function standoff(module, effects) {
    const sm = module.sim, q = W.sensorQuality(module, effects), maximum = sm.ident_range_m * q.range;
    return { max_range_m: maximum, recommended_m: Math.min(maximum, Math.max(0.7 * maximum, sm.min_range_m)),
      confidence: Math.min(1, q.range * q.pd), feasible: maximum >= Math.max(20, sm.min_range_m) };
  }
  class Controller {
    constructor(sensors, fleetIds, weather, sensorAt, emit, seqs, clock = (_, t) => t, options = {}) {
      this.sensors = sensors.filter((s) => fleetIds.includes(s.node));
      this.weather = weather; this.sensorAt = sensorAt; this.emit = emit || (() => {}); this.seqs = seqs;
      this.clock = clock;
      this.options=options;
      this.since = new Map(); this.blocked = new Map(); this.active = new Map(); this.requests = []; this.statuses = [];
    }
    message(source, type, body, t) {
      const m = Object.assign({ type, header: M.makeHeader(this.seqs, source, this.clock(source, t)) }, body);
      this.emit(m); return m;
    }
    update(t, tracks) {
      const live = new Set(tracks);
      const needsReview=(tr)=>tr.cls==='suspicious' || (this.options.cooperative && tr.kind!=='frd' && tr.cls==='unknown' &&
        tr.status!=='tentative' && tr.assessment?.needs_observer && t-tr.born>=(tr.assessment.inbound?2:5));
      this.active.forEach((task, tr) => {
        if (!live.has(tr) || !needsReview(tr) || (this.options.cooperative && tr.assessment?.corroborated &&
            tr.behavior?.reasons?.includes('corroborated_inbound_course')))
          this.finish(tr, task, t, live.has(tr) ? 'done' : 'aborted');
      });
      this.since.forEach((_, tr) => { if (!live.has(tr) || !needsReview(tr)) this.since.delete(tr); });
      this.blocked.forEach((until, tr) => { if (!live.has(tr) && t >= until) this.blocked.delete(tr); });
      tracks.slice().sort((a,b)=>Number(!!b.assessment?.inbound)-Number(!!a.assessment?.inbound) || a.born-b.born).forEach((tr) => {
        tr.investigation = null;
        if (!needsReview(tr) || tr.status === 'tentative') return;
        if(this.options.cooperative && tr.assessment?.needs_observer && this.options.cueGround) {
          tr.assessment.ground_cues=this.options.cueGround(tr,t);
          if(tr.assessment.ground_cues.length && tr.groundRequested===undefined)tr.groundRequested=t;
          if(tr.assessment.ground_cues.length && t-tr.groundRequested<(tr.groundWait??1.5))return;
        }
        if(this.options.cooperative && tr.assessment?.corroborated && tr.behavior?.reasons?.includes('corroborated_inbound_course'))return;
        if (!this.since.has(tr)) this.since.set(tr, t);
        const wait=this.options.cooperative && tr.assessment?.inbound?0:3;
        if (t - this.since.get(tr) < wait - 1e-8) return;
        let task = this.active.get(tr);
        if (!task) {
          if (t < (this.blocked.get(tr) ?? -1)) return;
          if(this.options.cooperative && this.active.size>=2)return;
          const byModule = {}, effects = W.activeEffects(this.weather.at([tr.s[0], tr.s[1], 0], t));
          this.sensors.forEach((s) => { byModule[s.module] = standoff(s.mod, effects); });
          const values = Object.values(byModule).sort((a, b) => Number(b.feasible) - Number(a.feasible) || b.max_range_m - a.max_range_m);
          const best = values[0] || { recommended_m: 0, confidence: 0, feasible: false };
          const sigma2 = Math.max(tr.P[0], tr.P[5]);
          const request = this.message('estimator', 'investigation_request', {
            track_id: tr.id, position: [tr.s[0], tr.s[1], 0], covariance: [[tr.P[0], tr.P[1], 0], [tr.P[1], tr.P[5], 0], [0, 0, sigma2]],
            class_prob: tr.classification.class_prob, priority: Math.round((1 - tr.classification.p_friendly) * 1000) / 1000,
            t_requested: t, standoff_m: best.recommended_m, standoff_by_module: byModule,
            weather_confidence: best.confidence, feasible: best.feasible,
          }, t);
          this.requests.push(request); this.blocked.set(tr, t + (this.options.cooperative ? 3 : 30));
          if (!best.feasible) return;
          task = { request, drone: null, state: null, updated: -Infinity };
          this.active.set(tr, task);
        }
        tr.investigation = task;
      });
    }
    geometry(tr, drone, t) {
      const task = tr.investigation;
      if (!task) return null;
      // The ally being approached keeps its mission. A different observer must
      // identify the contact; turning the approached ally into its follower
      // would reverse the encounter and compromise the motion evidence.
      const references = [tr.behavior?.features?.reference_track_id, tr.behavior?.retained_risk?.features?.reference_track_id];
      if (references.includes(drone.id)) return null;
      if(this.options.cooperative && tr.assessment?.needs_observer && task.drone!==drone.id &&
          tr.assessment.source_nodes.includes(drone.id))return null;
      // Re-evaluate along the actual line of sight, including local weather events.
      const choices = this.sensors.filter((s) => s.node === drone.id).map((s) => {
        if (s.kind === 'RF' && !Object.entries(tr.srcs).some(([key, seen]) => key.endsWith(' RF') && t - seen <= 3))
          return { feasible: false }; // RF can identify only an observed emitter, never a silent object by assumption
        const q = this.sensorAt(s, drone, { x: tr.s[0], y: tr.s[1] }, t);
        const corroborating=this.options.cooperative && tr.assessment?.needs_observer;
        const maximum = corroborating ? q.range*0.85 : s.sm.ident_range_m * q.range / s.sm.range_m;
        const current=Math.hypot(tr.s[0]-drone.x,tr.s[1]-drone.y);
        const distance = Math.max(SAFE_STANDOFF_M, s.minRange, Math.min(corroborating?current:Infinity,0.7 * maximum));
        return { sensor: s, distance, maximum, corroborating, feasible: q.pd > 0 && maximum >= distance };
      }).filter((q) => q.feasible).sort((a, b) => b.maximum - a.maximum);
      return choices[0] || null;
    }
    sync(t, drones) {
      this.active.forEach((task, tr) => {
        const drone = drones.find((d) => d.target === tr && ['follow', 'search'].includes(d.mode));
        if (!drone) {
          if (task.drone) this.finish(tr, task, t, 'aborted');
          else if (t - task.request.t_requested >= 3) { this.active.delete(tr); tr.investigation = null; }
          return;
        }
        if (task.drone !== drone.id) {
          if (task.drone) this.status(tr, task, 'aborted', t);
          task.drone = drone.id; this.status(tr, task, 'assigned', t);
        }
        const q = this.geometry(tr, drone, t), r = Math.hypot(tr.s[0] - drone.x, tr.s[1] - drone.y);
        const state = drone.mode === 'follow' && q && r >= SAFE_STANDOFF_M && r <= q.maximum ? 'on_station' : 'en_route';
        if (state !== task.state && (t - task.updated >= 2 || task.state === 'assigned')) this.status(tr, task, state, t);
      });
    }
    status(tr, task, state, t) {
      task.state = state; task.updated = t;
      this.statuses.push(this.message(task.drone, 'investigation_status', { track_id: tr.id, drone_id: task.drone, state }, t));
    }
    finish(tr, task, t, state) {
      if (task.drone) this.status(tr, task, state, t);
      this.active.delete(tr); tr.investigation = null; this.blocked.set(tr, t + (this.options.cooperative ? 3 : 30));
    }
  }
  global.Investigations = { Controller, standoff, SAFE_STANDOFF_M };
  if (typeof module !== 'undefined') module.exports = global.Investigations;
})(typeof window !== 'undefined' ? window : globalThis);
