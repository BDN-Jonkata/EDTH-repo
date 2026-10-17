// Native sensor output regressions. node ui/viewer/test-sensors.js
const test = require('node:test');
const assert = require('node:assert/strict');
const Sim = require('./sim.js');
const challenge = require('./scenarios.js').challenge;
const wrap = a=>Math.atan2(Math.sin(a),Math.cos(a));

function closeRadarPair(secondY) {
  const sc = JSON.parse(JSON.stringify(challenge));
  sc.duration_s=1;sc.config.targets.crossing.enabled=false;
  sc.sensor_set.enabled_kinds=['radar'];
  sc.friendlies.forEach(f=>{f.platform='mini4pro';});
  sc.targets=sc.targets.map((h,i)=>({...h,wobble_m:0,signature:{radar:100},
    waypoints:[[0,400,460+(i?secondY:.1)],[1,400,460+(i?secondY:.1)]]}));
  const r=Sim.run({scenario:sc,seed:sc.seed,mode:'optimistic',weather:'clear'});
  return r.frames.flatMap(f=>f.meas.filter(m=>m.node==='GS2'&&m.k==='RAD'&&m.merged));
}

test('radar resolution merges close targets across the azimuth seam and keeps their westward bearing', () => {
  const sameSide=closeRadarPair(.2),acrossSeam=closeRadarPair(-.1);
  assert.ok(sameSide.length>=2,'ordinary close pair must be unresolved repeatedly');
  assert.ok(acrossSeam.length>=2,'crossing -pi/pi must not improve radar resolution');
  for(const m of acrossSeam) {
    assert.ok(Math.abs(wrap(m.b-Math.PI))<.2,'circular mean must point west');
    assert.ok(Math.abs(m.r-255)<20,'merged range stays at the actual resolution cell');
  }
});
