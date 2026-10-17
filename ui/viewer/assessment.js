/* Cooperative review urgency and observation confidence. Inference inputs only:
 * delivered native readings, estimated kinematics and the public C2 position. */
(function(global) {
  'use strict';
  const DEFAULTS={window_s:6,source_age_s:2,sample_s:0.5,review_s:5,deadline_s:10,
    max_sigma_m:25,min_baseline_m:40,min_angle_deg:15};
  class Model {
    constructor(base,config={}) { this.base=base;this.config={...DEFAULTS,...config};this.memory=new Map(); }
    update(t,tr,classification) {
      const c=this.config, sigma=Math.sqrt(Math.max(0,(tr.P[0]+tr.P[5])/2+Math.hypot((tr.P[0]-tr.P[5])/2,tr.P[1])));
      let m=this.memory.get(tr.id);
      if(!m) {m={history:[],last:-Infinity,seen:t,inboundSince:null};this.memory.set(tr.id,m);}
      m.seen=t;
      this.memory.forEach((v,k)=>{if(t-v.seen>30)this.memory.delete(k);});
      const observed=tr.observedT ?? tr.lastUpd;
      const fresh=t-observed<=c.source_age_s && t-observed>=-0.5 && sigma<=c.max_sigma_m && tr.status!=='tentative';
      if(fresh && observed>m.last+1e-8 && (!m.history.length || t-m.history.at(-1).t>=c.sample_s-1e-8)) {
        if(m.history.length && t-m.history.at(-1).t>c.source_age_s) m.history=[];
        m.last=observed;m.history.push({t,x:tr.s[0],y:tr.s[1],vx:tr.s[2],vy:tr.s[3]});
      }
      m.history=m.history.filter((p)=>t-p.t<=c.window_s);
      const byNode=new Map();
      (tr.observations||[]).filter((o)=>t-o.t<=c.source_age_s && t-o.t>=-0.5 && !o.merged).forEach((o)=>{
        const old=byNode.get(o.node);
        if(!old || old.t<o.t || (old.t===o.t && o.m==='rangeaz'))byNode.set(o.node,o);
      });
      const sources=[...byNode.values()];let diverse=false;
      for(let i=0;i<sources.length;i++)for(let j=0;j<i;j++) {
        const a=sources[i],b=sources[j],ax=tr.s[0]-a.sx,ay=tr.s[1]-a.sy,bx=tr.s[0]-b.sx,by=tr.s[1]-b.sy;
        const sine=Math.abs(ax*by-ay*bx)/Math.max(1,Math.hypot(ax,ay)*Math.hypot(bx,by));
        if(Math.hypot(a.sx-b.sx,a.sy-b.sy)>=c.min_baseline_m && sine>=Math.sin(c.min_angle_deg*Math.PI/180))diverse=true;
      }
      const h=m.history,first=h[0],last=h.at(-1),span=last&&first?last.t-first.t:0;
      const dx=tr.s[0]-this.base.x,dy=tr.s[1]-this.base.y,range=Math.hypot(dx,dy),speed=Math.hypot(tr.s[2],tr.s[3]);
      const closure=range>1?-(dx*tr.s[2]+dy*tr.s[3])/range:0;
      const cpa=speed>1?Math.max(0,(dx*tr.s[2]+dy*tr.s[3])/-(speed**2)):Infinity;
      const miss=Math.hypot(dx+tr.s[2]*cpa,dy+tr.s[3]*cpa);
      const inbound=fresh && speed>=2 && closure>=2 && cpa>0 && cpa<=90 && miss<=Math.max(3*sigma,range*0.35);
      if(inbound && m.inboundSince===null)m.inboundSince=t;
      if(!inbound && (!fresh || closure<=0))m.inboundSince=null;
      const closed=first&&last?Math.hypot(first.x-this.base.x,first.y-this.base.y)-Math.hypot(last.x-this.base.x,last.y-this.base.y):0;
      const reliable=fresh && span>=2.5 && closed>=Math.max(5,sigma);
      const confidence=fresh&&sources.length?Math.min(0.97,(0.35+0.35*Number(diverse)+0.15*Number(sources.some((o)=>o.m==='rangeaz'))+
        0.12*Math.min(1,span/3))/(1+(sigma/30)**2)):0;
      const corroborated=diverse && confidence>=0.65 && span>=2.5;
      const since=m.inboundSince===null?tr.born:m.inboundSince,elapsed=Math.max(0,t-since);
      const review={confidence,source_nodes:sources.map((s)=>s.node).sort(),independent_geometry:diverse,
        corroborated,inbound,closing_mps:closure,time_to_closest_s:Number.isFinite(cpa)?cpa:null,
        observed_s:span,sigma_m:sigma,elapsed_s:elapsed,deadline_s:c.deadline_s,
        needs_observer:tr.kind!=='frd' && !corroborated && !['friendly','peaceful','hostile'].includes(classification.cls),
        state:tr.kind==='frd'?'known_fleet':corroborated?'corroborated':elapsed>=c.deadline_s?'insufficient_evidence':elapsed>=c.review_s?'corroborating':'collecting'};
      // An inbound course warrants scrutiny, not a declaration of hostile intent.
      // Independent views corroborate kinematics; they cannot verify allegiance.
      let risk=inbound && reliable && corroborated?Math.min(0.85,0.66+0.15*confidence):null;
      let retained=false;
      if(risk!==null)m.risk={t,strength:risk};
      else if(m.risk && t-m.risk.t<=10) {
        const value=m.risk.strength*Math.exp(-(t-m.risk.t)/30);
        if(value>=0.65){risk=value;retained=true;}
      }
      const canReview=tr.kind!=='frd' && classification.p_friendly<0.7;
      const decision=canReview && risk!==null && ['unknown','peaceful','suspicious'].includes(classification.cls)?
        {...classification,cls:'suspicious',p_hostile:Math.max(classification.p_hostile,risk),class_prob:Math.max(classification.p_hostile,risk)}:classification;
      return {review,decision,reasons:risk!==null&&canReview?[retained?'recent_corroborated_approach':'corroborated_inbound_course']:[]};
    }
  }
  const api={Model,DEFAULTS};global.Assessment=api;
  if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
