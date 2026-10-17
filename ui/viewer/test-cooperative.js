const test=require('node:test');
const assert=require('node:assert/strict');
const {Model}=require('./assessment.js');
const {Planner}=require('./coverage.js');
const {Controller:Missions}=require('./missions.js');
const {Controller:Investigator}=require('./investigations.js');
const Weather=require('./weather.js');
const Catalog=require('./catalog.js');
const Sim=require('./sim.js');
const original={cls:'unknown',p_friendly:0.18,p_hostile:0.5,class_prob:0.5};
function contact() {return {id:'opaque',kind:'trk',born:0,status:'confirmed',s:[750,500,-10,0],P:[9,0,0,0,0,9],observations:[]};}
function reading(node,t,sx,sy,changes={}) {return {node,t,sx,sy,m:'rangeaz',merged:false,...changes};}
function feed(model,tr,t,observations,decision=original) {
  tr.s[0]=750-10*t;tr.observedT=t;tr.lastUpd=t;tr.observations=observations;
  return model.update(t,tr,decision);
}
test('independent ground/drone views assess an inbound contact within five seconds, without inventing hostility',()=>{
  const m=new Model({x:500,y:500}),tr=contact();let first=null,last;
  for(let k=0;k<=12;k++) {const t=k/2;last=feed(m,tr,t,[reading('GS1',t,500,400),reading('F1',t,600,600)]);
    if(last.decision.cls==='suspicious' && first===null)first=t;}
  assert.ok(first<=5);assert.ok(last.review.corroborated);assert.ok(last.review.confidence>.8);
  assert.equal(last.decision.cls,'suspicious');assert.ok(last.decision.p_hostile<.9);
});
test('many sensors from one node cannot manufacture independent confirmation',()=>{
  const m=new Model({x:500,y:500}),tr=contact();let r;
  for(let k=0;k<=24;k++)r=feed(m,tr,k/2,Array.from({length:8},()=>reading('F1',k/2,600,600)));
  assert.equal(r.decision.cls,'unknown');assert.equal(r.review.corroborated,false);
  assert.equal(r.review.state,'insufficient_evidence');assert.deepEqual(r.review.source_nodes,['F1']);
});
test('collinear observers and merged radar returns cannot create corroboration',()=>{
  for(const merged of [false,true]) {const m=new Model({x:500,y:500}),tr=contact();let r;
    for(let k=0;k<=12;k++)r=feed(m,tr,k/2,[reading('A',k/2,400,500,{merged}),reading('B',k/2,500,500,{merged})]);
    assert.equal(r.review.corroborated,false);assert.equal(r.decision.cls,'unknown');}
});
test('coasting, replayed observations and large covariance cannot raise confidence',()=>{
  for(const variant of ['replay','stale','uncertain']) {
    const m=new Model({x:500,y:500}),tr=contact();let r;
    for(let k=0;k<=12;k++){const t=k/2;tr.s[0]=750-10*t;tr.observedT=variant==='replay'?0:variant==='stale'?t-4:t;
      if(variant==='uncertain')tr.P[0]=tr.P[5]=2500;
      tr.observations=[reading('A',0,500,400),reading('B',0,600,600)];r=m.update(t,tr,original);}
    assert.equal(r.decision.cls,'unknown');assert.equal(r.review.corroborated,false);
  }
});
test('verified fleet identity and an outbound course do not become inbound suspicion',()=>{
  for(const own of [false,true]) {
    const m=new Model({x:500,y:500}),tr=contact();if(own)tr.kind='frd';let r;
    for(let k=0;k<=12;k++){const t=k/2;tr.s=[750+10*t,500,10,0];tr.observedT=t;
      tr.observations=[reading('A',t,500,400),reading('B',t,600,600)];r=m.update(t,tr,original);}
    assert.equal(r.decision.cls,'unknown');if(own)assert.equal(r.review.needs_observer,false);
  }
});
const omni=(node,range=200)=>({node,kind:'RAD',range,minRange:0,pointing:'omni',fov:Math.PI*2,pd:1,every:1});
const drone=(id,x,y)=>({id,x,y,heading:0,speed:10,v:10,mode:'patrol'});
test('investigation departure is blocked for sole coverage and allowed with a redundant ground watch',()=>{
  const a=drone('A',400,500),ground=drone('GS',350,500),cells=[350,450,550].map(x=>({x,y:500,last:0}));
  const alone=new Planner([a],[omni('A',200)],cells,{base:{x:500,y:500}});
  assert.equal(alone.departure(a,{x:600,y:500},0,0).allowed,false);
  const redundant=new Planner([a],[omni('A',200),omni('GS',300)],cells,{base:{x:500,y:500},ground:[ground]});
  assert.equal(redundant.departure(a,{x:600,y:500},0,0).allowed,true);
});
test('a dispatched observer reserves its ground backup and releases the task if that backup fails',()=>{
  const ground={...drone('GS',350,500),goalHeading:0};
  const missions=new Missions([drone('A',400,500)],[omni('A',200),omni('GS',300)],.1,()=>{},
    {requireInvestigation:true,geometry:()=>({distance:80,maximum:150}),
      coverage:{base:{x:500,y:500},ground:[ground],isAlive:(_,t)=>t<.5}});
  const tr={...contact(),s:[600,500,-10,0],srcs:{},lastUpd:0,investigation:{}};
  missions.update(0,[tr]);assert.equal(missions.drones[0].mode,'follow');
  assert.ok(missions.coverage.reserved.has('GS'));
  tr.lastUpd=1;missions.update(1,[tr]);assert.equal(missions.drones[0].mode,'patrol');
  assert.equal(missions.drones[0].target,null);
});
test('ground sensing fills the coverage grid while RF does not hide silent-target blind spots',()=>{
  const missions=new Missions([drone('A',500,500)],[omni('GS'),{...omni('A',1000),kind:'RF'}],.1,()=>{},
    {coverage:{base:{x:500,y:500},ground:[drone('GS',500,500)]}});
  missions.observe(0,0);
  assert.equal(missions.cells.find(c=>c.x===537.5 && c.y===512.5).last,0);
  assert.equal(missions.cells.find(c=>c.x===937.5 && c.y===512.5).last,-1);
});
test('compact patrol planning keeps destinations inside the map instead of chasing border cells',()=>{
  const fleet=[drone('A',30,300),drone('B',970,700),drone('C',500,30)];
  const missions=new Missions(fleet,fleet.map(d=>omni(d.id)),.1,()=>{},{coverage:{base:{x:500,y:500}}});
  missions.update(0,[]);
  for(const d of missions.drones){assert.ok(d.goal.x>=120&&d.goal.x<=880);assert.ok(d.goal.y>=120&&d.goal.y<=880);}
});
test('watch contracts when the fresh sensor footprints cannot sustain its outer ring',()=>{
  const cells=Array.from({length:40*40},(_,i)=>({x:(i%40+.5)*25,y:(Math.floor(i/40)+.5)*25,last:Math.hypot(i%40*25+12.5-500,Math.floor(i/40)*25+12.5-500)<200?30:-1}));
  const a=drone('A',500,500),p=new Planner([a],[omni('A',400)],cells,{base:{x:500,y:500}});
  p.plan(0);const before=p.radius;p.plan(30);assert.ok(p.radius<before);assert.ok(p.radius>=180);
  assert.ok(p.stats(30).blind===0);
});
test('cooperative review can request a different observer while the contact is still unknown',()=>{
  const mod=Catalog.modules.find(m=>m.id==='eo_visible_mini4'),sm=mod.sim;
  const sensors=['F1','F2'].map(node=>({...omni(node,150),mod,sm,module:mod.id,kind:'EO'}));
  const inv=new Investigator(sensors,['F1','F2'],Weather.providerFor({},'clear',null).provider,s=>s,()=>{},{},(_,t)=>t,{cooperative:true});
  const tr={...contact(),cls:'unknown',s:[700,500,-10,0],lastUpd:2,classification:original,srcs:{'F1 EO':2},
    assessment:{inbound:true,needs_observer:true,source_nodes:['F1']}};
  inv.update(2,[tr]);assert.equal(inv.requests.length,1);
  assert.equal(inv.geometry(tr,drone('F1',600,500),2),null);
  assert.ok(inv.geometry(tr,drone('F2',650,600),2));
});
test('a fast ground cue gets a short chance before an aircraft is requested',()=>{
  const mod=Catalog.modules.find(m=>m.id==='eo_visible_mini4'),sm=mod.sim;
  const sensors=[{...omni('F1',150),mod,sm,module:mod.id,kind:'EO'}];
  const inv=new Investigator(sensors,['F1'],Weather.providerFor({},'clear',null).provider,s=>s,()=>{},{},(_,t)=>t,
    {cooperative:true,cueGround:()=>['GS1']});
  const tr={...contact(),cls:'unknown',s:[700,500,-10,0],classification:original,srcs:{},groundWait:1.5,
    assessment:{inbound:true,needs_observer:true,source_nodes:[]}};
  inv.update(2,[tr]);assert.equal(inv.requests.length,0);
  inv.update(3.6,[tr]);assert.equal(inv.requests.length,1);
});
test('native noisy observations corroborate and review an inbound contact within ten seconds',(testContext)=>{
  const sc=JSON.parse(JSON.stringify(require('./scenarios.js').challenge));
  sc.duration_s=15;sc.config.targets.crossing.enabled=false;
  sc.ground[0].platform='gs_radar_rf';sc.ground[0].position=[400,350];sc.ground[0].heading_deg=0;
  sc.ground[0].sensors=sc.ground[1].sensors;
  sc.ground[1].position=[650,350];sc.ground[1].heading_deg=90;
  sc.targets=[{...sc.targets[0],wobble_m:0,waypoints:[[0,650,500],[15,530,410]],signature:{radar:1,rf:1,eo:1,thermal:1,acoustic:1}}];
  const r=Sim.run({scenario:sc,seed:sc.seed,mode:'realistic',weather:'clear',loss:20,delayMs:200,driftMs:200});
  let firstSeen=null,decision=null;
  r.frames.forEach(f=>{
    const truth=f.truth.find(o=>o.id===sc.targets[0].id);
    const track=f.tracks.filter(tr=>!tr.id.startsWith('F')&&Math.hypot(tr.x-truth.x,tr.y-truth.y)<30)
      .sort((a,b)=>Math.hypot(a.x-truth.x,a.y-truth.y)-Math.hypot(b.x-truth.x,b.y-truth.y))[0];
    if(!track)return;if(firstSeen===null)firstSeen=f.t;
    if(!decision&&track.cls==='suspicious'&&track.assessment.corroborated)decision={t:f.t,nodes:track.assessment.source_nodes};
  });
  assert.ok(decision,JSON.stringify({firstSeen,tracks:r.frames.at(-1).tracks}));
  assert.ok(decision.t-firstSeen<=10,JSON.stringify({firstSeen,decision}));
  assert.ok(decision.nodes.some(n=>n.startsWith('GS')));
  assert.equal(r.summary.ffa,0);
  testContext.diagnostic(JSON.stringify({firstObserved_s:firstSeen,reviewed_s:decision.t,elapsed_s:decision.t-firstSeen,sources:decision.nodes}));
});
