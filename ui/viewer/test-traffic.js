// Physical traffic fixtures: the estimator only sees their sensor measurements.
const test = require('node:test');
const assert = require('node:assert/strict');
const Traffic = require('./traffic.js');
const dt = 0.1;
const specs = [{ id: 'contact', ally: 'own', mode: 'intercept', start_s: 2 }];
const own = (_, t) => ({ x: 200+6*t, y: 500+20*Math.sin(t/6), vx: 6, vy: 20/6*Math.cos(t/6), heading: 0 });
const actor = (s = specs) => new Traffic(s, [{ id: 'contact' }], [{ id: 'own' }], dt);

test('traffic appears at its configured start and interpolates recorded flight', () => {
  const a = actor();
  for (let k=0; k<=40; k++) a.step(k*dt, own);
  assert.equal(a.state('contact', 1.9), null);
  const p=a.state('contact', 3), q=a.state('contact', 3.1), mid=a.state('contact', 3.05);
  assert.ok(Math.abs(mid.x-(p.x+q.x)/2)<1e-9);
  assert.ok(Math.abs(mid.y-(p.y+q.y)/2)<1e-9);
});

test('actor motion keeps its speed and acceleration bounds without boundary teleports', () => {
  const a = actor();
  for (let k=0; k<=1800; k++) a.step(k*dt, own);
  const h=a.actors.get('contact').history;
  h.forEach((s,i) => {
    assert.ok(Math.hypot(s.vx,s.vy)<=18+1e-9);
    if (!i) return;
    const p=h[i-1];
    assert.ok(Math.hypot(s.vx-p.vx,s.vy-p.vy)<=3*dt+1e-9);
    assert.ok(Math.abs(s.x-p.x-s.vx*dt)<1e-9);
    assert.ok(Math.abs(s.y-p.y-s.vy*dt)<1e-9);
  });
  assert.equal(a.state('contact', 180), null, 'exited actors leave the visible area');
});

test('future ally motion cannot change already flown actor positions', () => {
  const a=actor(), b=actor();
  for (let k=0; k<=120; k++) {
    const t=k*dt;
    a.step(t,own);
    b.step(t,(id,at) => at<10 ? own(id,at) : {x:900,y:200,vx:0,vy:-8,heading:-Math.PI/2});
  }
  for(let k=20; k<100; k++) assert.deepEqual(a.state('contact',k*dt),b.state('contact',k*dt));
  assert.notDeepEqual(a.state('contact',12),b.state('contact',12));
});

test('invalid or duplicate actor definitions are rejected', () => {
  for (const change of [{id:'missing'},{ally:'missing'},{mode:'bad'},{start_s:-1},{start_s:NaN}])
    assert.throws(()=>actor([{...specs[0],...change}]), /Invalid traffic behavior/);
  assert.throws(()=>actor([specs[0],specs[0]]), /Invalid traffic behavior/);
});
