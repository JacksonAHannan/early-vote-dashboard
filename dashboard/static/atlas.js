'use strict';
const Atlas=window.Atlas={
 map:null,layer:null,cache:new Map(),layers:new Map(),county:'travis',active:null,native:null,ctx:null,request:0,initialized:false,
 init(ctx){
  this.ctx=ctx;
  if(this.initialized)return;
  this.initialized=true;
  this.map=L.map('county-map',{zoomControl:false,attributionControl:true,scrollWheelZoom:false,trackResize:false,zoomSnap:.25,minZoom:4,maxZoom:19,preferCanvas:false});
  L.control.zoom({position:'bottomright'}).addTo(this.map);
  this.map.attributionControl.setPrefix(false);this.map.attributionControl.addAttribution('Texas Legislative Council');
  this.map.setView([30.3,-97.75],9);
  $('map-county').innerHTML=ctx.data.counties.map(c=>`<option value="${c.id}">${esc(c.name)} County</option>`).join('');
  $('map-county').value=this.county;
  $('map-county').onchange=e=>{this.active=null;this.native=null;this.ctx.onCounty(e.target.value);this.showCounty(e.target.value,true);};
  $('map-layer').onchange=()=>{this.hideTooltip();this.repaint();this.legend();};
  $('map-reset').onclick=()=>this.reset();
  $('selection-clear').onclick=()=>this.reset();
  this.map.on('zoomend',()=>this.markSelection());
  this.map.on('movestart',()=>this.hideTooltip());
  window.addEventListener('scroll',()=>this.hideTooltip(),{passive:true,capture:true});
  window.addEventListener('resize',()=>this.hideTooltip());
  document.addEventListener('pointerdown',event=>{if(event.pointerType==='touch'){this.touchInput=true;this.hideTooltip();}},{capture:true,passive:true});
  document.addEventListener('pointermove',event=>{if(event.pointerType==='mouse'&&!event.sourceCapabilities?.firesTouchEvents)this.touchInput=false;},{capture:true,passive:true});
  document.addEventListener('keydown',event=>{this.touchInput=false;if(event.key==='Escape')this.hideTooltip();},{capture:true});
  this.map.on('resize',()=>{if(!this.layer||!this.visible())return;if(this.active?.county===this.county)this.zoomGroup(this.active.group_index,this.native,false);else this.map.fitBounds(this.layer.getBounds(),{padding:[24,24],animate:false});});
  new ResizeObserver(()=>{if(this.visible())this.map.invalidateSize({pan:false});}).observe($('county-map'));
  this.showCounty(this.county,true);
 },
 visible(){const node=$('county-map');return node.clientWidth>80&&node.clientHeight>80;},
 update(ctx){this.hideTooltip();this.ctx=ctx;if(!this.initialized){this.init(ctx);return;}this.repaint();this.legend();this.profile();},
 countyRecord(id=this.county){return this.ctx.data.counties.find(c=>c.id===id);},
 period(id=this.county){const p=this.countyRecord(id)?.periods.find(p=>p.day===this.ctx.day);return p?.coverage?.available_groups===0?undefined:p;},
 group(id,index){return this.period(id)?.groups[index];},
 counts(id=this.county,precinct=null){
  const period=this.period(id);if(!period)return null;if(precinct===null)return period.county_2026;
  const group=period.groups.find(g=>g.new.includes(precinct));if(!group||group.available===false)return null;
  const sources=this.countyRecord(id)?.sources||[],end=new Date(Date.UTC(2026,9,18+this.ctx.day)).toISOString().slice(0,10);
  const cumulative=sources.find(s=>s.cumulative&&s.date===end);
  if(cumulative)return precinct===null?Object.values(cumulative.counts).reduce((a,b)=>a+b,0):(cumulative.counts[precinct]||0);
  const daily=sources.filter(s=>!s.cumulative&&s.date>='2026-10-19'&&s.date<=end);
  if(daily.length!==this.ctx.day)return null;
  return daily.reduce((total,s)=>total+(precinct===null?Object.values(s.counts).reduce((a,b)=>a+b,0):(s.counts[precinct]||0)),0);
 },
 censusCounts(id=this.county,precinct=null){
  const county=this.ctx.census?.counties?.[id];if(!county)return null;
  if(precinct!==null)return county.precincts?.[precinct]?.counts||null;
  return county.assigned_totals||Object.values(county.precincts).reduce((result,p)=>{for(const [key,v]of Object.entries(p.counts))if(v!==null)result[key]=(result[key]||0)+v;return result;},{});
 },
 classificationCounts(id,precinct){return this.ctx.classification?.counties?.[id]?.precincts?.[precinct]?.counts||null;},
 metricValue(counts){const metric=this.ctx.metric;if(!counts||!metric)return null;const n=counts[metric.numerator],d=counts[metric.denominator];return n!==null&&n!==undefined&&d>0?100*n/d:null;},
 mix(a,b,t){t=Math.max(0,Math.min(1,t));const aa=a.match(/\w\w/g).map(v=>parseInt(v,16)),bb=b.match(/\w\w/g).map(v=>parseInt(v,16));return '#'+aa.map((v,i)=>Math.round(v+(bb[i]-v)*t).toString(16).padStart(2,'0')).join('');},
 color(value){
  if(value===null||!Number.isFinite(value))return '#dfe5ec';
  if($('map-layer').value==='turnout')return value<100?this.mix('a77b35','f4f5f7',(value-50)/50):this.mix('f4f5f7','176b83',(value-100)/50);
  if(this.ctx.mode==='demographic')return this.mix('edf5f3','087383',value/100);
  return value<50?this.mix('b5463d','f4f3f4',value/50):this.mix('f4f3f4','2266a7',(value-50)/50);
 },
 eligible(g){return g&&g.available!==false&&(this.ctx.cohort==='unchanged'?g.unchanged:(this.ctx.mode!=='partisan'||g.bucket!==null));},
 featureValue(feature){
  const p=feature.properties,g=this.group(p.county,p.group);
  if(this.ctx.mode!=='partisan'&&$('map-layer').value==='share'&&this.ctx.cohort==='matched')return this.metricValue(this.classificationCounts(p.county,p.precinct));
  if(!this.eligible(g))return null;
  if($('map-layer').value==='turnout')return g.votes_2024>0?100*g.votes_2026/g.votes_2024:null;
  if(this.ctx.mode!=='partisan')return this.metricValue(this.classificationCounts(p.county,p.precinct));
  return g.harris+g.trump>0?100*g.harris/(g.harris+g.trump):null;
 },
 style(feature){
  const p=feature.properties,isSelected=this.active?.county===p.county&&this.active.group_index===p.group;
  const isNative=isSelected&&this.native===p.precinct;
  return {color:isNative?'#4c269b':isSelected?'#713bc2':'#ffffff',weight:isNative?3:isSelected?2.3:.65,opacity:1,fillColor:this.color(this.featureValue(feature)),fillOpacity:isSelected?.95:this.ctx.bucket!==null&&(this.ctx.focusCounty!==p.county||this.ctx.bins.get(`${p.county}:${p.group}`)!==this.ctx.bucket)?.2:.85};
 },
 tooltip(feature){
  const p=feature.properties,county=this.countyRecord(p.county),candidate=this.group(p.county,p.group),reference=referenceByCounty.get(p.county),geometry=candidate||reference?.groups[p.group];
  const paired=candidate?.available!==false&&candidate&&(this.ctx.cohort!=='unchanged'||candidate.unchanged)?candidate:null;
  const native=this.counts(p.county,p.precinct),counts=this.censusCounts(p.county,p.precinct),multiple=(geometry?.new.length||0)>1;
  const records=geometry?.old.map(id=>reference?.presidential[id])||[],complete=records.length>0&&records.every(Boolean);
  const harris=complete?records.reduce((sum,r)=>sum+r.harris,0):0,trump=complete?records.reduce((sum,r)=>sum+r.trump,0):0,share=harris+trump>0?harris/(harris+trump):null;
  const pairRatio=paired&&paired.votes_2024>0?paired.votes_2026/paired.votes_2024:null;
  const detail=(label,value)=>`<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`;
  const race=(label,key)=>{const value=counts?.[key],denominator=counts?.vap;return detail(label,percent(Number.isFinite(value)&&value>=0&&value<=denominator&&denominator>0?value/denominator:null));};
  const primaryMetric=primary?.metrics[0],primaryCounts=primary?.counties?.[p.county]?.precincts?.[p.precinct]?.counts,primaryShare=primaryMetric&&primaryCounts&&Number.isFinite(primaryCounts[primaryMetric.numerator])&&primaryCounts[primaryMetric.numerator]>=0&&primaryCounts[primaryMetric.numerator]<=primaryCounts[primaryMetric.denominator]&&primaryCounts[primaryMetric.denominator]>0?primaryCounts[primaryMetric.numerator]/primaryCounts[primaryMetric.denominator]:null;
  const extraMetric=this.ctx.mode==='demographic'&&this.ctx.metric?.denominator!=='vap'?this.ctx.metric:null,extraN=extraMetric?counts?.[extraMetric.numerator]:null,extraD=extraMetric?counts?.[extraMetric.denominator]:null,extraShare=Number.isFinite(extraN)&&extraN>=0&&extraN<=extraD&&extraD>0?extraN/extraD:null;
  const band=candidate?.bucket!==null&&candidate?.bucket!==undefined?this.period(p.county)?.buckets[candidate.bucket]?.label:null;
  return `<div class="hover-heading"><strong>Precinct ${esc(p.precinct)}</strong><span>${esc(county?.name||p.county)} County</span></div><div class="hover-turnout"><div><span>2026 in person</span><strong>${native===null?'—':number(native)}</strong></div><div><span>${multiple?'Group':'Matched'} vs. 2024</span><strong>${percent(pairRatio)}</strong></div></div><div class="hover-comparison"><span>${multiple?'Group':'Matched'} votes · 2026 / 2024</span><b>${paired?number(paired.votes_2026)+' / '+number(paired.votes_2024):'Unavailable'}</b></div>${geometry&&(geometry.new.length>1||geometry.old.join(';')!==geometry.new.join(';'))?`<div class="hover-geography">Comparison group · ${geometry.new.length} current / ${geometry.old.length} historical precincts</div>`:''}<div class="hover-party"><span>${esc(band?(multiple?'2024 group · ':'2024 · ')+band:'2024 comparison group')}</span><b>${share===null?'Unknown':`Harris ${percent(share)} · Trump ${percent(1-share)}`}</b></div><dl class="hover-census">${detail('2020 residents',counts?.population===null||counts?.population===undefined?'—':number(counts.population))}</dl>${extraMetric?`<dl class="hover-current-metric">${detail(extraMetric.label,percent(extraShare))}</dl>`:''}<div class="hover-census-heading"><span>Residents age 18+</span><b>${counts?.vap===null||counts?.vap===undefined?'—':number(counts.vap)}</b></div><dl class="hover-census">${race('Total non-white','non_white_vap')}${race('Hispanic','hispanic_vap')}${race('White non-Hispanic','white_nh_vap')}${race('Black','black_vap')}${race('Asian','asian_vap')}</dl>${primaryShare===null&&this.ctx.mode!=='primary'?'':`<dl class="hover-primary">${detail('2026 Democratic primary',percent(primaryShare))}</dl>`}<div class="hover-dates">${esc(dates(comparisonPeriod(this.ctx.day)))}</div>`;
 },
 showTooltip(feature,event,layer){
  if(this.touchInput||!this.visible()||!$('map-loading').hidden||feature.properties.county!==this.county||event?.originalEvent?.buttons||event?.originalEvent?.sourceCapabilities?.firesTouchEvents)return;
  if(!this.tooltipNode){const node=document.createElement('div');node.id='precinct-tooltip';node.className='precinct-hover';node.setAttribute('role','tooltip');document.body.append(node);this.tooltipNode=node;}
  const node=this.tooltipNode;node.innerHTML=this.tooltip(feature);node.dataset.precinct=feature.properties.precinct;node.dataset.county=feature.properties.county;node.hidden=false;
  const original=event?.originalEvent,box=layer.getElement()?.getBoundingClientRect(),mapBox=$('county-map').getBoundingClientRect();
  const x=Number.isFinite(original?.clientX)?original.clientX:Math.max(mapBox.left,Math.min(mapBox.right,box?box.left+box.width/2:mapBox.left+mapBox.width/2));
  const y=Number.isFinite(original?.clientY)?original.clientY:Math.max(mapBox.top,Math.min(mapBox.bottom,box?box.top+box.height/2:mapBox.top+mapBox.height/2));
  this.positionTooltip(x,y);
 },
 positionTooltip(x,y){
  const node=this.tooltipNode;if(!node||node.hidden)return;
  const width=node.offsetWidth,height=node.offsetHeight,pad=10,gap=14;
  const left=x+gap+width>innerWidth-pad?x-width-gap:x+gap,top=y+gap+height>innerHeight-pad?y-height-gap:y+gap;
  node.style.left=Math.max(pad,Math.min(innerWidth-width-pad,left))+'px';node.style.top=Math.max(pad,Math.min(innerHeight-height-pad,top))+'px';
 },
 hideTooltip(){if(this.tooltipNode)this.tooltipNode.hidden=true;},

 async showCounty(id,fit=true){
  this.hideTooltip();this.county=id;$('map-county').value=id;const token=++this.request;
  $('map-loading').hidden=false;$('map-loading').textContent='Loading precincts…';
  try{
   let geo=this.cache.get(id);if(!geo){const response=await fetch(`/api/map/${encodeURIComponent(id)}`);if(!response.ok)throw Error('County map unavailable');geo=await response.json();this.cache.set(id,geo);}
   if(token!==this.request)return;
   if(this.layer)this.layer.remove();this.layers.clear();
   this.layer=L.geoJSON(geo,{style:f=>this.style(f),onEachFeature:(feature,layer)=>{
    this.layers.set(feature.properties.precinct,layer);
    layer.on('click',()=>{this.hideTooltip();this.ctx.onSelect(id,feature.properties.group,feature.properties.precinct,true);});
    layer.on('mouseover',event=>{if(this.touchInput||event.originalEvent?.sourceCapabilities?.firesTouchEvents)return;this.hover(id,feature.properties.group);layer.setStyle({weight:2,color:'#4f3a77'});this.raise(layer);this.showTooltip(feature,event,layer);});
    layer.on('mousemove',event=>{if(this.touchInput)return;if(event.originalEvent?.buttons){this.hideTooltip();return;}if(this.tooltipNode?.hidden)this.showTooltip(feature,event,layer);else if(event.originalEvent)this.positionTooltip(event.originalEvent.clientX,event.originalEvent.clientY);});
    layer.on('mouseout',()=>{this.hideTooltip();this.hover(null,null);});
   }}).addTo(this.map);
   this.layer.eachLayer(layer=>{const el=layer.getElement();if(el){
    el.dataset.precinct=layer.feature.properties.precinct;el.dataset.group=layer.feature.properties.group;el.setAttribute('aria-label',`Precinct ${layer.feature.properties.precinct}`);el.setAttribute('aria-describedby','precinct-tooltip');el.setAttribute('tabindex',this.layers.values().next().value===layer?'0':'-1');
    el.addEventListener('focus',()=>{if(this.touchInput)return;for(const sibling of this.layers.values())sibling.getElement()?.setAttribute('tabindex',sibling===layer?'0':'-1');this.hover(id,layer.feature.properties.group);this.showTooltip(layer.feature,null,layer);});el.addEventListener('blur',()=>{this.hideTooltip();this.hover(null,null);});
    el.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();this.hideTooltip();this.ctx.onSelect(id,layer.feature.properties.group,layer.feature.properties.precinct,true);}else if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)){event.preventDefault();const layers=[...this.layers.values()],index=layers.indexOf(layer),next=layers[(index+(['ArrowLeft','ArrowUp'].includes(event.key)?-1:1)+layers.length)%layers.length];el.tabIndex=-1;const target=next.getElement();if(!this.map.getBounds().contains(next.getBounds().getCenter()))this.map.panTo(next.getBounds().getCenter(),{animate:false});target.tabIndex=0;target.focus({preventScroll:true});}});
   }});
   $('map-loading').hidden=true;if(fit&&this.visible())this.map.fitBounds(this.layer.getBounds(),{padding:[24,24],animate:false});
   this.repaint();this.legend();this.profile();
   if(this.active?.county===id)this.zoomGroup(this.active.group_index,this.native,false);
  }catch(error){if(token===this.request){$('map-loading').textContent=error.message;this.layer?.remove();this.layers.clear();this.profile();}}
 },
 async focus(id,index,precinct=null,zoom=true){
  this.active={county:id,group_index:index};this.native=precinct;
  if(id!==this.county||!this.layer)await this.showCounty(id,false);
  if(this.active?.county!==id||this.active.group_index!==index)return;
  this.repaint();this.profile();if(zoom)this.zoomGroup(index,precinct,true);
 },
 zoomGroup(index,precinct,animate){
  if(!this.visible())return;
  let layers=precinct&&this.layers.has(precinct)?[this.layers.get(precinct)]:[...this.layers.values()].filter(l=>l.feature.properties.group===index);
  if(!layers.length)return;
  const bounds=L.featureGroup(layers).getBounds();if(!bounds.isValid())return;
  this.map.fitBounds(bounds,{padding:[36,36],maxZoom:15,animate:animate&&!matchMedia('(prefers-reduced-motion: reduce)').matches,duration:.45});
  this.markSelection();
 },
 markSelection(){
  if(this.marker){this.marker.remove();this.marker=null;}
  if(!this.active||this.active.county!==this.county)return;
  const layers=[...this.layers.values()].filter(l=>l.feature.properties.group===this.active.group_index);if(!layers.length)return;
  const native=this.native?this.layers.get(this.native):null;
  const bounds=native?.getBounds()||L.featureGroup(layers).getBounds();
  // A focus marker keeps tiny or disconnected precincts visible at county scale.
  this.marker=L.circleMarker(bounds.getCenter(),{radius:5,color:'#ffffff',weight:2,fillColor:'#713bc2',fillOpacity:1,interactive:false}).addTo(this.map);
 },
 // Moving a focused SVG node detaches it and clears browser keyboard focus.
 raise(layer){if(layer.getElement()!==document.activeElement)layer.bringToFront();},
 repaint(){if(this.layer){this.layer.eachLayer(layer=>{layer.setStyle(this.style(layer.feature));if(this.active?.group_index===layer.feature.properties.group)this.raise(layer);});}this.markSelection();},
 hover(id,index){
  document.querySelectorAll('.regression-point').forEach(el=>el.classList.toggle('linked-hover',el.dataset.id===`${id}:${index}`));
  if(!this.layer)return;
  this.layer.eachLayer(layer=>{layer.setStyle(this.style(layer.feature));if(id===this.county&&layer.feature.properties.group===index){layer.setStyle({color:'#713bc2',weight:2});this.raise(layer);}});
 },
 reset(){this.hideTooltip();this.active=null;this.native=null;this.ctx.onClear();this.repaint();if(this.layer&&this.visible())this.map.fitBounds(this.layer.getBounds(),{padding:[24,24],animate:!matchMedia('(prefers-reduced-motion: reduce)').matches,duration:.4});this.profile();},
 legend(){
  const demo=this.ctx.mode!=='partisan',turnout=$('map-layer').value==='turnout';
  $('map-layer').options[0].textContent=demo?this.ctx.metric?.label||'Demographic share':'Harris share';
  const gradient=turnout?'#a77b35,#f4f5f7,#176b83':this.ctx.mode==='demographic'?'#edf5f3,#87babb,#087383':'#b5463d,#f4f3f4,#2266a7';
  const label=turnout?'2026 / 2024 group votes':demo?`${this.ctx.metric?.label||'Residents'}${this.ctx.metric?.denominator==='vap'?' · age 18+':''}`:'2024 group Harris share';
  $('map-legend').innerHTML=`<span>${esc(label)}</span><div class="scale"><div class="scale-bar" style="background:linear-gradient(90deg,${gradient})"></div><div class="scale-ticks"><span>${turnout?'50%':'0%'}</span><span>${turnout?'100%':'50%'}</span><span>${turnout?'150%+':'100%'}</span></div></div><span class="map-vintage">${demo&&!turnout?(this.ctx.mode==='primary'?(Object.keys(this.ctx.classification?.counties?.[this.county]?.precincts||{}).length?'2026 primary':'Primary unavailable'):'2020 Census'):'2026 precincts'}</span>`;
 },
 profile(){
  const county=this.countyRecord(),period=this.period();if(!county)return;
  const active=this.active?.county===this.county?this.active:null,candidate=active?this.group(this.county,active.group_index):null,g=candidate?.available===false?null:candidate;
  const geometry=g||(active?referenceByCounty.get(this.county)?.groups[active.group_index]:null),precinct=this.native,ids=geometry?.new||[],isNative=precinct!==null;
  let counts=this.censusCounts(this.county,precinct);
  if(geometry&&!isNative){const rows=ids.map(id=>this.censusCounts(this.county,id));counts=rows.every(Boolean)?Object.fromEntries(Object.keys(rows[0]).map(key=>[key,rows.every(row=>row[key]!==null&&row[key]!==undefined)?rows.reduce((sum,row)=>sum+row[key],0):null])):null;}
  const current=isNative?this.counts(this.county,precinct):g?g.votes_2026:active?null:period?.county_2026;
  const baseline=g?g.votes_2024:active||isNative?null:period?.county_2024;
  const h=candidate?candidate.harris:period?.groups.reduce((s,g)=>s+g.harris,0),t=candidate?candidate.trump:period?.groups.reduce((s,g)=>s+g.trump,0),complete=candidate?presidentialComplete(county,candidate):period?.groups.every(g=>presidentialComplete(county,g));
  $('selection-title').textContent=isNative?`Precinct ${precinct}`:geometry?(ids.length===1?`Precinct ${ids[0]}`:`${ids.length} precincts`):`${county.name} County`;
  $('selection-context').textContent=(geometry||isNative)?`${county.name}${geometry?.new.length>1?' / comparable group '+ids.join(', '):''}`:`${this.cache.get(this.county)?.features.length||'—'} precincts`;
  $('selection-clear').hidden=!(geometry||isNative);
  $('selection-panel').dataset.county=this.county;$('selection-panel').dataset.group=active?.group_index??'';$('selection-panel').dataset.precinct=precinct||'';
  const ratio=baseline>0&&Number.isFinite(current)?(g?g.votes_2026:current)/baseline:null;
  const stats=[[current===null||current===undefined?'—':number(current),'2026 in-person'],[percent(ratio),geometry&&isNative&&geometry.new.length>1?'Group vs. 2024':'vs. 2024'],[complete&&h+t>0?percent(h/(h+t)):'—',geometry&&geometry.new.length>1?'2024 group Harris':'2024 Harris'],[counts?.population===null||counts?.population===undefined?'—':number(counts.population),'2020 residents'],[counts?.vap===null||counts?.vap===undefined?'—':number(counts.vap),'Residents age 18+']];
  $('selection-stats').innerHTML=stats.map(([v,k])=>`<div><dd>${v}</dd><dt>${k}</dt></div>`).join('');
  const bars=[['Total non-white','non_white_vap','#137b8a'],['Hispanic','hispanic_vap','#7c5bb4'],['White non-Hispanic','white_nh_vap','#416d9b'],['Black','black_vap','#d28a39'],['Asian','asian_vap','#268c92']];
  $('demographic-profile').innerHTML=bars.map(([label,key,color])=>{const value=counts?.[key],denom=counts?.vap,p=value!==null&&value!==undefined&&denom>0?value/denom:null;return `<div class="demographic-bar"><span>${label}</span><div><i style="width:${p===null?0:100*p}%;background:${color}"></i></div><b>${percent(p)}</b></div>`;}).join('');
  document.querySelector('.trend-panel h3').textContent=isNative&&geometry?.new.length>1?'Group cumulative votes':'Cumulative votes';
  this.trend(geometry,Boolean(active||isNative));
 },
 trend(group,selected=false){
  const county=this.countyRecord(),series=Array.from({length:this.ctx.day},(_,i)=>{const day=i+1,p=county.periods.find(p=>p.day===day),g=group?p?.groups.find(q=>q.new.join(';')===group.new.join(';')):null;return {day,old:group?(g?.available===false?null:g?.votes_2024):selected||p?.coverage?.available_groups===0?null:p?.county_2024,current:group?(g?.available===false?null:g?.votes_2026):selected||p?.coverage?.available_groups===0?null:p?.county_2026};}),valid=series.filter(p=>Number.isFinite(p.old)&&Number.isFinite(p.current));
  if(!valid.length){$('turnout-trend').innerHTML='<span class="muted">No comparable turnout for this cutoff</span>';return;}
  const width=360,height=112,l=42,r=12,t=13,b=23,max=Math.max(1,...valid.flatMap(p=>[p.old,p.current]));
  const x=d=>l+(d-1)/Math.max(1,this.ctx.day-1)*(width-l-r),y=v=>height-b-v/max*(height-t-b);
  let svg=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Cumulative group votes by early-voting day"><line x1="${l}" x2="${width-r}" y1="${height-b}" y2="${height-b}" stroke="#dce3ea"/><text x="${l-7}" y="${t+5}" text-anchor="end" font-size="10" fill="#66758a">${number(max)}</text><text x="${l-7}" y="${height-b+3}" text-anchor="end" font-size="10" fill="#66758a">0</text>`;
  for(const [key,color]of [['old','#a6b1c2'],['current','#2266a7']]){let path='',open=false;for(const p of series){if(!Number.isFinite(p.old)||!Number.isFinite(p.current)){open=false;continue;}path+=`${open?'L':'M'}${x(p.day)},${y(p[key])} `;open=true;}svg+=`<path class="profile-year-${key==='old'?'2024':'2026'}" d="${path}" fill="none" stroke="${color}" stroke-width="2"/>`;for(const p of valid)svg+=`<circle data-year="${key==='old'?2024:2026}" data-day="${p.day}" cx="${x(p.day)}" cy="${y(p[key])}" r="3" fill="${color}"><title>Day ${p.day}: ${number(p[key])}</title></circle>`;}
  for(const p of valid)svg+=`<text x="${x(p.day)}" y="${height-5}" text-anchor="middle" font-size="10" fill="#66758a">${p.day}</text>`;
  $('turnout-trend').innerHTML=svg+'</svg>';
 }
};
