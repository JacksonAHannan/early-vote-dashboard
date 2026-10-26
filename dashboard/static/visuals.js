'use strict';
// Panel state and client-side share cards. No source requests or external assets.
const Visuals=window.Visuals={
 social:{name:'Jackson Hannan',x:'@electionsjack',xUrl:'https://x.com/electionsjack',linkedin:'linkedin.com/in/jackson-hannan',linkedinUrl:'https://www.linkedin.com/in/jackson-hannan',dashboard:'https://jacksonahannan.github.io/early-vote-dashboard/'},
 storageKey:'texas-turnout:collapsed:v1',collapsed:new Set(),busy:false,queued:false,
 panels:[
  ['county-daily-section','.section-heading','County bucket timelines','county-daily'],
  ['county-summary-section','.section-heading','County bucket comparison','county-summary'],
  ['daily-section','.section-heading','Precinct bucket timelines','daily'],
  ['map-panel','.panel-heading','Map','map'],
  ['regression','.regression-heading','Turnout regression','regression'],
  ['selection-panel','.profile-heading','Precinct profile','profile'],
  ['bucket-section','.section-heading','Precinct buckets','matrix'],
  ['detail','.detail-title','County precincts',null],
  ['statewide-section','.section-heading','Texas counties',null]
 ],
 init(){
  try{const saved=JSON.parse(localStorage.getItem(this.storageKey)||'[]');if(Array.isArray(saved))this.collapsed=new Set(saved.filter(id=>this.panels.some(p=>p[0]===id)));}catch(_){}
  const map=document.querySelector('.map-panel');if(map)map.id='map-panel';
  for(const [id,selector,label,image]of this.panels){
   const root=$(id),heading=root?.querySelector(selector);if(!heading)continue;
   root.dataset.collapsible=id;
   const body=document.createElement('div');body.id=id+'-body';body.className='panel-body';
   for(const child of [...root.children])if(child!==heading)body.append(child);
   root.append(body);
   const actions=document.createElement('div');actions.className='panel-tools';
   if(image)actions.append(this.imageButton(image,`Export ${label.toLowerCase()} as PNG`));
   const button=document.createElement('button');button.type='button';button.className='panel-toggle';button.dataset.panel=id;button.setAttribute('aria-controls',body.id);button.innerHTML='<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4"/></svg>';actions.append(button);heading.append(actions);
   this.applyPanel(id);
  }
  const bulk=document.createElement('div');bulk.className='panel-bulk';bulk.innerHTML='<button type="button" data-panels="collapse">Collapse all</button><button type="button" data-panels="expand">Expand all</button>';
  document.querySelector('.controls').append(bulk);
  const status=document.createElement('div');status.id='image-status';status.className='image-status';status.setAttribute('role','status');status.setAttribute('aria-live','polite');document.body.append(status);
  document.addEventListener('click',event=>{
   const toggle=event.target.closest('[data-panel]');if(toggle){this.toggle(toggle.dataset.panel);return;}
   const all=event.target.closest('[data-panels]');if(all){Motion.finish();if(all.dataset.panels==='collapse'&&Atlas.map&&!this.collapsed.has('map-panel'))this.mapView={center:Atlas.map.getCenter(),zoom:Atlas.map.getZoom(),county:Atlas.county};for(const [id]of this.panels)if($(id).getBoundingClientRect().width)all.dataset.panels==='collapse'?this.collapsed.add(id):this.collapsed.delete(id);this.save();for(const [id]of this.panels)this.applyPanel(id);this.reflow();return;}
   const image=event.target.closest('[data-image]');if(image)this.download(image.dataset.image,image);
  });
  new MutationObserver(()=>{if(!this.queued){this.queued=true;queueMicrotask(()=>{this.queued=false;this.sync();});}}).observe(document.querySelector('main'),{childList:true,subtree:true});
  this.sync();
 },
 imageButton(key,label){const b=document.createElement('button');b.type='button';b.className='image-export';b.dataset.image=key;b.textContent='PNG ↓';b.title=label;b.setAttribute('aria-label',label);return b;},
 save(){try{localStorage.setItem(this.storageKey,JSON.stringify([...this.collapsed]));}catch(_){}},
 applyPanel(id){const root=$(id),closed=this.collapsed.has(id),label=this.panels.find(p=>p[0]===id)[2],button=root.querySelector('[data-panel]');root.classList.toggle('is-collapsed',closed);const body=$(id+'-body'),wasHidden=body.hidden;body.hidden=closed;if(wasHidden&&!closed)Motion.reveal(body);button.setAttribute('aria-expanded',String(!closed));button.setAttribute('aria-label',`${closed?'Expand':'Collapse'} ${label.toLowerCase()}`);button.title=button.getAttribute('aria-label');},
 toggle(id){Motion.finish();if(!this.collapsed.has('map-panel')&&Atlas.map)this.mapView={center:Atlas.map.getCenter(),zoom:Atlas.map.getZoom(),county:Atlas.county};this.collapsed.has(id)?this.collapsed.delete(id):this.collapsed.add(id);this.save();this.applyPanel(id);this.reflow();},
 reflow(){requestAnimationFrame(()=>{window.dispatchEvent(new Event('resize'));requestAnimationFrame(()=>{if(Atlas.map&&!this.collapsed.has('map-panel')){Atlas.map.invalidateSize({pan:false});if(this.mapView){if(this.mapView.county===Atlas.county)Atlas.map.setView(this.mapView.center,this.mapView.zoom,{animate:false});else if(Atlas.layer){if(Atlas.active?.county===Atlas.county)Atlas.zoomGroup(Atlas.active.group_index,Atlas.native,false);else Atlas.map.fitBounds(Atlas.layer.getBounds(),{padding:[24,24],animate:false});}this.mapView=null;}}});});},
 addImage(selector,key,label){const heading=document.querySelector(selector);if(heading&&!heading.querySelector(`[data-image="${key}"]`))heading.append(this.imageButton(key,label));},
 sync(){
  document.querySelectorAll('.daily-panel').forEach((panel,index)=>{const heading=panel.querySelector('.daily-panel-heading');if(!heading.querySelector('[data-image]'))heading.append(this.imageButton('daily-'+index,`Export ${heading.querySelector('h3').textContent} as PNG`));});
  document.querySelectorAll('.county-daily-panel').forEach((panel,index)=>{const heading=panel.querySelector('.daily-panel-heading');if(!heading.querySelector('[data-image]'))heading.append(this.imageButton('county-daily-'+index,`Export ${heading.querySelector('h3').textContent} county turnout as PNG`));});
  this.addImage('.census-profile .subheading','demographics','Export resident composition as PNG');
  this.addImage('.trend-panel .subheading','precinct-trend','Export precinct cumulative turnout as PNG');
  if($('chart')&&!document.querySelector('[data-image="bucket-bars"]')){const tools=document.createElement('div');tools.className='visual-tools';tools.append(this.imageButton('bucket-bars','Export county bucket chart as PNG'));$('chart').before(tools);tools.append($('chart'));}
  this.addImage('#detail .search-row','precinct-table','Export precinct table as PNG');
  this.addImage('.statewide-list .search-row','county-table','Export county table as PNG');
  this.addImage('.statewide-heading','county-trend','Export county turnout chart as PNG');
  document.querySelectorAll('[data-image]').forEach(button=>button.disabled=this.busy||!this.ready(button.dataset.image));
 },
 status(message,error=false){const node=$('image-status');node.textContent=message;node.classList.toggle('image-failed',error);clearTimeout(this.statusTimer);this.statusTimer=setTimeout(()=>node.textContent='',error?10000:4500);},
 scope(){return county==='all'?'All precinct counties':data.counties.find(c=>c.id===county)?.name||county;},
 classification(){return mode==='place'?'Place type · 2020 residents age 18+':mode==='partisan'?'2024 presidential margin':metric()?.label+(metric()?.denominator==='vap'?' · age 18+':'');},
 ready(key){
  if(!data)return false;
  if(key.startsWith('county-')||key==='counties')return CountyView.ready()&&(!['county-table','county-trend','counties'].includes(key)||Tracking.stateReady());
  if(key==='matrix'&&matrixLayout==='joint')return Boolean(jointReady()&&jointViews[county]?.partisan_matrix);
  if(key==='daily'||key.startsWith('daily-'))return Boolean(Tracking.view&&Tracking.key===Tracking.signature());
  if(key==='map')return Boolean(Atlas.layer&&$('map-loading').hidden&&(mode==='partisan'||demoReady()));
  if(['profile','demographics','precinct-trend'].includes(key))return $('selection-panel').dataset.county===Atlas.county;
  return mode==='partisan'||demoReady();
 },
 descriptor(key){
  if(!this.ready(key))throw Error('Wait for the selected comparison to finish loading.');
  const title=id=>$(id)?.textContent||'',countyMethod=({total:'Mail + in person',in_person:'In person',mail:'Mail'})[window.CountyView?.votingMethod||'total'],scope=this.scope(),classification=this.classification(),selectedTitle=title('selection-title'),sources='Official county / Texas SOS in-person reports';
  const desc={title:'',nodes:[],scope,classification,source:sources+(mode==='place'?' · NCES 2025 / 2020 Census':mode==='demographic'?' · 2020 Census PL 94-171':mode==='primary'?' · 2026 primary ballots':''),note:'',key};
  if(key==='county-daily'){desc.title=`${CountyView.measure==='daily'?'Daily':'Cumulative'} turnout by county bucket`;desc.nodes=[$('county-daily-charts')];desc.legend=true;desc.note=title('county-bucket-coverage');desc.grid=true;}
  else if(key.startsWith('county-daily-')){const panel=document.querySelectorAll('.county-daily-panel')[Number(key.slice(13))];if(!panel)throw Error('Chart unavailable');desc.title=`${CountyView.measure==='daily'?'Daily':'Cumulative'} turnout · ${panel.querySelector('h3').textContent}`;desc.nodes=[panel.querySelector('svg')];desc.legend=true;desc.note=title('county-bucket-coverage');}
  else if(key==='county-summary'){desc.title='Cumulative turnout by county bucket';desc.nodes=[$('county-bucket-summary')];desc.summaryColumns=CountyView.view.buckets.length;desc.note=`${CountyView.view.coverage.cumulative_groups} counties · Same counties in both years`;desc.footer='2024 and 2026 through the same early-voting day.';}
  else if(key==='daily'){desc.title=`${Tracking.measure==='daily'?'Daily':'Cumulative'} turnout`;desc.nodes=[$('daily-charts')];desc.legend=true;desc.note=title('daily-coverage');desc.footer='Same reported geography in both years at each point; coverage can vary by day.';desc.grid=true;}
  else if(key.startsWith('daily-')){const index=Number(key.slice(6)),panel=document.querySelectorAll('.daily-panel')[index];if(!panel)throw Error('Chart unavailable');desc.title=`${Tracking.measure==='daily'?'Daily':'Cumulative'} turnout · ${panel.querySelector('h3').textContent}`;desc.nodes=[panel.querySelector('svg')];desc.legend=true;desc.note=title('daily-coverage');desc.footer='Same reported geography in both years at each point; coverage can vary by day.';}
  else if(key==='map'){desc.title=Atlas.county==='all'?'Texas · county overview':`${data.counties.find(c=>c.id===Atlas.county)?.name} County`;desc.scope='';desc.classification=$('map-layer').value==='turnout'?'Cumulative 2026 as % of 2024':mode==='partisan'?'2024 Harris share':classification;desc.nodes=[document.querySelector('.map-container'),$('map-legend')];desc.source='TLC 2026 primary precincts (November proxy) · '+($('map-layer').value==='turnout'?sources:mode==='place'?'NCES 2025 / 2020 Census':mode==='demographic'?'2020 Census':mode==='primary'?'County 2026 primary ballots':'2024 presidential votes');desc.footer=mode==='demographic'&&$('map-layer').value==='share'?'2020 Census resident composition; not voter demographics.':$('map-layer').value==='turnout'?'Comparison-group turnout; precincts in the same group share a value.':'Current map extent; selected comparison groups remain highlighted.';}
  else if(key==='regression'){desc.vector=true;desc.title=`Cumulative turnout vs. ${title('regression-title')}${mode!=='partisan'&&mode!=='place'?' · '+RegressionCohort.label(regressionWinner):''}`;desc.nodes=[$('regression-stats'),...(mode==='place'?[$('regression-legend')]:[]),$('regression-chart')];desc.footer='Unweighted OLS · All eligible observations remain in the fit; the selected scale may hide points.';if(bucket!==null)desc.note=`Highlight: ${bucketsFor(data.counties.find(c=>c.id===selected))?.[bucket]?.label||''}`;}
  else if(key==='profile'){desc.title=selectedTitle;desc.scope=title('selection-context');desc.nodes=[document.querySelector('.profile-grid')];desc.source='County / Texas SOS in-person reports · 2020 Census';desc.footer='Census figures describe residents; race and ethnicity categories can overlap.';desc.classification='Cumulative in-person turnout and resident composition';}
  else if(key==='demographics'){desc.title=`${selectedTitle} · Residents age 18+`;desc.scope=title('selection-context');desc.classification='2020 Census';desc.nodes=[$('demographic-profile')];desc.source='2020 Census PL 94-171 · TLC blocks assigned to 2026 precincts';desc.footer='Resident composition, not voter demographics. Categories overlap and are not additive.';}
  else if(key==='precinct-trend'){desc.title=`${selectedTitle} · ${document.querySelector('.trend-panel h3').textContent}`;desc.scope=title('selection-context');desc.nodes=[$('turnout-trend')];desc.legend=true;desc.classification='Cumulative in-person votes';desc.footer='Historical counts use the comparable geographic group where native precincts changed.';}
  else if(key==='matrix'){desc.title=title('bucket-title');desc.nodes=[$('matrix')];desc.footer=`2026 / 2024 cumulative in-person votes · Counties ${title('matrix-page')}${$('matrix-search').value?' · Filter: '+$('matrix-search').value:''} · † fewer than 3 groups or 100 baseline votes · — unavailable.`;}
  else if(key==='detail'||key==='bucket-bars'){desc.title=`${title('detail-name')} · Cumulative votes`;desc.nodes=[$('chart')];desc.scope=title('detail-totals');desc.footer='2024 and 2026 through the same early-voting day.';}
  else if(key==='precinct-table'){desc.title=title('detail-name')+' · Cumulative votes';desc.nodes=[document.querySelector('.group-scroll')];desc.scope=title('detail-totals');desc.table='precinct';desc.footer=`${$('search').value?`Filter: ${$('search').value} · `:''}Current page ${title('page')}; first 12 rows, in the current sort order.`;}
  else if(key==='county-table'){desc.title='Texas county turnout';desc.nodes=[document.querySelector('.county-scroll')];desc.scope=title('statewide-count');desc.table='county';desc.classification='Cumulative '+countyMethod.toLowerCase()+' votes';desc.footer=`${$('statewide-search').value?`Filter: ${$('statewide-search').value} · `:''}First 12 matching counties in the current sort order. County totals can differ from ordinary-precinct reports.`;}
  else if(key==='county-trend'||key==='counties'){desc.title=`${Tracking.stateCounty==='all'?'Texas':Tracking.state.counties.find(c=>c.id===Tracking.stateCounty)?.name} · ${Tracking.stateMeasure==='daily'?'Daily':'Cumulative'} turnout`;desc.nodes=[$('statewide-chart')];desc.scope='County totals';desc.classification=countyMethod+' votes';desc.legend=true;desc.note=title('statewide-note');desc.footer='Same reported geography in both years at each point; coverage can vary by day.';}
  else throw Error('Unknown visual');
  const isCounty=key.startsWith('county-')||key==='counties';
  const stale=isCounty?[]:comparisonIssues().filter(c=>!['map','profile','demographics','precinct-trend'].includes(key)||Atlas.county==='all'||c.county===Atlas.county);
  if(stale.length)desc.note=[desc.note,`Day ${day}: ${coverageSummary(stale)}; displayed pairs use the same geography`].filter(Boolean).join(' · ');
  if(key==='map'&&Atlas.county==='all'){desc.source='2020 Census county boundaries · '+sources+(mode==='place'?' · NCES 2025 / 2020 Census':'');desc.footer='County overview of matched precincts, not whole-county turnout. Gray: unavailable or unclassified.';}
  if(key==='regression'&&mode==='place'){desc.classification=regressionPlace==='all'?'All place types':placeLabels[+regressionPlace];desc.note=[desc.note,'Dots: place type'].filter(Boolean).join(' · ');}
  if(key==='regression'&&mode!=='partisan'&&mode!=='place')desc.note=[desc.note,'Dots: 2024 Harris blue / Trump red'].filter(Boolean).join(' · ');
  if(['county-table','county-trend','counties','precinct-trend'].includes(key))desc.source=sources;
  if(desc.classification&&desc.title.toLowerCase().includes(desc.classification.toLowerCase()))desc.classification='';
  desc.period=dates(comparisonPeriod());desc.day=day;desc.mode=mode;desc.through=data.through;desc.legendColor=mode==='demographic'?'#137b8a':'#334155';desc.cohortLabel=cohort==='unchanged'&&!['profile','demographics','precinct-trend','county-table','county-trend','counties'].includes(key)?'Unchanged precincts':'';
  if(isCounty){desc.period='Through '+[comparisonPeriod().through_2026,comparisonPeriod().through_2024].map(iso=>new Date(iso+'T12:00:00Z').toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'})).join(' / ');desc.mode=CountyView.mode;desc.scope='County totals · '+countyMethod;desc.classification=CountyView.label();desc.cohortLabel='';desc.legendColor=CountyView.mode==='demographic'?'#137b8a':'#334155';desc.source='Official Texas SOS / county '+countyMethod.toLowerCase()+' reports · 2024 presidential results'+(CountyView.mode==='place'?' · NCES 2025 / 2020 Census':CountyView.mode==='demographic'?' · 2020 Census':'');if(key.startsWith('county-daily'))desc.footer='Matched counties at each point; coverage can vary by day.';if(CountyView.bucket!==null)desc.note=[desc.note,`Selected bucket: ${CountyView.view?.buckets[CountyView.bucket]?.label}`].filter(Boolean).join(' · ');if(key==='county-trend'||key==='counties'){desc.classification=countyMethod+' votes';desc.source='Official Texas SOS / county '+countyMethod.toLowerCase()+' reports';}}
  if(key==='matrix'&&matrixLayout==='joint'){
   desc.mode=jointMetric().unit==='category'?'place':'demographic';desc.classification=jointMetric().label+(jointMetric().denominator==='vap'?' · age 18+':'');
   desc.source=sources+' · 2020 Census PL 94-171'+(jointMetric().unit==='category'?' · NCES 2025':'')+' · 2024 presidential results';
   desc.note=[desc.note,title('matrix-context')].filter(Boolean).join(' · ');
   desc.footer='2026 / 2024 cumulative in-person votes · † fewer than 3 groups or 100 baseline votes · — no baseline or unavailable.';
  }
  desc.static=key==='demographics'||key==='map'&&$('map-layer').value==='share';
  return desc;
 },
 cssValue(value){return value.replace(/url\(["']?[^)"']*#([^)"']+)["']?\)/g,'url(#$1)');},
 copyStyle(source,target,pseudo=null){const style=getComputedStyle(source,pseudo);for(const property of style)if(!property.startsWith('--'))target.style.setProperty(property,this.cssValue(style.getPropertyValue(property)));target.style.animation='none';target.style.transition='none';return style;},
 clone(source,vector=false){
  if(source.nodeType===Node.TEXT_NODE)return source.cloneNode();
  if(source.nodeType!==Node.ELEMENT_NODE)return null;
  // Regression SVGs already carry their chart styles as presentation attributes.
  // Preserve interactive highlights without copying every computed CSS property
  // onto thousands of circles in a static image.
  if(vector&&source.localName==='svg'){
   const clone=source.cloneNode(true);this.copyStyle(source,clone);clone.style.fontFamily='Arial,sans-serif';
   const originals=source.querySelectorAll('.regression-point,.state-dot'),copies=clone.querySelectorAll('.regression-point,.state-dot');
   originals.forEach((node,i)=>{if(node.matches(':hover,:focus,.linked-hover'))this.copyStyle(node,copies[i]);});
   return clone;
  }
  if(source.matches('.image-export,.panel-tools,.leaflet-control-zoom,.leaflet-tooltip,.timeline-hit,#map-loading,.tracking-readout,.regression-heading,.panel-heading,.search-row,.pagination,select,input,.download,#statewide-reset,.panel-toggle,.precinct-available'))return null;
  const clone=source.cloneNode(false),style=this.copyStyle(source,clone);
  // Internal SVG fragments must remain local to the exported document.
  for(const attribute of [...clone.attributes])if(attribute.value.includes('url('))clone.setAttribute(attribute.name,this.cssValue(attribute.value));
  const pseudo=which=>{if(source.namespaceURI!=='http://www.w3.org/1999/xhtml')return;const s=getComputedStyle(source,which);if(s.content==='none'||s.content==='normal')return;const node=document.createElement('span');this.copyStyle(source,node,which);node.textContent=s.content.replace(/^['"]|['"]$/g,'');node.style.content='normal';clone.append(node);};
  pseudo('::before');const children=this.rowLimit&&source.tagName==='TBODY'?[...source.children].slice(0,this.rowLimit):source.childNodes;for(const child of children){const copy=this.clone(child,vector);if(copy)clone.append(copy);}pseudo('::after');
  clone.style.fontFamily='Arial,sans-serif';clone.removeAttribute('tabindex');clone.removeAttribute('autofocus');
  if(style.position==='sticky'){clone.style.position='static';clone.style.top='auto';clone.style.left='auto';}
  return clone;
 },
 async capture(desc){
  await document.fonts.ready;
  if(desc.nodes.some(n=>!n||!n.getBoundingClientRect().width||!n.getBoundingClientRect().height))throw Error('Expand this panel before exporting');
  const wrapper=document.createElement('div');wrapper.setAttribute('xmlns','http://www.w3.org/1999/xhtml');wrapper.style.cssText='background:#fff;color:#1d2633;font:14px Arial,sans-serif;box-sizing:border-box;';
  const measure=document.createElement('div');measure.style.cssText='position:fixed;left:-20000px;top:0;pointer-events:none;visibility:hidden;';document.body.append(measure);
  let width=0,height=0;
  this.rowLimit=desc.table?12:0;
  try{
   for(const source of desc.nodes){
    const box=source.getBoundingClientRect(),clone=this.clone(source,desc.vector);if(!clone)continue;let w=box.width;
    if(source.id==='matrix'){w=Math.max(w,source.scrollWidth);clone.style.overflow='visible';clone.style.maxHeight='none';}
    if(desc.table){clone.style.maxHeight='none';clone.style.overflow='visible';clone.querySelectorAll('table,thead,tbody,tr').forEach(node=>{node.style.height='auto';node.style.minHeight='0';});}
    if(desc.grid){
     w=1320;clone.style.display='grid';clone.style.gridTemplateColumns='repeat(3,minmax(0,1fr))';clone.style.gridTemplateRows='none';clone.style.gridAutoRows='auto';clone.style.width=w+'px';
     clone.querySelectorAll('.daily-panel,.county-daily-panel').forEach((panel,index)=>{
      panel.style.padding='16px 12px 5px';panel.style.width='auto';panel.style.height='auto';panel.style.borderRight=(index+1)%3?'1px solid #e3e7ed':'0';panel.style.borderBottom=index<3?'1px solid #e3e7ed':'0';
      const heading=panel.querySelector('.daily-panel-heading');heading.style.width='auto';heading.style.height='auto';heading.querySelector('h3').style.cssText+='width:auto;height:auto;white-space:nowrap;';
      const ratio=heading.querySelector('b');if(ratio)ratio.style.marginLeft='auto';
      panel.querySelectorAll('svg').forEach(svg=>{svg.style.width='100%';svg.style.height='auto';});
     });
    }
    if(desc.key==='county-summary'){
     w=1320;clone.style.display='grid';clone.style.gridTemplateColumns='repeat(3,minmax(0,1fr))';clone.style.gridTemplateRows='none';
     const originalBars=source.querySelectorAll('.bucket-bar-old,.bucket-bar-new');clone.querySelectorAll('.bucket-bar-old,.bucket-bar-new').forEach((bar,i)=>{bar.style.width=originalBars[i].style.width;bar.style.height='8px';});
     clone.querySelectorAll('.county-summary-bucket').forEach((node,index)=>{
      node.style.height='auto';node.style.width='auto';node.style.padding='24px';node.querySelectorAll('.bucket-summary-heading,.bucket-summary-heading>span,.bucket-summary-heading>b,.bucket-summary-votes,.bucket-summary-votes>span,.bucket-summary-votes strong,.bucket-county-count').forEach(n=>{n.style.width='auto';n.style.height='auto';});node.style.borderBottom=index<3?'1px solid #e3e7ed':'0';node.style.borderRight=(index+1)%3?'1px solid #e3e7ed':'0';
      node.querySelectorAll('.bucket-summary-heading,.bucket-summary-heading>span').forEach(n=>{n.style.fontSize='20px';n.style.width='auto';});node.querySelector('.bucket-summary-heading').style.marginBottom='20px';node.querySelector('.bucket-summary-heading>b').style.fontSize='25px';
      const votes=node.querySelector('.bucket-summary-votes');votes.style.width='auto';votes.style.flexDirection='column';votes.style.marginTop='20px';votes.style.gap='9px';votes.querySelectorAll('span').forEach(n=>{n.style.fontSize='16px';n.style.width='auto';});votes.querySelectorAll('strong').forEach(n=>{n.style.fontSize='19px';});node.querySelector('.bucket-county-count').style.cssText+='font-size:15px;margin-top:16px;';
     });
    }
    if(desc.key==='profile'){clone.querySelectorAll('.census-profile,#demographic-profile').forEach(node=>{node.style.height='auto';});clone.querySelector('#demographic-profile').style.display='flow-root';}
    if(source.id==='map-legend')clone.querySelectorAll('span').forEach(node=>{node.style.width='auto';node.style.whiteSpace='nowrap';});
    clone.style.width=w+'px';clone.style.minWidth='0';clone.style.margin='0';clone.style.maxWidth='none';clone.style.flexShrink='0';
    if(desc.table||desc.grid||desc.key==='profile'||desc.key==='county-summary'||source.id==='demographic-profile'||source.id==='chart'||source.id==='map-legend'){
     clone.style.height='auto';if(getComputedStyle(source).display==='block')clone.style.display='flow-root';
    }else clone.style.height=box.height+'px';
    measure.style.width=w+'px';measure.append(clone);
    const h=Math.ceil(Math.max(clone.getBoundingClientRect().height,source.classList.contains('map-container')?0:clone.scrollHeight));
    clone.style.height=h+'px';wrapper.append(clone);width=Math.max(width,w);height+=h;
   }
  }finally{this.rowLimit=0;measure.remove();}
  wrapper.style.width=width+'px';wrapper.style.height=height+'px';wrapper.style.overflow='hidden';
  const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><foreignObject width="100%" height="100%">${new XMLSerializer().serializeToString(wrapper)}</foreignObject></svg>`;
  const img=new Image();img.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg);await img.decode();return {img,width,height};
 },
 // Wrap all metadata, including a long URL or county name, without clipping.
 wrapText(ctx,text,maxWidth){
  const lines=[];
  for(const paragraph of String(text||'').split('\n')){
   let current='';
   for(const word of paragraph.split(/\s+/).filter(Boolean)){
    if(current&&ctx.measureText(current+' '+word).width>maxWidth){lines.push(current);current='';}
    let part='';
    for(const character of word){if(part&&ctx.measureText(part+character).width>maxWidth){if(current){lines.push(current);current='';}lines.push(part);part='';}part+=character;}
    current+=(current?' ':'')+part;
   }
   if(current)lines.push(current);
  }
  return lines;
 },
 shareText(desc){
  const context=[desc.scope,desc.classification,desc.cohortLabel,desc.static||desc.day==null?'':`Day ${desc.day}`,desc.static?'':desc.period].filter(Boolean).join(' · ');
  const detail=[desc.title,context,desc.footer,desc.note,desc.source].filter(Boolean).join('. ');
  const links=`${this.social.dashboard}\n${this.social.x} · ${this.social.linkedinUrl}`;
  const period=[desc.static||desc.day==null?'':`Day ${desc.day}`,desc.static?'':desc.period].filter(Boolean).join(' · ');
  // A concise caption works for standard X posts as well as LinkedIn. Full
  // coverage/method notes remain in the graphic and separate image description.
  const candidates=[
   [desc.title,context,links].filter(Boolean).join('\n\n'),
   [desc.title,period,links].filter(Boolean).join('\n\n'),
   [`Early vote analysis${desc.static||desc.day==null?'':` · Day ${desc.day}`}`,'Comparison dates, scope and coverage are shown in the graphic.',links].join('\n\n')
  ];
  const caption=candidates.find(value=>Array.from(value).length<=280);
  const alt=detail.length<=1000?detail:detail.slice(0,996)+'…';
  return {caption,alt,title:desc.title,context};
 },
 offerShare(desc){
  this.lastShare=this.shareText(desc);this.status('PNG downloaded');clearTimeout(this.statusTimer);
  const node=$('image-status'),actions=document.createElement('div');actions.className='image-share-actions';
  for(const [field,label]of [['caption','Copy caption'],['alt','Copy ALT text']]){
   const button=document.createElement('button');button.type='button';button.id='copy-image-'+field;button.textContent=label;
   const frozen=this.lastShare[field];button.addEventListener('click',async()=>{
    try{await navigator.clipboard.writeText(frozen);button.textContent='Copied';setTimeout(()=>button.textContent=label,1800);}
    catch(_){let area=node.querySelector('textarea');if(!area){area=document.createElement('textarea');area.readOnly=true;node.append(area);}area.setAttribute('aria-label',label.replace('Copy ','')+' — select and copy');area.value=frozen;area.focus();area.select();}
   });actions.append(button);
  }
  const close=document.createElement('button');close.type='button';close.textContent='Close';close.setAttribute('aria-label','Dismiss image sharing options');close.addEventListener('click',()=>node.replaceChildren());actions.append(close);node.append(actions);
 },
 async compose(capture,desc){
  await document.fonts.ready;
  if(!(capture.width>0&&capture.height>0))throw Error('The visual has no drawable area');
  const canvas=document.createElement('canvas');canvas.width=1600;
  const ctx=canvas.getContext('2d'),style=getComputedStyle(document.body),token=(name,fallback)=>style.getPropertyValue(name).trim()||fallback;
  const paper=token('--brand-paper','#dbeaf2'),ink=token('--ink','#211b1b'),muted=token('--muted','#586772'),brand=token('--brand-accent','#743b42'),rule=token('--rule','#9db4c1');
  // Fit the frame to the complete capture, rather than fitting a narrow chart
  // into an oversized landscape surface. Text is measured before canvas sizing,
  // which resets the context. Both organic platforms accept these aspect ratios.
  ctx.font='bold 40px Arial,sans-serif';const titles=this.wrapText(ctx,desc.title,1504);
  ctx.font='22px Arial,sans-serif';
  const context=[desc.scope,desc.classification,desc.cohortLabel,desc.static||desc.day==null?'':`Day ${desc.day}`].filter(Boolean).join(' · ');
  const contexts=this.wrapText(ctx,context,1504),periods=!desc.static&&desc.period?this.wrapText(ctx,desc.period,1504):[];
  ctx.font='19px Arial,sans-serif';const notes=this.wrapText(ctx,[desc.note,desc.footer].filter(Boolean).join(' · '),1504);
  ctx.font='18px Arial,sans-serif';const sources=this.wrapText(ctx,'Source: '+desc.source,1504);
  const plotTop=128+titles.length*47+(contexts.length+periods.length)*28+(desc.legend?29:0)+7;
  const belowPlot=20+notes.length*24+13+sources.length*23+17+86;
  const naturalHeight=plotTop+24+capture.height*1472/capture.width+belowPlot;
  canvas.height=Math.max(800,Math.min(2000,Math.ceil(naturalHeight)));
  ctx.fillStyle=paper;ctx.fillRect(0,0,1600,canvas.height);ctx.fillStyle=brand;ctx.fillRect(0,0,1600,76);
  let authorX=48;const portrait=$('brand-portrait');
  if(portrait){try{await portrait.decode();ctx.drawImage(portrait,48,14,48,48);authorX=112;}catch(_){/* Plain-text identity remains complete if the portrait fails. */}}
  ctx.fillStyle='#fff';ctx.font='bold 27px Arial,sans-serif';ctx.fillText(this.social.name,authorX,49);
  ctx.font='22px Arial,sans-serif';const masthead='EARLY VOTE · 2026';ctx.fillText(masthead,1552-ctx.measureText(masthead).width,48);
  ctx.fillStyle=ink;ctx.font='bold 40px Arial,sans-serif';let top=128;
  for(const line of titles){ctx.fillText(line,48,top);top+=47;}
  ctx.fillStyle=muted;ctx.font='22px Arial,sans-serif';
  for(const line of contexts){ctx.fillText(line,48,top-9);top+=28;}
  for(const line of periods){ctx.fillText(line,48,top-9);top+=28;}
  if(desc.legend){const y=top-5;for(const [i,year,color]of [[0,2024,'#8d9aab'],[1,2026,desc.legendColor||ink]]){const x=48+i*145;ctx.strokeStyle=color;ctx.lineWidth=3;ctx.setLineDash(i?[]:[7,5]);ctx.beginPath();ctx.moveTo(x,y-6);ctx.lineTo(x+30,y-6);ctx.stroke();ctx.setLineDash([]);ctx.fillText(String(year),x+40,y);}top+=29;}
  top+=7;
  const footerTop=canvas.height-86,sourceTop=footerTop-17-sources.length*23,noteTop=sourceTop-13-notes.length*24,plotBottom=noteTop-20,available=plotBottom-top;
  if(available<170)throw Error('This visual has too much context for a share image. Export a focused panel.');
  ctx.fillStyle='#fff';ctx.fillRect(48,top,1504,available);ctx.strokeStyle=rule;ctx.lineWidth=1;ctx.strokeRect(48.5,top+.5,1503,available-1);
  const scale=Math.min(1472/capture.width,(available-24)/capture.height),w=capture.width*scale,h=capture.height*scale;
  ctx.drawImage(capture.img,48+(1504-w)/2,top+(available-h)/2,w,h);
  ctx.fillStyle=muted;ctx.font='19px Arial,sans-serif';notes.forEach((line,i)=>ctx.fillText(line,48,noteTop+19+i*24));
  ctx.font='18px Arial,sans-serif';sources.forEach((line,i)=>ctx.fillText(line,48,sourceTop+18+i*23));
  ctx.fillStyle=brand;ctx.fillRect(0,footerTop,1600,86);ctx.fillStyle='#fff';ctx.font='bold 29px Arial,sans-serif';ctx.fillText('X '+this.social.x,48,canvas.height-34);
  ctx.font='26px Arial,sans-serif';const linkedin=this.social.linkedin;ctx.fillText(linkedin,1552-ctx.measureText(linkedin).width,canvas.height-34);
  this.lastLayout={canvas:{width:canvas.width,height:canvas.height},plot:{x:48,y:top,width:1504,height:available},capture:{x:48+(1504-w)/2,y:top+(available-h)/2,width:w,height:h},noteTop,sourceTop,footerTop};
  return canvas;
 },
 async png(canvas){
  const blob=await new Promise((resolve,reject)=>canvas.toBlob(value=>value?resolve(value):reject(Error('PNG encoding failed')),'image/png'));
  if(blob.size>5000000)throw Error('PNG exceeds the 5 MB sharing limit. Export a focused panel.');return blob;
 },
 async download(key,button){
  if(this.busy)return;this.busy=true;button.disabled=true;this.status('Preparing PNG…');
  try{
   if(!data)throw Error('Wait for the dashboard to load');
   await document.fonts.ready;Motion.finish();const desc=this.descriptor(key),capture=await this.capture(desc),canvas=await this.compose(capture,desc),blob=await this.png(canvas);
   const url=URL.createObjectURL(blob),link=document.createElement('a'),slug=desc.title.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');link.href=url;link.download=`texas-${desc.key}-${slug}-${desc.mode}-day-${desc.day}-${desc.through}.png`;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);this.offerShare(desc);
  }catch(error){this.status(`Image export failed: ${error.message}`,true);}
  finally{this.busy=false;this.sync();}
 }
};
Visuals.init();
