'use strict';
// Geography and classification are separate choices. Each workspace keeps its filters.
const Navigation=window.Navigation={
 level:'counties',section:'trends',
 show(level,section=this.section,write=true){
  this.level=level;this.section=section;
  $('county-workspace').hidden=level!=='counties';$('precinct-workspace').hidden=level!=='precincts';
  $('counties-tab').setAttribute('aria-pressed',String(level==='counties'));$('precincts-tab').setAttribute('aria-pressed',String(level==='precincts'));
  $('precinct-trends').hidden=section!=='trends';$('precinct-explore').hidden=section!=='explore';
  $('precinct-trends-tab').setAttribute('aria-pressed',String(section==='trends'));$('precinct-explore-tab').setAttribute('aria-pressed',String(section==='explore'));
  if(write)history.replaceState(null,'',level==='counties'?'#counties':'#precinct-'+section);
  window.dispatchEvent(new Event('resize'));
  if(data){const limit=availableDays();if(day>limit){day=limit;page=0;bucket=null;updateView();}else renderDayControls();}
  if(level==='counties')CountyView.update();
 },
 init(){
  $('counties-tab').onclick=()=>this.show('counties');$('precincts-tab').onclick=()=>this.show('precincts');
  $('precinct-trends-tab').onclick=()=>this.show('precincts','trends');$('precinct-explore-tab').onclick=()=>this.show('precincts','explore');
  const read=()=>this.show(location.hash.startsWith('#precinct-')?'precincts':'counties',location.hash==='#precinct-explore'?'explore':'trends',false);
  window.addEventListener('hashchange',read);read();
 }
};
const CountyView=window.CountyView={
 votingMethod:'total',mode:'partisan',metricId:'hispanic_vap',measure:'daily',bucket:null,view:null,key:'',pending:'',download:null,
 metric(){return this.mode==='place'?places?.metrics[0]:census?.metrics.find(m=>m.id===this.metricId);},
 label(){const m=this.metric();return this.mode==='place'?'Place type':this.mode==='partisan'?'2024 presidential margin':`${m?.label||'Demographic'}${m?.denominator==='vap'?' age 18+':''}`;},
 color(i){return this.mode==='place'?placeColors[i]:this.mode==='partisan'?['#285b91','#4d80b4','#6e9cc7','#d18a7d','#be6658','#a84236'][i]:'#137b8a';},
 signature(){return data?`${data.generated_at}|${day}|${this.mode}|${this.metricId}|${this.votingMethod}|${dataEpoch}`:'';},
 ready(){return this.view&&this.key===this.signature()&&(!this.pending||this.pending===this.key);},
 async update(){
  if(!data)return;
  $('precinct-county-count').textContent=`${data.counties.length} counties`;
  if(census&&!$('county-metric').options.length){$('county-metric').innerHTML=census.metrics.map(m=>`<option value="${m.id}">${esc(m.label)}${m.denominator==='vap'?' age 18+':''}</option>`).join('');$('county-metric').value=this.metricId;}
  $('county-partisan').setAttribute('aria-pressed',String(this.mode==='partisan'));$('county-demographic').setAttribute('aria-pressed',String(this.mode==='demographic'));$('county-place').setAttribute('aria-pressed',String(this.mode==='place'));$('county-metric').hidden=this.mode!=='demographic';$('county-classification-label').textContent=this.mode==='place'?'NCES 2025 · 2020 Census age 18+':this.mode==='partisan'?'2024 presidential margin':'2020 Census';
  const key=this.signature();
  if(this.key===key&&this.view){this.render();return;}if(this.pending===key)return;
  this.pending=key;this.view=null;downloadReady('county-bucket-download',false);$('county-daily-charts').innerHTML='<div class="empty">Loading matched comparisons…</div>';$('county-bucket-summary').innerHTML='';$('county-bucket-coverage').textContent='';$('county-summary-cutoff').textContent='';Tracking.clearState();window.Visuals?.sync();$('county-workspace').setAttribute('aria-busy','true');$('county-error').hidden=true;
  try{
   const response=await fetch('/api/county-buckets?'+new URLSearchParams({view:this.mode,metric:this.mode==='place'?'place_type':this.mode==='partisan'?'presidential_margin':this.metricId,day,method:this.votingMethod})),value=await response.json();
   if(!response.ok)throw Error(value.error||'County buckets unavailable');if(this.pending!==key)return;
   this.view=value;this.key=key;this.render();
  }catch(error){if(this.pending===key){$('county-error').textContent=error.message;$('county-error').hidden=false;}}
  finally{if(this.pending===key){this.pending='';$('county-workspace').setAttribute('aria-busy','false');}}
 },
 includes(id){if(this.bucket===null||!this.view)return true;return this.view.counties.some(c=>c.id===id&&c.bucket===this.bucket);},
 selectBucket(index){this.bucket=this.bucket===index?null:index;Tracking.stateCounty='all';this.render();},
 decorateState(){
  if(!this.view)return;
  const map=new Map(this.view.counties.map(c=>[c.id,c]));
  $('statewide-table').querySelectorAll('[data-state-county]').forEach(button=>{const c=map.get(button.dataset.stateCounty);if(c?.bucket!==null&&c?.bucket!==undefined){const dot=document.createElement('i');dot.className='county-class-dot';dot.style.background=this.color(c.bucket);button.prepend(dot);}});
 },
 render(){
  if(!this.ready()||!Tracking.ctx)return;
  renderDayControls();
  const buckets=this.view.buckets,panels=buckets.length===5?[...buckets,this.view.totals]:buckets,isDaily=this.measure==='daily',membership=isDaily?'groups':'cumulative_groups';
  $('county-daily-title').textContent=`${isDaily?'Same-day':'Cumulative'} turnout by county bucket`;
  $('county-daily-section').dataset.mode=this.mode;
  const count=buckets.reduce((n,b)=>n+b[membership],0),total=this.view.counties.length;
  $('county-bucket-coverage').textContent=`${count} of ${total} counties · ${isDaily?'Same-day':'Cumulative'} 2026 as % of 2024`;
  $('county-bucket-coverage').title=this.view.method||'';
  $('county-bucket-method').textContent=[this.view.method,this.view.reference_method,...new Set((this.view.reference_sources||[]).map(s=>s.transport_note).filter(Boolean))].filter(Boolean).join(' ');
  $('county-reference-sources').innerHTML=(this.view.reference_sources||[]).map(source=>`<a href="${esc(source.url||source.original_url||'#')}" target="_blank" rel="noopener">${esc(source.label||source.name||source.path?.split('/').pop()||'County classifications')}</a>${source.transport_url?` (<a href="${esc(source.transport_url)}" target="_blank" rel="noopener">preserved source</a>)`:''}`).join(' · ');
  $('county-daily-charts').innerHTML=panels.map((b,i)=>{
   const rows=Tracking.values(b.days,this.measure,false,this.view.observed_days,'counties'),latest=rows.find(d=>d.day===day),color=b.id==='total'?'#334155':this.color(i),ratio=latest?.a>0&&latest?.b!==null&&latest?.b!==undefined?percent(latest.b/latest.a):'—';
   return `<section class="county-daily-panel${b.id==='total'?' total-panel':''}${this.bucket===i?' bucket-active':''}"><div class="daily-panel-heading"><h3>${b.id==='total'?esc(b.label):`<button type="button" data-county-bucket="${i}" aria-pressed="${this.bucket===i}"><i style="background:${color}"></i>${esc(b.label)}</button>`}</h3><span>${number(latest?.groupCount??b[membership])} ${(latest?.groupCount??b[membership])===1?'county':'counties'}</span><b title="${isDaily?'Same-day':'Cumulative'} 2026 as % of 2024">${ratio}</b></div>${Tracking.chart(rows,color,'county-'+i,false,this.measure,this.view.observed_days)}</section>`;
  }).join('');
  $('county-daily-charts').querySelectorAll('.county-daily-panel').forEach((panel,i)=>Tracking.bindChart(panel,Tracking.values(panels[i].days,this.measure,false,this.view.observed_days,'counties'),panels[i].label,'county-bucket-readout'));
  $('county-bucket-readout').textContent='';$('county-summary-cutoff').textContent=`${this.view.coverage.cumulative_groups} counties · Day ${day} · Cumulative 2026 as % of 2024`;$('county-bucket-clear').hidden=this.bucket===null;$('statewide-title').textContent=this.bucket===null?'Texas counties':this.view.buckets[this.bucket].label+' counties';
  const sums=buckets.map(b=>Tracking.paired(b.days,false,this.view.observed_days).find(d=>d.day===day)),max=Math.max(1,...sums.flatMap(d=>[d?.cumulative_2024,d?.cumulative_2026]).filter(v=>v!==null&&v!==undefined));
  $('county-bucket-summary').innerHTML=buckets.map((b,i)=>{
   const d=sums[i],old=d?.cumulative_2024,newVotes=d?.cumulative_2026,color=this.color(i),ratio=old>0&&Number.isFinite(newVotes)?percent(newVotes/old):'—',vote=v=>v===null||v===undefined?'—':number(v);
   return `<button type="button" class="county-summary-bucket${this.bucket===i?' bucket-active':''}" data-county-bucket="${i}" aria-pressed="${this.bucket===i}" aria-label="${esc(b.label)}, ${b.cumulative_groups} counties, 2026 ${vote(newVotes)} votes, 2024 ${vote(old)} votes, ${ratio} of 2024"><div class="bucket-summary-heading"><span><i style="background:${color}"></i>${esc(b.label)}</span><b>${ratio}</b></div><div class="bucket-bar-old" style="width:${(old??0)/max*100}%"></div><div class="bucket-bar-new" style="width:${(newVotes??0)/max*100}%;background:${color}"></div><div class="bucket-summary-votes"><span>2024 <strong>${vote(old)}</strong></span><span>2026 <strong>${vote(newVotes)}</strong></span></div><span class="bucket-county-count">${b.cumulative_groups} ${b.cumulative_groups===1?'county':'counties'}</span></button>`;
  }).join('');
  document.querySelectorAll('[data-county-bucket]').forEach(button=>button.onclick=()=>this.selectBucket(+button.dataset.countyBucket));
  const rows=[['geography','view','metric','method','bucket','daily_counties','cumulative_counties','day','date_2024','date_2026','daily_2024','daily_2026','cumulative_2024','cumulative_2026','daily_county_ids','cumulative_county_ids']];
  for(const b of panels)for(const d of Tracking.paired(b.days,false,this.view.observed_days))rows.push(['county',this.mode,this.mode==='partisan'?'presidential_margin':this.metricId,this.votingMethod,b.label,d.groups??d.daily_groups??b.groups,d.cumulative_groups??b.cumulative_groups,d.day,d.date_2024,d.date_2026,d.daily_2024,d.daily_2026,d.cumulative_2024,d.cumulative_2026,(d.county_ids||[]).join(';'),(d.cumulative_county_ids||[]).join(';')]);
  this.download=csvLink('county-bucket-download',rows,`county-buckets-${this.mode}-${this.mode==='partisan'?'presidential':this.metricId}.csv`,this.download);
  if(Tracking.state)Tracking.renderState();window.Visuals?.sync();
 },
 init(){
  $('county-method').onchange=e=>{this.votingMethod=e.target.value;this.bucket=null;this.update();if(Tracking.ctx)Tracking.update(Tracking.ctx);};
  $('county-partisan').onclick=()=>{this.mode='partisan';this.bucket=null;this.update();};$('county-demographic').onclick=()=>{this.mode='demographic';this.bucket=null;this.update();};
  $('county-place').onclick=()=>{this.mode='place';this.bucket=null;this.update();};
  $('county-metric').onchange=e=>{this.metricId=e.target.value;this.bucket=null;this.update();};$('county-bucket-measure').onchange=e=>{this.measure=e.target.value;this.render();};$('county-bucket-clear').onclick=()=>{this.bucket=null;this.render();};
 }
};
CountyView.init();Navigation.init();
