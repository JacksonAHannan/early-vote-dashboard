'use strict';
let data=null,dataEpoch=0,census=null,primary=null,references=null,referenceByCounty=new Map(),matrixPage=0,day=4,county='all',cohort='matched',selected='travis',bucket=null,sort='votes_2026',descending=true,page=0,mode='partisan',metricId='hispanic_vap',demoViews=null,demoKey='',demoPending='',selection=null,regressionWinner='all';
const $=id=>document.getElementById(id);
const colors=['#285b91','#9ec3e5','#deebf7','#fae1dc','#e6a69a','#a84236'];
const primaryColors=['#a84236','#d88f85','#f0eff2','#84afd3','#285b91'];
const demoColors=['#edf5f3','#cee7e4','#a2d2d0','#65b1b5','#137b8a'];
const number=n=>new Intl.NumberFormat('en-US',{maximumFractionDigits:0}).format(n);
const percent=r=>r===null||r===undefined||!Number.isFinite(r)?'—':`${(r*100).toFixed(1)}%`;
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const period=c=>{const p=c?.periods.find(p=>p.day===day);return p?.coverage?.available_groups===0?undefined:p;};
const classification=()=>mode==='primary'?primary:census;
const activeMetricId=()=>mode==='primary'?'primary_dem_share':metricId;
const metric=()=>classification()?.metrics.find(m=>m.id===activeMetricId());
const demoSignature=()=>`${data?.generated_at}|${day}|${cohort}|${mode}|${activeMetricId()}|${dataEpoch}`;
const demoReady=()=>demoKey===demoSignature()&&demoViews;
const small=c=>c.groups<3||c.votes_2024<100;
function dates(p){const range=(first,iso)=>{const d=Number(iso.slice(-2));return iso.slice(5,7)==='10'?(d===first?`Oct ${first}`:`Oct ${first}–${d}`):`Oct ${first}–Nov ${d}`;};return `${range(19,p.through_2026)}, 2026 / ${range(21,p.through_2024)}, 2024`;}
const comparisonPeriod=(n=day)=>({through_2026:new Date(Date.UTC(2026,9,18+n)).toISOString().slice(0,10),through_2024:new Date(Date.UTC(2024,9,20+n)).toISOString().slice(0,10)});
const eligible=g=>g.available!==false&&(cohort==='unchanged'?g.unchanged:(mode!=='partisan'||g.bucket!==null));
function presidentialComplete(c,g){const ref=referenceByCounty.get(c.id);return ref?g.old.every(id=>Object.hasOwn(ref.presidential,id)):g.reason!=='Missing or tied presidential return';}
function presidentialShare(c,g){return presidentialComplete(c,g)&&g.harris+g.trump>0?100*g.harris/(g.harris+g.trump):null;}
function groupRows(c){
 const p=period(c);if(!p)return [];
 if(mode!=='partisan')return (demoReady()?demoViews[c.id]?.points:[])?.map(point=>({...p.groups[point.group_index],group_index:point.group_index,id:point.id,share:point.x,view_bucket:point.bucket})).filter(g=>g.available!==false)||[];
 return p.groups.map((g,index)=>({...g,group_index:index,id:`${c.id}:${index}`,share:presidentialShare(c,g),view_bucket:g.bucket})).filter(eligible);
}
function bucketsFor(c){const p=period(c);if(!p)return null;if(mode!=='partisan')return demoReady()?demoViews[c.id]?.bins:null;return p.buckets.map(b=>({label:b.label,...b[cohort]}));}
let bucketUrl=null,regressionUrl=null,matrixLayout='counties',jointMetricId='hispanic_vap',jointViews=null,jointKey='',jointPending='';
const classificationPending=new Map();
const jointSignature=()=>`${data?.generated_at}|${day}|${cohort}|${jointMetricId}|${dataEpoch}`;
const jointReady=()=>jointKey===jointSignature()&&jointViews;
const jointMetric=()=>census?.metrics.find(m=>m.id===jointMetricId);
function downloadReady(id,ready){const link=$(id);link.setAttribute('aria-disabled',String(!ready));link.tabIndex=ready?0:-1;if(!ready)link.removeAttribute('href');}
function csvLink(id,rows,filename,oldUrl){if(oldUrl)URL.revokeObjectURL(oldUrl);const csv=rows.map(row=>row.map(v=>`"${String(v??'').replaceAll('"','""')}"`).join(',')).join('\r\n'),url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));$(id).href=url;$(id).download=filename;downloadReady(id,true);return url;}
function classificationRequest(view,metricId){
 const key=`${data.generated_at}|${day}|${cohort}|${view}|${metricId}|${dataEpoch}`;
 if(!classificationPending.has(key)){
  const request=fetch(`/api/demographic-view?day=${day}&cohort=${encodeURIComponent(cohort)}&metric=${encodeURIComponent(metricId)}&view=${view}`).then(async response=>{const payload=await response.json();if(!response.ok)throw Error(payload.error||'Classification unavailable');return payload;}).finally(()=>{if(classificationPending.get(key)===request)classificationPending.delete(key);});
  classificationPending.set(key,request);
 }
 return classificationPending.get(key);
}
async function ensureJoint(){
 const key=jointSignature();if(jointReady()||jointPending===key)return;
 jointPending=key;
 try{
  const payload=await classificationRequest('demographic',jointMetricId);
  if(key!==jointSignature())return;if(payload.generated_at!==data.generated_at){await load();return;}
  jointKey=key;jointViews=payload.views;renderMatrix();
 }catch(error){if(key===jointSignature()&&matrixLayout==='joint')$('matrix').innerHTML=`<div class="empty">${esc(error.message)}</div>`;}
 finally{if(jointPending===key)jointPending='';}
}
async function ensureDemo(){
 const key=demoSignature();if(demoReady()||demoPending===key)return;
 demoPending=key;$('demographic-error').hidden=true;
 try{
  const payload=await classificationRequest(mode,activeMetricId());if(key!==demoSignature())return;if(payload.generated_at!==data.generated_at){await load();return;}demoKey=key;demoViews=payload.views;render();
 }catch(error){if(key===demoSignature()){$('demographic-error').hidden=false;$('demographic-error').textContent=error.message;}}
 finally{if(demoPending===key)demoPending='';}
}
function updateView(){if(mode!=='partisan'&&!demoReady())ensureDemo();render();}
function selectDetail(id,b=null){selected=id;bucket=b;page=0;selection=null;Atlas.active=null;Atlas.native=null;if(Atlas.initialized&&Atlas.county!==id)Atlas.showCounty(id,true);window.Navigation?.show('precincts','explore');render();}
function selectPoint(id,index,precinct=null,zoom=true){selected=id;bucket=null;selection={county:id,group_index:index,precinct};page=0;Atlas.update(atlasContext());Atlas.focus(id,index,precinct,zoom);regression();detail();}
function atlasContext(){const bins=new Map();for(const c of data.counties)for(const g of groupRows(c))bins.set(g.id,g.view_bucket);return {data,census,classification:classification(),day,cohort,mode,metric:metric(),bucket,focusCounty:selected,bins,onSelect:selectPoint,onCounty:id=>{selected=id;selection=null;bucket=null;Atlas.ctx=atlasContext();regression();detail();},onClear:()=>{selection=null;bucket=null;Atlas.ctx=atlasContext();regression();detail();}};}
function availableDays(){return window.Navigation?.level==='counties'?Math.max(data?.days||0,window.CountyView?.view?.observed_days||0,window.Tracking?.state?Tracking.stateObserved():0):data?.days||0;}
function renderDayControls(){
 if(!data)return;
 $('days').innerHTML=Array.from({length:availableDays()},(_,i)=>`<button type="button" data-day="${i+1}" aria-pressed="${day===i+1}">Day ${i+1}</button>`).join('');
 $('days').querySelectorAll('button').forEach(b=>b.onclick=()=>{day=+b.dataset.day;page=0;bucket=null;updateView();});
}
function render(){
 if(!data?.counties.length){$('matrix').innerHTML='<div class="empty">Waiting for the first official download…</div>';return;}
 renderDayControls();
 $('partisan-mode').setAttribute('aria-pressed',String(mode==='partisan'));$('demographic-mode').setAttribute('aria-pressed',String(mode==='demographic'));$('primary-mode').setAttribute('aria-pressed',String(mode==='primary'));$('metric').hidden=mode!=='demographic';
 $('period').textContent=dates(comparisonPeriod());
 const failures=data.counties.filter(c=>c.status!=='current'&&(county==='all'||c.id===county));$('source-errors').hidden=!failures.length;$('source-errors-summary').textContent=`${failures.length} ${failures.length===1?'county has':'counties have'} partial or delayed precinct reports`;$('error').hidden=!failures.length;$('error').textContent=failures.map(c=>`${c.name}: ${c.status==='stale'?'using available reported precincts':'data unavailable'} (${c.error||'source not posted'})`).join(' · ');
 renderMatrix();regression();detail();
 Tracking.update({data,day,county,cohort,mode,metric:activeMetricId(),label:metric()?.label});
 Atlas.update(atlasContext());
 window.CountyView?.update();
 $('geography').textContent=data.geography;
 $('census-method').textContent=census?.method||'Census demographic data unavailable.';$('primary-method').textContent=primary?.method||'';
 $('sources').innerHTML='<div class="source-grid">'+data.counties.map(c=>{
  const groups=[['2026',c.sources.filter(s=>s.date.startsWith('2026'))],['2024',c.sources.filter(s=>s.date.startsWith('2024'))]];
  return `<div><h3>${esc(c.name)}</h3>${references?.find(r=>r.id===c.id)?.references?.presidential?.qualification?`<p>${esc(references.find(r=>r.id===c.id).references.presidential.qualification)}</p>`:''}`+groups.map(([year,s])=>s.length?`<p>${year}: `+s.map(v=>`<a href="${esc(v.source)}" target="_blank" rel="noopener">${esc(v.date.slice(5))}${v.cumulative?' cumulative':''}</a>`).join(', ')+`</p><p>${esc([...new Set(s.map(v=>v.note))].join(' '))}</p>`:'').join('')+'</div>';
 }).join('')+'</div>';
}
function renderMatrix(){
 const joint=matrixLayout==='joint';
 $('matrix-layout').querySelectorAll('button').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.matrixLayout===matrixLayout)));
 $('matrix-metric').hidden=!joint;$('matrix-county-controls').hidden=joint;$('matrix-context').hidden=!joint;
 $('matrix').setAttribute('aria-label',joint?'Turnout by demographic and partisan precinct buckets':'County turnout by precinct bucket');
 if(joint){renderJointMatrix();return;}
 $('bucket-title').textContent=mode!=='partisan'?`${metric()?.label||'Census'} precinct buckets`:'2024 presidential margin';
 const allVisible=data.counties.filter(c=>county==='all'||c.id===county),query=$('matrix-search').value.trim().toLowerCase(),filtered=allVisible.filter(c=>c.name.toLowerCase().includes(query)),size=12;matrixPage=Math.min(matrixPage,Math.max(0,Math.ceil(filtered.length/size)-1));const visible=filtered.slice(matrixPage*size,(matrixPage+1)*size);$('matrix-page').textContent=filtered.length?`${matrixPage*size+1}–${Math.min((matrixPage+1)*size,filtered.length)} of ${filtered.length}`:'0 counties';$('matrix-previous').disabled=matrixPage===0;$('matrix-next').disabled=(matrixPage+1)*size>=filtered.length;
 if(mode!=='partisan'&&!demoReady()){downloadReady('download',false);$('matrix').innerHTML='<div class="empty">Loading comparison…</div>';return;}
 const labels=mode!=='partisan'?(demoViews.all?.bins||[]).map(b=>b.label):['Harris 30+','Harris 15–30','Harris 0–15','Trump 0–15','Trump 15–30','Trump 30+'];
 const periods=data.counties.map(period).filter(Boolean),sum=key=>periods.reduce((total,p)=>total+(p[key]||0),0),total2024=sum('county_2024'),total2026=sum('county_2026');
 const totalBins=mode!=='partisan'?demoViews.all?.bins:labels.map((label,i)=>{const b={label,groups:0,votes_2024:0,votes_2026:0};for(const c of data.counties){const source=bucketsFor(c)?.[i];if(source)for(const key of ['groups','votes_2024','votes_2026'])b[key]+=source[key];}return {...b,ratio:b.votes_2024>0?b.votes_2026/b.votes_2024:null};});
 const totalCoverage=periods.length&&periods.every(p=>p.coverage)?periods.reduce((all,p)=>{for(const key of ['available_precincts','total_precincts','baseline_votes_2024','available_baseline_votes_2024'])all[key]+=p.coverage[key];return all;},{available_precincts:0,total_precincts:0,baseline_votes_2024:0,available_baseline_votes_2024:0}):null;
 const totalPeriod=periods.length?{county_2024:total2024,county_2026:total2026,county_ratio:total2024>0?total2026/total2024:null,coverage:totalCoverage,[cohort]:{votes_2024:periods.reduce((n,p)=>n+p[cohort].votes_2024,0)}}:null;
 const columns=[{id:'all',name:'All Counties',total:true,bins:totalBins,period:totalPeriod},...visible.map(c=>({...c,bins:bucketsFor(c),period:period(c)}))];
 let html=`<table style="min-width:calc(var(--matrix-label-width) + var(--matrix-total-width) + ${visible.length*100}px);${visible.length?'':'width:calc(var(--matrix-label-width) + var(--matrix-total-width));'}"><thead><tr><th>${mode!=='partisan'?esc(metric()?.label||'Share')+' (%)':'2024 margin (pp)'}</th>`+columns.map(c=>c.total?'<th class="matrix-total" scope="col">All Counties</th>':`<th><button data-county="${c.id}" aria-label="View ${esc(c.name)} precincts">${esc(c.name)}</button>${c.status==='current'?'':`<span class="stale">${esc(c.status)}</span>`}</th>`).join('')+'</tr></thead><tbody>';
 labels.forEach((label,i)=>{const bg=mode==='partisan'?colors[i]:mode==='primary'?primaryColors[i%5]:demoColors[i%5],dark=mode==='partisan'?(i===0||i===5):mode==='primary'?(i===0||i===4):i===4;html+=`<tr><td class="band" style="background:${bg};color:${dark?'white':'#17212b'}">${esc(label)}</td>`;
  for(const c of columns){const b=c.bins?.[i];if(!b){html+=`<td class="missing${c.total?' matrix-total':''}" title="No complete precinct data for this cutoff">—</td>`;continue;}
   const title=`${c.name}, ${label}: ${number(b.votes_2026)} / ${number(b.votes_2024)} votes; ${b.groups} groups`,ratio=`<span class="ratio">${percent(b.ratio)}${b.ratio!==null&&small(b)?'†':''}</span>`;
   html+=c.total?`<td class="matrix-total" title="${esc(title)}">${ratio}</td>`:`<td><button data-cell="${c.id}:${i}" class="${selected===c.id&&bucket===i?'selected':''}" aria-label="${esc(title)}" title="${esc(title)}">${ratio}</button></td>`;
  }html+='</tr>';
 });
 html+='</tbody><tfoot><tr><td>Matched votes<br>2026 / 2024</td>'+columns.map(c=>{const p=c.period,cls=c.total?' class="matrix-total"':'';return p?`<td${cls}><b>${percent(p.county_ratio)}</b>${number(p.county_2026)} / ${number(p.county_2024)}</td>`:`<td${cls}>Unavailable</td>`;}).join('')+'</tr><tr><td>Matched precincts</td>'+columns.map(c=>{const p=c.period,covered=mode!=='partisan'?demoViews?.[c.id]?.coverage.included.votes_2024:p?.[cohort].votes_2024;return `<td${c.total?' class="matrix-total"':''} title="${p?.coverage?esc(percent(p.coverage.baseline_votes_2024>0?p.coverage.available_baseline_votes_2024/p.coverage.baseline_votes_2024:null)+' of available 2024 baseline votes'):'Classified baseline vote coverage'}">${p?.coverage?number(p.coverage.available_precincts)+' / '+number(p.coverage.total_precincts):p?percent(covered/p.county_2024):'—'}</td>`;}).join('')+'</tr></tfoot></table>';
 $('matrix').innerHTML=html;
 $('matrix').querySelectorAll('[data-county]').forEach(b=>b.onclick=()=>selectDetail(b.dataset.county));$('matrix').querySelectorAll('[data-cell]').forEach(b=>b.onclick=()=>{const [c,i]=b.dataset.cell.split(':');selectDetail(c,+i);});
 if(mode==='partisan'){$('download').href=`/api/export.csv?day=${day}&cohort=${cohort}&county=${county}`;$('download').removeAttribute('download');downloadReady('download',true);}
 else{const rows=[['county','through_2026','through_2024','metric','bucket','cohort','groups','votes_2024','votes_2026','ratio']];for(const c of allVisible)for(const b of bucketsFor(c)||[])rows.push([c.name,period(c)?.through_2026,period(c)?.through_2024,activeMetricId(),b.label,cohort,b.groups,b.votes_2024,b.votes_2026,b.ratio]);bucketUrl=csvLink('download',rows,`${mode}-buckets-${activeMetricId()}-day-${day}.csv`,bucketUrl);}
}
function renderJointMatrix(){
 $('bucket-title').textContent='Demographics × partisanship';
 $('matrix-context').textContent='';
 if(!census){downloadReady('download',false);$('matrix').innerHTML='<div class="empty">Census data unavailable</div>';return;}
 if(!jointReady()){downloadReady('download',false);$('matrix').innerHTML='<div class="empty">Loading comparison…</div>';ensureJoint();return;}
 const view=jointViews[county],matrix=view?.partisan_matrix,m=jointMetric();
 if(!matrix){downloadReady('download',false);$('matrix').innerHTML='<div class="empty">Joint comparison unavailable from this publication</div>';return;}
 const metricLabel=m.label+(m.denominator==='vap'?' age 18+':''),total=view.coverage.included;
 const cell=(value,label,pooled=false)=>{
  const title=`${label}: ${number(value.votes_2026)} / ${number(value.votes_2024)} votes; ${number(value.groups)} groups`;
  let background='';if(!pooled&&value.ratio!==null){const difference=Math.max(-.5,Math.min(.5,value.ratio-1)),rgb=difference<0?'165,95,39':'19,123,138';background=` style="background:rgba(${rgb},${Math.abs(difference)*.55})"`;}
  return `<td${pooled?' class="matrix-total"':''}${background} tabindex="0" aria-label="${esc(title)}" title="${esc(title)}"><span class="ratio">${percent(value.ratio)}${value.ratio!==null&&small(value)?'†':''}</span></td>`;
 };
 let html=`<table class="joint-table" style="min-width:calc(var(--matrix-label-width) + var(--matrix-total-width) + ${matrix.columns.length*110}px)"><thead><tr><th scope="col">${esc(metricLabel)} (%)</th><th class="matrix-total" scope="col">All</th>`+matrix.columns.map((label,i)=>`<th scope="col" style="border-bottom:3px solid ${colors[i]||'#a6afbc'}">${esc(label)}</th>`).join('')+'</tr></thead><tbody>';
 view.bins.forEach((bin,i)=>{html+=`<tr><th class="joint-row" scope="row">${esc(bin.label)}</th>`+cell(bin,`${metricLabel} ${bin.label}, all partisan bands`,true)+matrix.cells[i].map((value,j)=>cell(value,`${metricLabel} ${bin.label}, ${matrix.columns[j]}`)).join('')+'</tr>';});
 html+='</tbody><tfoot><tr><th class="joint-row" scope="row">All</th>'+cell(total,'All demographic and partisan buckets',true)+matrix.totals.map((value,j)=>cell(value,`All demographic buckets, ${matrix.columns[j]}`)).join('')+'</tr></tfoot></table>';
 $('matrix').innerHTML=html;
 const counties=new Set(view.points.map(point=>point.county)).size;
 $('matrix-context').textContent=`${number(total.groups)} precinct groups · ${number(counties)} ${counties===1?'county':'counties'}`;
 $('matrix-context').title=`${number(view.coverage.missing_demographics.groups+view.coverage.invalid_demographics.groups+view.coverage.zero_denominator.groups)} groups lack usable Census counts. Mixed or unknown partisan bands remain in their own column.`;
 const dates=comparisonPeriod(),rows=[['county_scope','through_2026','through_2024','metric','cohort','demographic_bucket','partisan_bucket','groups','votes_2024','votes_2026','ratio']];
 view.bins.forEach((bin,i)=>matrix.cells[i].forEach((value,j)=>rows.push([county,dates.through_2026,dates.through_2024,jointMetricId,cohort,bin.label,matrix.columns[j],value.groups,value.votes_2024,value.votes_2026,value.ratio])));
 bucketUrl=csvLink('download',rows,`demographic-partisan-${jointMetricId}-${county}-day-${day}-${cohort}.csv`,bucketUrl);
}
function detail(){
 const c=data.counties.find(c=>c.id===selected)||data.counties[0],p=period(c),bins=bucketsFor(c);$('detail').hidden=false;$('detail-name').textContent=`${c.name} precincts`;$('clear-filter').hidden=bucket===null;
 $('sort-share').textContent=mode==='partisan'?'Harris %':`${metric()?.label||'Share'} %`;
 if(!p||!bins){$('detail-totals').textContent=!p?'No matched turnout for this cutoff':'Loading comparison…';$('chart').innerHTML='';$('groups').querySelector('tbody').innerHTML='';$('row-count').textContent='';$('page').textContent='';$('previous').disabled=true;$('next').disabled=true;return;}
 $('detail-totals').textContent=`${number(p.county_2026)} / ${number(p.county_2024)} votes${p.coverage?' · '+number(p.coverage.available_precincts)+' / '+number(p.coverage.total_precincts)+' precincts':''}`;
 const max=Math.max(1,...bins.flatMap(b=>[b.votes_2024,b.votes_2026])),mobile=matchMedia('(max-width:550px)').matches,left=mobile?92:117,w=mobile?205:420,viewWidth=mobile?360:630,top=22,row=47;
 let svg=`<svg viewBox="0 0 ${viewWidth} ${bins.length*row+56}" role="img" aria-label="${esc(c.name)} cumulative votes by precinct bucket"><title>${esc(c.name)}: 2024 and 2026 in-person votes</title>`;
 for(let t=0;t<=4;t++){const x=left+w*t/4;svg+=`<line x1="${x}" x2="${x}" y1="12" y2="${bins.length*row+18}" stroke="#e3e9ef"/><text x="${x}" y="${bins.length*row+40}" text-anchor="middle" fill="#66758a" font-size="11">${number(Math.round(max*t/4))}</text>`;}
 bins.forEach((b,i)=>{const y=top+i*row,color=mode==='demographic'?'#137b8a':mode==='primary'?primaryColors[i]:i<3?'#285b91':'#a84236';svg+=`<text x="${left-14}" y="${y+19}" text-anchor="end" fill="#17212b" font-size="12">${esc(b.label)}</text><rect x="${left}" y="${y}" width="${b.votes_2024/max*w}" height="12" fill="#c3ced9"><title>2024: ${number(b.votes_2024)}</title></rect><rect x="${left}" y="${y+16}" width="${b.votes_2026/max*w}" height="12" fill="${color}"><title>2026: ${number(b.votes_2026)}</title></rect><text x="${viewWidth-15}" y="${y+21}" text-anchor="end" font-size="13" fill="#17212b">${percent(b.ratio)}</text>`;});
 $('chart').innerHTML=bins.every(b=>!b.groups)?'<p class="no-data">No classified precinct groups for this view.</p>':'<div class="chart-legend"><span><i style="background:#c3ced9"></i>2024</span><span><i style="background:#2266a7"></i>2026</span></div>'+svg+'</svg>';
 let rows=groupRows(c);if(bucket!==null)rows=rows.filter(g=>g.view_bucket===bucket);
 const search=$('search').value.trim().toUpperCase();if(search)rows=rows.filter(g=>[...g.old,...g.new].join(' ').toUpperCase().includes(search));
 const value=g=>sort==='ratio'?(g.votes_2024?g.votes_2026/g.votes_2024:-1):sort==='share'?(g.share??-1):g[sort];rows.sort((a,b)=>(value(a)-value(b))*(descending?-1:1));
 const size=30;page=Math.min(page,Math.max(0,Math.ceil(rows.length/size)-1));$('row-count').textContent=`${rows.length} groups`;
 $('groups').querySelector('tbody').innerHTML=rows.slice(page*size,(page+1)*size).map(g=>`<tr class="${selection?.county===c.id&&selection.group_index===g.group_index?'selected-row':''}"><td><button class="precinct-link" data-group="${g.group_index}">${esc(g.new.join(', '))}</button>${g.old.join(',')!==g.new.join(',')?`<small>2024: ${esc(g.old.join(', '))}</small>`:''}</td><td>${g.share===null?'—':g.share.toFixed(1)+'%'}</td><td>${number(g.votes_2024)}</td><td>${number(g.votes_2026)}</td><td>${percent(g.votes_2024?g.votes_2026/g.votes_2024:null)}</td></tr>`).join('')||'<tr><td colspan="5">No matching precincts</td></tr>';
 $('groups').querySelectorAll('[data-group]').forEach(b=>b.onclick=()=>{selectPoint(c.id,+b.dataset.group);$('workspace').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});});
 $('page').textContent=rows.length?`${page*size+1}–${Math.min((page+1)*size,rows.length)}`:'0';$('previous').disabled=page===0;$('next').disabled=(page+1)*size>=rows.length;
}
function regression(){
 $('regression').hidden=false;const chart=$('regression-chart'),m=metric(),demo=mode!=='partisan';
 $('regression-title').textContent=demo?`${m?.label||'Demographic'} share`:'Harris vote share';
 let summary=demo?(demoReady()?demoViews[county]:null):data.regressions?.find(r=>r.day===day&&r.county===county&&r.cohort===cohort);
 const allPoints=data.counties.filter(c=>county==='all'||c.id===county).flatMap(c=>groupRows(c).filter(g=>g.votes_2024>0&&g.share!==null).map(g=>({county:c.name,countyId:c.id,id:g.id,group:g.group_index,precincts:g.new.join(';'),old:g.old.join(';'),bucket:g.view_bucket,x:g.share,y:100*g.votes_2026/g.votes_2024,oldVotes:g.votes_2024,newVotes:g.votes_2026,harrisShare:presidentialShare(c,g)})));
 const winner=demo?regressionWinner:'all',points=RegressionCohort.select(allPoints,winner),fit=winner==='all'?summary?.fit:RegressionCohort.fit(points);
 $('regression-winner').hidden=!demo;for(const button of $('regression-winner').querySelectorAll('button'))button.setAttribute('aria-pressed',String(button.dataset.regressionWinner===regressionWinner));
 $('regression-stats').innerHTML=`<span>${fit?'OLS':'Fit unavailable'}</span><span>n = ${number(points.length)}</span>${fit?`<span>R² = ${fit.r_squared===null?'—':fit.r_squared.toFixed(3)}</span>`:''}${demo?'<span class="partisan-key" aria-label="2024 two-party winner"><span><i style="background:#a84236"></i>Trump</span><span><i style="background:#285b91"></i>Harris</span></span>':''}`;
 if(!demo||demoReady())regressionUrl=csvLink('regression-download',[['county','precincts_2026','precincts_2024',demo?activeMetricId()+'_pct':'harris_share_2024_pct','turnout_2026_as_pct_2024','votes_2024','votes_2026',...(demo?['harris_share_2024_pct']:[])],...points.map(p=>[p.county,p.precincts,p.old,p.x,p.y,p.oldVotes,p.newVotes,...(demo?[p.harrisShare]:[])])],`turnout-regression-${county}-day-${day}-${cohort}${demo?'-'+activeMetricId()+'-'+winner:''}.csv`,regressionUrl);else downloadReady('regression-download',false);
 if(!points.length){chart.innerHTML=`<p class="no-data">${demo&&!demoReady()?'Loading comparison…':'No comparable precinct groups with a 2024 baseline for this selection.'}</p>`;$('point-readout').textContent='';return;}
 const mobile=matchMedia('(max-width:550px)').matches,width=Math.max(340,Math.min(1400,chart.clientWidth)),height=mobile?350:420,left=mobile?59:68,right=16,top=18,bottom=52,pw=width-left-right,ph=height-top-bottom;
 const scale=RegressionScale.calculate(points.map(p=>p.y),$('regression-scale').value),{step,min:ymin,max:ymax}=scale;
 const x=v=>left+v/100*pw,y=v=>top+ph-(v-ymin)/(ymax-ymin)*ph;
 const outside=scale.below+scale.above,referenceVisible=ymin<=100&&ymax>=100,split=Math.max(top,Math.min(top+ph,y(100)));
 const quads=[{id:'trump-above',color:'#a84236',left:0,above:true},{id:'trump-below',color:'#96641b',left:0,above:false},{id:'harris-above',color:'#285b91',left:50,above:true},{id:'harris-below',color:'#007f99',left:50,above:false}];
 const xLabel=demo?`${m?.label||'Demographic'} ${m?.denominator==='vap'?'age 18+ ':''}(%)`:'2024 Harris vote share (%)';
 let svg=`<svg viewBox="0 0 ${width} ${height}" data-y-min="${ymin}" data-y-max="${ymax}" data-scale="${scale.mode}" role="group" aria-labelledby="regression-svg-title regression-svg-description"><title id="regression-svg-title">Cumulative turnout versus ${demo?esc(m?.label||'demographic share'):'2024 Harris vote share'}</title><desc id="regression-svg-description">${RegressionCohort.label(winner)}. ${points.length} comparable precinct groups. Points select and zoom the associated map polygons. Arrow keys move between points; Enter selects. ${demo?'Dot colors show the 2024 two-party winner: Harris blue, Trump red; ties or missing presidential votes are neutral.':'Quadrants split at 50% share and 100% of 2024 turnout.'} ${scale.mode==='full'?'Full turnout range.':`Vertical view: ${ymin}–${ymax}% of 2024${scale.mode==='auto'?', automatically scaled around the main cluster':''}. ${outside} points fall outside the view; choose Full range to see them.`} All eligible observations remain in OLS and CSV; the line spans observed values. Data is available in Points CSV.</desc><defs><clipPath id="regression-clip"><rect x="${left}" y="${top}" width="${pw}" height="${ph}"/></clipPath></defs>`;
 if(outside)svg+=`<text class="regression-outside" x="${width-right}" y="11" text-anchor="end" fill="#66758a" font-size="10">${number(outside)} outside view</text>`;
 if(!demo)for(const q of quads)svg+=`<rect class="regression-quadrant" data-quadrant="${q.id}" x="${x(q.left)}" y="${q.above?top:split}" width="${pw/2}" height="${q.above?split-top:top+ph-split}" fill="${q.color}" fill-opacity=".035"/>`;
 for(let i=0;i<=4;i++){const value=i*25,px=x(value);svg+=`<line x1="${px}" x2="${px}" y1="${top}" y2="${top+ph}" stroke="#e3e9ef"/><text x="${px}" y="${top+ph+21}" text-anchor="middle" fill="#66758a" font-size="11">${value}%</text>`;}
 for(const value of scale.ticks){const py=y(value);svg+=`<line x1="${left}" x2="${width-right}" y1="${py}" y2="${py}" stroke="#e3e9ef"/><text x="${left-9}" y="${py+4}" text-anchor="end" fill="#66758a" font-size="11">${number(value)}%</text>`;}
 svg+=`<line class="regression-share-reference" x1="${x(50)}" x2="${x(50)}" y1="${top}" y2="${top+ph}" stroke="#66758a" stroke-dasharray="5 4"/>`;
 if(referenceVisible&&!scale.ticks.includes(100))svg+=`<text x="${left-9}" y="${y(100)+4}" text-anchor="end" fill="#66758a" font-size="11">100%</text>`;
 if(referenceVisible)svg+=`<line class="regression-reference" x1="${left}" x2="${width-right}" y1="${y(100)}" y2="${y(100)}" stroke="#7c8b97" stroke-dasharray="5 4"/>`;svg+=`<g clip-path="url(#regression-clip)">`;
 const activeId=selection?`${selection.county}:${selection.group_index}`:null,hasActive=points.some(p=>p.id===activeId&&p.y>=ymin&&p.y<=ymax),firstVisible=points.findIndex(p=>p.y>=ymin&&p.y<=ymax);
 points.forEach((p,index)=>{const q=quads[(p.x>=50?2:0)+(p.y>=100?0:1)],party=p.harrisShare===null?'unknown':p.harrisShare>50?'harris':p.harrisShare<50?'trump':'tie',fill=demo?(party==='harris'?'#285b91':party==='trump'?'#a84236':'#77818e'):q.color,active=p.id===activeId,inView=p.y>=ymin&&p.y<=ymax,dim=bucket!==null&&(p.countyId!==selected||p.bucket!==bucket),title=`${p.county}: ${p.precincts.replaceAll(';',', ')} | ${demo?m?.label:'Harris'} ${p.x.toFixed(1)}%${demo?' | 2024 Harris '+(p.harrisShare===null?'—':p.harrisShare.toFixed(1)+'%'):''} | Turnout ${p.y.toFixed(1)}% (${number(p.newVotes)} / ${number(p.oldVotes)})`;
  svg+=`<circle class="regression-point${active?' active-point':''}" role="button" tabindex="${inView&&(active||(!hasActive&&index===firstVisible))?0:-1}" aria-hidden="${!inView}" aria-label="${esc(title)}" data-id="${p.id}" data-county="${p.countyId}" data-group="${p.group}" data-index="${index}" ${demo?`data-party="${party}" data-harris-share="${p.harrisShare??''}"`:`data-quadrant="${q.id}"`} data-x="${p.x}" data-y="${p.y}" cx="${x(p.x)}" cy="${y(p.y)}" r="${active?5:3.2}" fill="${fill}" fill-opacity="${dim?.16:.85}" stroke="${active?'#713bc2':'white'}" stroke-width="${active?2.2:.35}"><title>${esc(title)}</title></circle>`;
 });
 if(fit)svg+=`<line class="regression-fit" data-slope="${fit.slope}" data-intercept="${fit.intercept}" x1="${x(fit.x_min)}" x2="${x(fit.x_max)}" y1="${y(fit.intercept+fit.slope*fit.x_min)}" y2="${y(fit.intercept+fit.slope*fit.x_max)}" stroke="#17212b" stroke-width="2.2"><title>OLS: y = ${fit.intercept.toFixed(3)} ${fit.slope<0?'−':'+'} ${Math.abs(fit.slope).toFixed(3)}x</title></line>`;
 svg+=`</g><text x="${left+pw/2}" y="${height-8}" text-anchor="middle" fill="#17212b" font-size="12">${esc(xLabel)}</text><text transform="translate(17 ${top+ph/2}) rotate(-90)" text-anchor="middle" fill="#17212b" font-size="12">Cumulative turnout (% of 2024)</text></svg>`;chart.innerHTML=svg;
 const circles=[...chart.querySelectorAll('.regression-point')];
 const keyboardCircles=circles.filter(c=>c.getAttribute('aria-hidden')!=='true');
 const activeCircle=chart.querySelector('.active-point');if(activeCircle)activeCircle.parentNode.appendChild(activeCircle);
 for(const circle of circles){const point=points[+circle.dataset.index],readout=()=>{$('point-readout').textContent=`${point.county} / ${point.precincts.replaceAll(';',', ')} / ${point.y.toFixed(1)}% of 2024`;};circle.onclick=()=>selectPoint(point.countyId,point.group);circle.onpointerenter=()=>{readout();Atlas.hover(point.countyId,point.group);};circle.onpointerleave=()=>Atlas.hover(null,null);circle.onfocus=()=>{readout();Atlas.hover(point.countyId,point.group);};circle.onblur=()=>Atlas.hover(null,null);circle.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectPoint(point.countyId,point.group);}else if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();const next=(keyboardCircles.indexOf(circle)+(['ArrowLeft','ArrowUp'].includes(e.key)?-1:1)+keyboardCircles.length)%keyboardCircles.length;circles.forEach(c=>c.tabIndex=-1);keyboardCircles[next]?.setAttribute('tabindex','0');keyboardCircles[next]?.focus();}};}
 if(selection){const point=points.find(p=>p.id===activeId);$('point-readout').textContent=point?`${point.county} / ${point.precincts.replaceAll(';',', ')} / ${point.y.toFixed(1)}% of 2024`:'';}else $('point-readout').textContent='';
}
// Qualification can change without a new source snapshot timestamp.
function invalidateComparisonViews(){
 dataEpoch++;demoKey='';demoViews=null;jointKey='';jointViews=null;classificationPending.clear();
 if(window.Tracking){Tracking.key='';Tracking.stateKey='';}
 if(window.CountyView)CountyView.key='';
}
async function load(){
 try{const response=await fetch('/api/data',{cache:'no-store'});if(!response.ok)throw Error(`HTTP ${response.status}`);const incoming=await response.json(),first=!data;data=incoming;
  if(first){day=data.days||4;$('county').innerHTML='<option value="all">All precinct counties</option>'+data.counties.map(c=>`<option value="${c.id}">${esc(c.name)}</option>`).join('');try{const results=await Promise.all([fetch('/api/demographics'),fetch('/api/primary'),fetch('/api/reference')]);if(results[0].ok)census=await results[0].json();if(results[1].ok)primary=await results[1].json();if(results[2].ok){references=await results[2].json();referenceByCounty=new Map(references.map(r=>[r.id,r]));}}catch(_){}$('primary-mode').disabled=!primary;if(census){$('metric').innerHTML=census.metrics.map(m=>`<option value="${m.id}">${esc(m.label)}${m.denominator==='vap'?' age 18+':''}</option>`).join('');$('metric').value=metricId;$('matrix-metric').innerHTML=census.metrics.map(m=>`<option value="${m.id}">${esc(m.label)}${m.denominator==='vap'?' age 18+':''}</option>`).join('');$('matrix-metric').value=jointMetricId;}else{$('demographic-mode').disabled=true;$('demographic-mode').title='Census data unavailable';}}
  if(data.generated_at)$('sync').textContent=`Updated ${new Date(data.generated_at).toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit',timeZoneName:'short'})}`;
  invalidateComparisonViews();updateView();
 }catch(error){$('error').hidden=false;$('error').textContent=`Download unavailable: ${error.message}. Retrying automatically.`;}
}
$('county').onchange=e=>{county=e.target.value;matrixPage=0;$('matrix-search').value='';if(county!=='all'){selected=county;selection=null;Atlas.active=null;Atlas.native=null;if(Atlas.initialized)Atlas.showCounty(county,true);}bucket=null;page=0;updateView();};
$('partisan-mode').onclick=()=>{mode='partisan';bucket=null;page=0;$('demographic-error').hidden=true;render();};$('primary-mode').onclick=()=>{mode='primary';bucket=null;page=0;if(county==='all'&&!Object.keys(primary?.counties?.[Atlas.county]?.precincts||{}).length){const id=data.counties.find(c=>Object.keys(primary?.counties?.[c.id]?.precincts||{}).length)?.id;if(id){selected=id;selection=null;Atlas.active=null;Atlas.native=null;if(Atlas.initialized)Atlas.showCounty(id,true);}}updateView();};$('demographic-mode').onclick=()=>{mode='demographic';bucket=null;page=0;updateView();};$('metric').onchange=e=>{metricId=e.target.value;bucket=null;page=0;updateView();};$('cohort').onchange=e=>{cohort=e.target.value;bucket=null;page=0;updateView();};
$('regression-scale').onchange=()=>regression();
$('regression-winner').onclick=event=>{const button=event.target.closest('[data-regression-winner]');if(button){regressionWinner=button.dataset.regressionWinner;regression();}};
$('matrix-layout').onclick=event=>{const button=event.target.closest('[data-matrix-layout]');if(button){matrixLayout=button.dataset.matrixLayout;renderMatrix();}};
$('matrix-metric').onchange=event=>{jointMetricId=event.target.value;renderMatrix();};
$('matrix-search').oninput=()=>{matrixPage=0;renderMatrix();};$('matrix-previous').onclick=()=>{matrixPage--;renderMatrix();};$('matrix-next').onclick=()=>{matrixPage++;renderMatrix();};
$('search').oninput=()=>{page=0;detail();};$('clear-filter').onclick=()=>{bucket=null;page=0;render();};$('previous').onclick=()=>{page--;detail();};$('next').onclick=()=>{page++;detail();};
for(const [id,key]of [['sort-share','share'],['sort-2024','votes_2024'],['sort-2026','votes_2026'],['sort-ratio','ratio']])$(id).onclick=()=>{descending=sort===key?!descending:true;sort=key;page=0;detail();};
$('refresh').onclick=async()=>{try{const r=await fetch('/api/refresh',{method:'POST'});if(!r.ok&&r.status!==409)throw Error(`HTTP ${r.status}`);$('sync').textContent='Refreshing…';$('refresh').disabled=true;await refreshStatus(true);}catch(e){$('error').hidden=false;$('error').textContent=`Refresh failed: ${e.message}`;}};
async function refreshStatus(manual=false){try{const r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)return;const s=await r.json();$('refresh').disabled=s.updating;if(s.updating){$('sync').textContent='Refreshing…';if(manual)setTimeout(()=>refreshStatus(true),5000);}else if(s.generated_at!==data?.generated_at)await load();}catch(_){} }
setInterval(load,3600000);load();
window.addEventListener('resize',()=>{if(data){regression();detail();}});
