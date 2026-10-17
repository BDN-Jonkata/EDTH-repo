/* Fictional village scenery in the map's 1 km square (SVG north is up).
 * Built once, independently of scenarios and track assessments. */
(function (global) {
  'use strict';
  const roads = [
    { name: 'Main Road', width: 13, points: [[0,610],[160,590],[320,548],[480,510],[528,500],[710,474],[860,447],[1000,420]] },
    { name: 'North Road', width: 11, points: [[505,0],[510,170],[516,300],[522,410],[528,500],[538,660],[546,820],[560,1000]] },
    { name: 'North Lane', width: 7, points: [[320,548],[298,448],[300,335],[410,294],[516,300]] },
    { name: 'Church Lane', width: 7, points: [[522,410],[655,384],[742,325],[712,225],[623,192],[510,170]] },
    { name: 'West Lane', width: 7, points: [[160,590],[146,470],[163,360],[232,304],[300,335]] },
    { name: 'Orchard Lane', width: 6, points: [[300,335],[288,246],[310,158],[412,118],[510,170]] },
    { name: 'South Lane', width: 7, points: [[320,548],[302,670],[352,755],[440,790],[546,820]] },
    { name: 'Mill Road', width: 7, points: [[538,660],[670,665],[762,714],[839,811],[876,890],[910,985]] },
    { name: 'Garden Lane', width: 7, points: [[302,670],[420,646],[465,630],[500,637],[538,660]] },
    { name: 'Riverside Lane', width: 7, points: [[710,474],[746,555],[752,630],[762,714]] },
    { name: 'West Cut', width: 6, points: [[146,470],[224,438],[298,448]] },
    { name: 'Market Street', width: 8, points: [[528,500],[551,563],[638,568],[746,555]] },
    { name: 'Farm Lane', width: 5, points: [[302,670],[160,690],[60,800],[0,810]] },
    { name: 'School Lane', width: 5, points: [[420,646],[419,675]] },
  ];
  const river = [[1000,840],[930,865],[860,889],[790,913],[720,951],[660,981],[620,1000]];
  const reserved = [[618,535,64],[388,700,66],[668,295,44],[610,613,49],[210,750,43],[470,650,18]];
  const noise = (n) => { const v=Math.sin(n*127.1+311.7)*43758.5453; return v-Math.floor(v); };
  const path = (points) => points.map((p,i)=>(i?'L':'M')+p.join(' ')).join('');
  const distance = (p,a,b) => {
    const dx=b[0]-a[0],dy=b[1]-a[1],u=Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy)));
    return Math.hypot(p[0]-a[0]-u*dx,p[1]-a[1]-u*dy);
  };
  const segments = roads.flatMap(r=>r.points.slice(1).map((b,i)=>({a:r.points[i],b,width:r.width})));
  const tree = (x,y,r=4) => '<g class="village-tree"><ellipse cx="'+(x+2)+'" cy="'+(y+2)+'" rx="'+r+'" ry="'+(r*.8)+'" fill="#000" opacity=".2"/><circle cx="'+x+'" cy="'+y+'" r="'+r+'" fill="#2B4436" stroke="#3D5945" stroke-width=".7"/><circle cx="'+(x-r*.25)+'" cy="'+(y-r*.25)+'" r="'+(r*.6)+'" fill="#456047" opacity=".45"/></g>';

  const landscape = `
<defs>
  <pattern id="village-crops" width="11" height="11" patternUnits="userSpaceOnUse" patternTransform="rotate(-18)"><path d="M0 0V11" stroke="#738064" stroke-width="1" opacity=".2"/></pattern>
  <pattern id="village-meadow" width="18" height="18" patternUnits="userSpaceOnUse"><path d="m4 7 2-2m8 10 2-2" stroke="#66755A" stroke-width=".8" opacity=".2"/></pattern>
</defs>
<rect width="1000" height="1000" fill="#141E1E"/>
<path d="M0 0H450L430 75 294 117 247 260 95 304 0 280Z" fill="#202C25"/>
<g stroke="#45513C" stroke-width="2">
  <path d="M22 25 177 20 197 126 43 151Z" fill="#303626"/><path d="m192 22 124-4 62 71-164 41Z" fill="#293529"/>
  <path d="m44 169 154-25 30 111-136 42-63-35Z" fill="#353628"/>
  <path d="m20 744 137-27 85 107-88 121-134 19Z" fill="#303626"/>
  <path d="m171 844 99-63 73 79-65 120-107-2Z" fill="#26362B"/>
  <path d="m833 520 140-38 27 145-127 27Z" fill="#2D3527"/>
  <path d="m869 673 131-24v155l-87 20Z" fill="#333627"/>
</g>
<g fill="url(#village-crops)"><path d="M22 25 177 20 197 126 43 151Z"/><path d="m44 169 154-25 30 111-136 42-63-35Z"/><path d="m20 744 137-27 85 107-88 121-134 19Z"/><path d="m869 673 131-24v155l-87 20Z"/></g>
<path d="M0 330 95 310 130 442 93 655 0 696Z" fill="#1D2C25"/><path d="M0 330 95 310 130 442 93 655 0 696Z" fill="url(#village-meadow)"/>
<path d="M775 0H1000V403L920 410 834 330 787 222 745 104Z" fill="#1A2C24"/>
<path d="M295 848 463 873 512 1000H298Z" fill="#202F27"/><path d="M295 848 463 873 512 1000H298Z" fill="url(#village-meadow)"/>
<path d="M1000 840C900 880 820 900 760 940S650 990 620 1000" fill="none" stroke="#294237" stroke-width="25"/>
<path d="M1000 840C900 880 820 900 760 940S650 990 620 1000" fill="none" stroke="#294E54" stroke-width="12"/>
<path d="M1000 840C900 880 820 900 760 940S650 990 620 1000" fill="none" stroke="#477278" stroke-width="3" opacity=".5"/>`;

  // Paint all kerbs before the carriageways so junctions join without seams.
  const roadDrawing = '<g fill="none" stroke-linejoin="round" stroke-linecap="round">'+
    roads.map(r=>'<path d="'+path(r.points)+'" stroke="#59625D" stroke-width="'+(r.width+5)+'"/>').join('')+
    roads.map(r=>'<path class="village-street" data-street="'+r.name+'" d="'+path(r.points)+'" stroke="#333E42" stroke-width="'+r.width+'"/>').join('')+
    roads.slice(0,2).map(r=>'<path d="'+path(r.points)+'" stroke="#A2A28C" stroke-width=".7" stroke-dasharray="5 9" opacity=".45"/>').join('')+'</g>';

  // Lots follow street bearings and keep clear of junctions, water and landmarks.
  const candidates=[];
  roads.forEach((r,ri)=>{
    let travelled=0,next=28+noise(ri)*20,index=0;
    r.points.slice(1).forEach((b,i)=>{
      const a=r.points[i],length=Math.hypot(b[0]-a[0],b[1]-a[1]),angle=Math.atan2(b[1]-a[1],b[0]-a[0]);
      while(next<travelled+length){
        const u=(next-travelled)/length,x=a[0]+(b[0]-a[0])*u,y=a[1]+(b[1]-a[1])*u;
        [-1,1].forEach(side=>{
          const seed=ri*1000+index*2+(side+1)/2,w=14+noise(seed+1)*8,h=12+noise(seed+2)*6;
          const radius=Math.hypot(w+14,h+16)/2,offset=radius+r.width/2+5+noise(seed+3)*4;
          const cx=x-Math.sin(angle)*side*offset,cy=y+Math.cos(angle)*side*offset;
          candidates.push({x:cx,y:cy,angle,side,w,h,radius,offset,roadWidth:r.width,seed,
            priority:Math.hypot(cx-480,cy-510)*.35+noise(seed+5)*150});
        });
        index++;next+=50+noise(ri*100+index)*12;
      }
      travelled+=length;
    });
  });
  const lots=[];
  candidates.sort((a,b)=>a.priority-b.priority).forEach(c=>{
    if(lots.length>=112||c.x<65||c.x>880||c.y<90||c.y>890)return;
    if(((c.x-480)/365)**2+((c.y-500)/365)**2>1.1)return;
    if(reserved.some(([x,y,r])=>Math.hypot(x-c.x,y-c.y)<r+c.radius))return;
    if(segments.some(s=>distance([c.x,c.y],s.a,s.b)<c.radius+s.width/2+2))return;
    if(river.slice(1).some((b,i)=>distance([c.x,c.y],river[i],b)<c.radius+16))return;
    if(lots.some(p=>Math.hypot(p.x-c.x,p.y-c.y)<p.radius+c.radius+2))return;
    lots.push(c);
  });
  const roofs=['#795D52','#6A625A','#705950','#58656A','#80675B'];
  const houses=lots.map(c=>{
    const {w,h,side,seed}=c,lw=w+14,lh=h+16,roof=roofs[Math.floor(noise(seed+6)*roofs.length)];
    return '<g class="village-house" transform="translate('+c.x.toFixed(1)+' '+c.y.toFixed(1)+') rotate('+(c.angle*180/Math.PI).toFixed(1)+')">'+
      '<rect x="'+(-lw/2)+'" y="'+(-lh/2)+'" width="'+lw+'" height="'+lh+'" rx="2" fill="'+(seed%2?'#253A2E':'#2B3D30')+'" stroke="#50614B" stroke-width=".7"/>'+
      '<path d="M'+(w/2+3)+' '+(-side*(c.offset-c.roadWidth/2))+'V0" stroke="#62675B" stroke-width="3"/>'+
      '<path d="M0 '+(-side*h/2)+'V'+(-side*(c.offset-c.roadWidth/2))+'" stroke="#76796A" stroke-width="1.5"/>'+
      '<rect x="'+(-w/2+2)+'" y="'+(-h/2+3)+'" width="'+w+'" height="'+h+'" fill="#000" opacity=".3"/>'+
      '<rect x="'+(-w/2)+'" y="'+(-h/2)+'" width="'+w+'" height="'+h+'" fill="'+roof+'" stroke="#B6A28C" stroke-opacity=".5" stroke-width=".7"/>'+
      '<path d="M'+(-w/2)+' '+(-h/2)+'h'+w+'v'+(h/2)+'h'+(-w)+'Z" fill="#D6C9AA" opacity=".12"/>'+
      '<path d="M'+(-w/2)+' 0h'+w+'" stroke="#3B3631" stroke-width=".9"/>'+
      '<rect x="'+(w*.2)+'" y="'+(-h*.3)+'" width="2" height="3" fill="#3E3B37"/>'+
      tree(-w/2-3,side*(h/2+3),2.7)+
      (seed%4===0?'<rect x="'+(w/2-3)+'" y="'+(side>0?h/2+2:-h/2-6)+'" width="5" height="4" fill="#6C7169" stroke="#9C9F90" stroke-width=".5"/>':'')+'</g>';
  }).join('');

  const landmarks = `
<g class="village-landmark" data-place="Market square">
  <path d="M580 507 655 510 657 555 573 550Z" fill="#53564C" stroke="#787969" stroke-width="1.3"/>
  <path d="M620 488v24m10 40 8 16" stroke="#7D7E6D" stroke-width="4"/>
  <path d="M585 529h64m-37-17v36m24-35v37" stroke="#797B68" stroke-width=".7" opacity=".55"/>
  <circle cx="612" cy="531" r="7" fill="#28454C" stroke="#85877B" stroke-width="2"/><circle cx="612" cy="531" r="2" fill="#9B9B88"/>
  <g fill="#7A6555" stroke="#AF9880" stroke-width=".7"><rect x="551" y="512" width="18" height="30"/><rect x="584" y="511" width="22" height="11"/><rect x="628" y="514" width="22" height="12"/></g>
  <path d="M560 513v28m25-24h20m24 3h20" stroke="#453B33" stroke-width="1"/>
  <path d="M584 524h22m22 5h22" stroke="#8B826B" stroke-width="3" stroke-dasharray="3 2"/>
  <rect x="664" y="512" width="39" height="25" fill="#000" opacity=".25"/>
  <rect x="661" y="509" width="39" height="25" fill="#666C69" stroke="#9B9C88" stroke-width=".8"/>
  <path d="M662 521h37" stroke="#454C4C"/>
  <g fill="#8D9187"><rect x="667" y="540" width="3" height="6" rx="1"/><rect x="676" y="540" width="3" height="6" rx="1"/><rect x="685" y="540" width="3" height="6" rx="1"/></g>
</g>
<g class="village-landmark" data-place="Church" transform="translate(668 295)">
  <ellipse rx="34" ry="36" fill="#394537" stroke="#59624E"/>
  <path d="M14 14 46 49" stroke="#6F7564" stroke-width="4"/>
  <g transform="rotate(-14)"><rect x="-9" y="-18" width="18" height="39" fill="#826F5A" stroke="#B4A48B" stroke-width="1"/>
  <path d="M0-18v39" stroke="#4A4037" stroke-width="1.2"/><rect x="-7" y="-29" width="14" height="14" fill="#59666A" stroke="#9CA59A"/>
  <path d="m0-30 5 8-5 6-5-6Z" fill="#8A9692"/><path d="M0-27v10m-3-6h6" stroke="#D0C8AD" stroke-width="1"/></g>
</g>
<g class="village-landmark" data-place="School">
  <rect x="353" y="674" width="120" height="66" rx="3" fill="#304332" stroke="#60715A" stroke-width="1"/>
  <path d="M419 675v12m-61 26h49" stroke="#7D816D" stroke-width="5"/>
  <rect x="363" y="688" width="44" height="22" fill="#000" opacity=".25"/>
  <rect x="360" y="685" width="44" height="22" fill="#78685A" stroke="#ACA08A" stroke-width=".8"/><path d="M361 696h42" stroke="#4D443D"/>
  <rect x="414" y="683" width="51" height="44" rx="2" fill="#3C5640" stroke="#B0B59A" stroke-width=".7"/>
  <path d="M439.5 683v44m-25-30h7v16h-7m51-16h-7v16h7" fill="none" stroke="#B0B59A" stroke-width=".6"/><circle cx="439.5" cy="705" r="6" fill="none" stroke="#B0B59A" stroke-width=".6"/>
</g>
<g class="village-landmark" data-place="Village green">
  <ellipse cx="610" cy="613" rx="43" ry="35" fill="#2B4534" stroke="#4E654D"/>
  <path d="M595 582q-28 38 8 52t32-28q-4-14-23-13" fill="none" stroke="#858672" stroke-width="2"/>
  <ellipse cx="625" cy="609" rx="12" ry="8" fill="#31525A" stroke="#5A766F"/>
  <path d="m581 614 5 1m28 22 5-1" stroke="#A19377" stroke-width="2"/>
</g>
<g class="village-landmark" data-place="Farm">
  <path d="M160 690 202 733" stroke="#5F6251" stroke-width="5"/>
  <path d="M175 722 248 722 259 783 179 789Z" fill="#393E2D" stroke="#5C624B"/>
  <g transform="translate(211 751) rotate(38)"><rect x="-13" y="-20" width="26" height="40" fill="#73594C" stroke="#AF9175"/><path d="M0-20v40" stroke="#453A32"/></g>
  <rect x="239" y="758" width="12" height="20" fill="#5C6866" stroke="#89958A" stroke-width=".7"/>
</g>
<g class="village-bridge" transform="translate(872 881) rotate(65)"><rect x="-19" y="-7" width="38" height="14" fill="#77786B"/><path d="M-18-6h36m-36 12h36" stroke="#B9B7A0" stroke-width="1.4"/><path d="M-14-4v8m7-8v8m7-8v8m7-8v8m7-8v8" stroke="#535B56" stroke-width=".7"/></g>`;

  let trees='';
  for(let i=0;i<78;i++){
    const x=790+noise(i+600)*190,y=30+noise(i+900)*340;
    if(segments.every(s=>distance([x,y],s.a,s.b)>18))trees+=tree(Math.round(x*10)/10,Math.round(y*10)/10,4+noise(i)*4);
  }
  for(let i=0;i<22;i++){
    const x=333+(i%6)*19,y=43+Math.floor(i/6)*17;
    trees+=tree(x,y,4);
  }
  [[585,601],[595,625],[636,626],[576,620],[648,601],[648,285],[688,314],[644,315],[365,728],[400,732]].forEach(([x,y])=>{trees+=tree(x,y,4.5);});

  const labels = `<g class="t" style="font-size:8px;fill:#A7AF9D;stroke-width:2.5;letter-spacing:.08em">
<text x="62" y="585" transform="rotate(-7 62 585)">MAIN ROAD</text><text x="535" y="200" transform="rotate(88 535 200)">NORTH ROAD</text>
<text x="184" y="345" transform="rotate(-40 184 345)">WEST LANE</text><text x="352" y="125" transform="rotate(-22 352 125)">ORCHARD LANE</text>
<text x="333" y="651" transform="rotate(-11 333 651)">GARDEN LANE</text><text x="790" y="762" transform="rotate(48 790 762)">MILL ROAD</text>
<text x="667" y="344" text-anchor="middle">CHURCH</text><text x="380" y="720" text-anchor="middle">SCHOOL</text>
<text x="613" y="548" text-anchor="middle" style="font-size:6px">MARKET SQUARE</text><text x="612" y="653" text-anchor="middle" style="font-size:7px">VILLAGE GREEN</text>
<text x="844" y="942" transform="rotate(-24 844 942)" style="fill:#6E9295;font-style:italic">MILL BROOK</text></g>`;

  global.Village = { landscape, settlement: roadDrawing+houses+landmarks+trees+labels,
    stats: { streets: roads.length, houses: lots.length, landmarks: 5 } };
})(typeof window !== 'undefined' ? window : globalThis);
