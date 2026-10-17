// Truth is used only by the scorer, after tracking and assessment.
// node ui/viewer/test-metrics.js
const test = require('node:test');
const assert = require('node:assert/strict');
const Metrics = require('./metrics.js');
const Sim = require('./sim.js');
const challenge = require('./scenarios.js').challenge;
const clone = (x) => JSON.parse(JSON.stringify(x));
const close = (a,b) => assert.ok(Math.abs(a-b) <= 1e-9*Math.max(1,Math.abs(b)), a+' != '+b);
const object = (id,x,y=0,kind='hostile') => ({id,x,y,vx:1,vy:0,kind});

test('gated global assignment preserves two valid matches that greedy pairing loses', () => {
  const pairs = Metrics.assign([object('A',0),object('B',2)], [object('H1',1),object('H2',-2)], 3);
  assert.deepEqual(pairs.map(p=>[p.track.id,p.truth.id]), [['B','H1'],['A','H2']]);
  assert.equal(Metrics.assign([object('A',0)],[object('H1',3)],3).length,0);
  assert.deepEqual(Metrics.assign([], [object('H',0)]),[]);
});

test('all object kinds compete geometrically before threat-target metrics are selected', () => {
  const truth=[object('H',11),object('F',10,0,'friendly'),object('N',20,0,'benign'),object('B',30,0,'clutter')];
  const tracks=[object('U1',10),object('U2',11),object('U3',20),object('U4',30)];
  const pairs=Metrics.assign(tracks,truth);
  assert.deepEqual(pairs.map(p=>[p.track.id,p.truth.id]),[['U4','B'],['U1','F'],['U2','H'],['U3','N']]);
  assert.deepEqual(pairs.filter(p=>p.truth.kind==='hostile').map(p=>p.track.id),['U2']);
  const flipped=truth.map(t=>({...t,kind:t.kind==='hostile'?'benign':'hostile'}));
  assert.deepEqual(Metrics.assign(tracks,flipped).map(p=>[p.track.id,p.truth.id]),pairs.map(p=>[p.track.id,p.truth.id]));
});

test('assignment has no continuity preference that could hide crossing identity changes', () => {
  const truth=[object('H1',0),object('H2',10)];
  const before=Metrics.assign([object('U1',0),object('U2',10)],truth);
  const after=Metrics.assign([object('U1',10),object('U2',0)],truth);
  assert.deepEqual(before.map(p=>[p.truth.id,p.track.id]),[['H1','U1'],['H2','U2']]);
  assert.deepEqual(after.map(p=>[p.truth.id,p.track.id]),[['H1','U2'],['H2','U1']]);
});

test('velocity and wrapped moving-target headings are measured; hover has no heading', () => {
  const vel=a=>({vx:2*Math.cos(a*Math.PI/180),vy:2*Math.sin(a*Math.PI/180)});
  const track={...object('U',0),...vel(359)}, truth={...object('H',3,4),...vel(1)};
  const errors=Metrics.errors([{track,truth,distance:5}]);
  close(errors.positionSq,25);close(errors.headingSq,4);assert.equal(errors.headingN,1);
  close(Metrics.aggregate([errors]).velocityRmse,4*Math.sin(Math.PI/180));
  const still=Metrics.errors([{track:{...track,vx:0,vy:0},truth,distance:5}]);
  assert.equal(Metrics.aggregate([still]).headingRmseDeg,null);
});

test('rolling RMSE weights each matched pair and reports missing evidence as null', () => {
  const one={positionSq:100,velocitySq:4,headingSq:400,headingN:1,n:1};
  const two={positionSq:0,velocitySq:0,headingSq:0,headingN:2,n:2};
  const result=Metrics.aggregate([one,two]);
  close(result.rmse,Math.sqrt(100/3));close(result.velocityRmse,Math.sqrt(4/3));
  close(result.headingRmseDeg,Math.sqrt(400/3));assert.equal(result.matchedSamples,3);
  assert.deepEqual(Metrics.aggregate([]),{rmse:null,velocityRmse:null,headingRmseDeg:null,matchedSamples:0});
});

const scenario=clone(challenge);scenario.duration_s=70;
const params={scenario,seed:challenge.seed,mode:'optimistic',weather:'clear',loss:0,delayMs:0,driftMs:0};
const demo=Sim.run(params);

test('challenge tracking quality remains measurable when behavior cannot establish hostile intent', () => {
  assert.equal(demo.summary.countErr,2,'strict hostile count must remain honest');
  assert.equal(demo.summary.exactCountFraction,0);
  assert.ok(demo.summary.matchedSamples>0);
  assert.ok(demo.summary.trackedFraction>0&&demo.summary.trackedFraction<=1);
  assert.ok(Number.isFinite(demo.summary.rmse));
  assert.ok(Number.isFinite(demo.summary.velocityRmse));
  assert.ok(Number.isFinite(demo.summary.headingRmseDeg));
  const crossing=demo.frames[Math.round(challenge.config.targets.crossing.t/demo.DT)];
  assert.equal(crossing.m.est,0);
  assert.ok(crossing.m.tracked>0,'unknown/peaceful contacts still carry position and identity');
  assert.equal(crossing.m.matchedSamples,crossing.m.tracked);
});

test('native-run summary and ten-second RMSE equal the errors of every geometric match', () => {
  let sq=0,matched=0,targets=0;
  const squaredError=(f,id,target)=>{
    const track=f.tracks.find(t=>t.id===id),truth=f.truth.find(t=>t.id===target);
    return (track.x-truth.x)**2+(track.y-truth.y)**2;
  };
  demo.frames.forEach((frame,k)=>{
    const recent=demo.frames.slice(Math.max(0,k-99),k+1);
    let rollingSq=0,rollingN=0;
    recent.forEach(f=>f.match.forEach(([id,target])=>{rollingSq+=squaredError(f,id,target);rollingN++;}));
    if(rollingN)close(frame.m.rmse10,Math.sqrt(rollingSq/rollingN));
    else assert.equal(frame.m.rmse10,null);
    if(frame.t>=demo.EVAL[0]&&frame.t<=demo.EVAL[1]){
      frame.match.forEach(([id,target])=>{sq+=squaredError(frame,id,target);matched++;});
      targets+=frame.m.tru;
    }
  });
  close(demo.summary.rmse,Math.sqrt(sq/matched));
  close(demo.summary.trackedFraction,matched/targets);
  assert.equal(demo.summary.matchedSamples,matched);assert.equal(demo.summary.targetSamples,targets);
});

test('lite scoring exactly matches full playback scoring', () => {
  assert.deepEqual(Sim.run(params,{lite:true}).summary,demo.summary);
});

test('seeing no target cannot pass quality metrics with zero reported identity swaps', () => {
  const blind=clone(challenge);blind.duration_s=55;blind.sensor_set.enabled_kinds=[];
  const result=Sim.run({...params,scenario:blind},{lite:true});
  assert.equal(result.summary.swaps,0);
  assert.equal(result.summary.trackedFraction,0);assert.equal(result.summary.matchedSamples,0);
  assert.ok(result.summary.targetSamples>0);
  assert.equal(result.summary.rmse,null);assert.equal(result.summary.velocityRmse,null);
  assert.equal(result.summary.headingRmseDeg,null);assert.equal(result.summary.exactCountFraction,0);
});
