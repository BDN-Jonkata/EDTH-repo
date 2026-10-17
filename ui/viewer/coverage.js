/* Sensor-footprint planning and leave-cover checks. No traffic truth enters here. */
(function (global) {
  'use strict';
  const wrap = (a) => Math.atan2(Math.sin(a), Math.cos(a));
  const DEFAULTS = { margin_m: 120, max_radius_m: 320, min_radius_m: 180,
    range_fraction: 0.85, fresh_s: 10, leg_m: 90, replan_s: 3 };
  class Planner {
    constructor(drones, sensors, cells, options = {}) {
      this.drones = drones; this.sensors = sensors; this.cells = cells;
      this.config = Object.assign({}, DEFAULTS, options.config);
      this.base = options.base || { x: 500, y: 500 };
      this.ground = options.ground || [];
      this.sensorAt = options.sensorAt || ((s) => s);
      this.isAlive = options.isAlive || (() => true);
      this.radius = this.config.min_radius_m; this.nextPlan = -Infinity;
      this.distances=cells.map(c=>Math.hypot(c.x-this.base.x,c.y-this.base.y));
      this.indices=this.distances.map((r,i)=>r<=this.radius?i:-1).filter(i=>i>=0);
      this.radiusLimit=Infinity;this.nextAdapt=30;
      this.covered = new Uint8Array(cells.length); this.planned = new Uint8Array(cells.length);
      this.reserved=new Set();
    }
    // RF cannot watch silent objects; it does not certify area coverage.
    modules(node, pose, t) {
      return this.sensors.filter((s) => s.node === node && s.kind !== 'RF').map((s) => {
        const q = this.sensorAt(s, pose, this.base, t);
        return { base:s, range: q.range * this.config.range_fraction, minRange: q.minRange || 0,
          fov: q.fov || s.fov, pointing: q.pointing || s.pointing, pd: q.pd };
      }).filter((s) => s.pd >= 0.15 && s.range > s.minRange);
    }
    inside(c) { return Math.hypot(c.x - this.base.x, c.y - this.base.y) <= this.radius; }
    bound(p) {
      const m = this.config.margin_m, r = Math.max(185, this.radius - 45);
      let x = Math.max(m, Math.min(1000-m, p.x)), y = Math.max(m, Math.min(1000-m, p.y));
      const dx = x-this.base.x, dy = y-this.base.y, distance = Math.hypot(dx,dy);
      if (distance > r) { x = this.base.x + dx*r/distance; y = this.base.y + dy*r/distance; }
      return { x:Math.max(m,Math.min(1000-m,x)), y:Math.max(m,Math.min(1000-m,y)) };
    }
    footprint(pose, modules, exactTime = null) {
      const out = [];
      this.indices.forEach((i) => {
        const c=this.cells[i],dx=c.x-pose.x,dy=c.y-pose.y,r=Math.hypot(dx,dy);
        if(exactTime===null && !modules.some(s=>r>=s.minRange && r<=s.range))return;
        const angle=wrap(Math.atan2(dy,dx)-pose.heading);
        if (modules.some((s) => {
          const q=exactTime===null?s:this.sensorAt(s.base,pose,c,exactTime);
          const range=exactTime===null?q.range:q.range*this.config.range_fraction;
          return q.pd>=0.15 && r>=q.minRange && r<=range && (q.pointing==='omni' || Math.abs(angle)<=q.fov/2);
        })) out.push(i);
      });
      return out;
    }
    nodes(t) {
      return this.drones.filter((d)=>!d.disabled).concat(this.ground.filter((g)=>this.isAlive(g.id,t)));
    }
    refresh(t) {
      let area=0;
      this.nodes(t).forEach((d) => {
        area += Math.max(0,...this.modules(d.id,d,t).map((s)=> Math.PI*s.range*s.range *
          (s.pointing==='omni' ? 1 : s.fov/(2*Math.PI))));
      });
      // Reserve overlap rather than stretching each independent footprint to its limit.
      const desired = Math.min(this.config.max_radius_m, Math.max(this.config.min_radius_m, Math.sqrt(area/Math.PI)*0.78));
      this.capacityRadius=desired;const radius=Math.min(desired,this.radiusLimit);
      if(radius!==this.radius){this.radius=radius;this.indices=this.distances.map((r,i)=>r<=radius?i:-1).filter(i=>i>=0);}
      this.covered.fill(0);
      this.nodes(t).forEach((d)=>this.footprint(d,this.modules(d.id,d,t)).forEach((i)=>this.covered[i]++));
    }
    plan(t) {
      if (t < this.nextPlan) return;
      this.nextPlan=t+this.config.replan_s;
      this.refresh(t); this.planned.fill(0);
      if(t>=this.nextAdapt) {
        this.nextAdapt=t+10;
        const stale=this.cells.filter((c)=>c.last<0 || t-c.last>this.config.fresh_s);
        const freshRadius=Math.min(this.capacityRadius,...stale.map((c)=>Math.hypot(c.x-this.base.x,c.y-this.base.y)-18));
        // Contract to a contiguous freshly watched disk; grow only into cells
        // already observed recently, never by declaring an unseen annulus safe.
        const supported=Math.max(this.config.min_radius_m,freshRadius);
        this.radiusLimit=Math.min(this.capacityRadius,supported<this.radius?supported:this.radius+12.5,supported);
        this.refresh(t);
      }
      this.ground.filter((g)=>this.isAlive(g.id,t)).forEach((g)=>
        this.footprint(g,this.modules(g.id,g,t)).forEach((i)=>this.planned[i]++));
      this.drones.filter((d)=>!d.disabled && d.mode!=='patrol').forEach((d)=>
        this.footprint(d,this.modules(d.id,d,t)).forEach((i)=>this.planned[i]++));
      // Nearest-to-base first keeps the inner watch covered while outer drones return.
      this.drones.filter((d)=>!d.disabled && d.mode==='patrol').slice().sort((a,b)=>
        Math.hypot(a.x-this.base.x,a.y-this.base.y)-Math.hypot(b.x-this.base.x,b.y-this.base.y) || a.id.localeCompare(b.id))
        .forEach((d)=>this.planDrone(d,t));
    }
    planDrone(d,t) {
      d.coverageHold=this.reserved.has(d.id);
      if(d.coverageHold) {
        d.goal={x:d.x,y:d.y};d.desiredHeading=d.heading;
        this.footprint(d,this.modules(d.id,d,t)).forEach(i=>this.planned[i]++);return;
      }
      const modules=this.modules(d.id,d,t), candidates=[this.bound(d),this.bound(d.goal||d),this.bound(this.base)];
      const urgent=this.cells.filter((c,i)=>this.inside(c) && !this.planned[i] && (c.last<0 || t-c.last>this.config.fresh_s))
        .sort((a,b)=>a.last-b.last || Math.hypot(a.x-d.x,a.y-d.y)-Math.hypot(b.x-d.x,b.y-d.y)).slice(0,3);
      for (const distance of [45,this.config.leg_m]) for(let i=0;i<8;i++)
        candidates.push(this.bound({x:d.x+distance*Math.cos(i*Math.PI/4),y:d.y+distance*Math.sin(i*Math.PI/4)}));
      let best=null;
      for(const p of candidates) {
        if(this.drones.some((q)=>q!==d && !q.disabled && (
          Math.hypot(p.x-q.x,p.y-q.y)<150 || (q.goal && Math.hypot(p.x-q.goal.x,p.y-q.goal.y)<150)))) continue;
        const headings=[d.heading,...Array.from({length:8},(_,k)=>k*Math.PI/4),...urgent.map((c)=>Math.atan2(c.y-p.y,c.x-p.x))];
        for(const heading of headings) {
          const footprint=this.footprint({...p,heading},modules);
          let score=0;
          footprint.forEach((i)=>{
            const age=this.cells[i].last<0 ? 30 : Math.max(0,t-this.cells[i].last);
            const priority=age>this.config.fresh_s ? 8+Math.min(30,age-this.config.fresh_s) : 0.2+age/this.config.fresh_s;
            score += priority * (this.planned[i]===0 ? 1 : this.planned[i]===1 ? 0.15 : 0);
          });
          const travel=Math.hypot(p.x-d.x,p.y-d.y), turn=Math.abs(wrap(heading-d.heading));
          score -= travel*0.045 + turn*2;
          if(d.goal && Math.hypot(p.x-d.goal.x,p.y-d.goal.y)<10 && !d.blocked) score+=3;
          if(!best || score>best.score) best={...p,heading,footprint,score};
        }
      }
      if(!best) {
        // A reserved neighbour is never a reason to chase an uncovered border cell.
        const p=this.bound(d); d.goal=p; d.desiredHeading=Math.atan2(this.base.y-d.y,this.base.x-d.x); return;
      }
      d.goal={x:best.x,y:best.y}; d.desiredHeading=best.heading; d.cell=null; d.assignedAt=t;
      best.footprint.forEach((i)=>this.planned[i]++);
    }
    departure(drone,goal,heading,t) {
      this.refresh(t);
      const others=new Uint8Array(this.cells.length),byNode=new Map();
      this.nodes(t).filter((d)=>d.id!==drone.id &&
        (!d.mode || ['patrol','hold'].includes(d.mode)) && Math.hypot(d.vx||0,d.vy||0)<0.5 &&
        Math.abs(wrap((d.goalHeading??d.heading)-d.heading))<0.05).forEach((d)=>{
        const indices=this.footprint(d,this.modules(d.id,d,t),t);byNode.set(d.id,new Set(indices));
        indices.forEach((i)=>others[i]++);
      });
      const own=this.footprint(drone,this.modules(drone.id,drone,t),t);
      const kept=new Set(this.footprint({...goal,heading},this.modules(drone.id,goal,t),t));
      const backups=new Set();
      let lost=0;
      // Sample the whole route, including yaw slew: a safe endpoint alone is insufficient.
      const travel=Math.hypot(goal.x-drone.x,goal.y-drone.y);
      const seconds=Math.max(travel/Math.max(1,drone.speed||6),Math.abs(wrap(heading-drone.heading))/(Math.PI/9));
      const samples=Math.max(2,Math.ceil(seconds));
      for(let step=1;step<=samples;step++) {
        const u=step/samples, elapsed=seconds*u;
        const pose={x:drone.x+(goal.x-drone.x)*u,y:drone.y+(goal.y-drone.y)*u,
          heading:drone.heading+Math.sign(wrap(heading-drone.heading))*Math.min(Math.abs(wrap(heading-drone.heading)),elapsed*Math.PI/9)};
        const route=new Set(this.footprint(pose,this.modules(drone.id,pose,t),t));
        const missing=own.reduce((n,i)=>{
          const requiresBackup=!route.has(i)||!kept.has(i);
          if(requiresBackup)byNode.forEach((indices,id)=>{if(indices.has(i))backups.add(id);});
          return n+Number(!others[i] && requiresBackup);
        },0);
        lost=Math.max(lost,missing);
      }
      const bounded=this.bound(goal), inside=Math.hypot(bounded.x-goal.x,bounded.y-goal.y)<1;
      return { allowed:inside && lost===0, lostCells:lost, backups:[...backups],reason:!inside?'outside_watch_area':lost?'coverage_gap':null };
    }
    stats(t) {
      this.refresh(t);
      const indices=this.cells.map((c,i)=>this.inside(c)?i:-1).filter((i)=>i>=0);
      const fresh=indices.filter((i)=>this.cells[i].last>=0 && t-this.cells[i].last<=this.config.fresh_s).length;
      return {radius_m:this.radius,total:indices.length,fresh,blind:indices.length-fresh,
        visible:indices.filter((i)=>this.covered[i]>0).length, overlap:indices.filter((i)=>this.covered[i]>1).length,
        fresh_s:this.config.fresh_s,area_km2:indices.length*625/1e6};
    }
  }
  const api={Planner,DEFAULTS}; global.Coverage=api;
  if(typeof module!=='undefined') module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
