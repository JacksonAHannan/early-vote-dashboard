'use strict';
// Panel state and client-side share cards. No source requests or external assets.
const Visuals=window.Visuals={
 storageKey:'texas-turnout:collapsed:v1',collapsed:new Set(),busy:false,queued:false,
 panels:[
  ['county-daily-section','.section-heading','County bucket timelines','county-daily'],
  ['county-summary-section','.section-heading','County bucket comparison','county-summary'],
  ['daily-section','.section-heading','Daily turnout','daily'],
  ['map-panel','.panel-heading','Precinct map','map'],
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
   const all=event.target.closest('[data-panels]');if(all){if(all.dataset.panels==='collapse'&&Atlas.map&&!this.collapsed.has('map-panel'))this.mapView={center:Atlas.map.getCenter(),zoom:Atlas.map.getZoom()};for(const [id]of this.panels)if($(id).getBoundingClientRect().width)all.dataset.panels==='collapse'?this.collapsed.add(id):this.collapsed.delete(id);this.save();for(const [id]of this.panels)this.applyPanel(id);this.reflow();return;}
   const image=event.target.closest('[data-image]');if(image)this.download(image.dataset.image,image);
  });
  new MutationObserver(()=>{if(!this.queued){this.queued=true;queueMicrotask(()=>{this.queued=false;this.sync();});}}).observe(document.querySelector('main'),{childList:true,subtree:true});
  this.sync();
 },
 imageButton(key,label){const b=document.createElement('button');b.type='button';b.className='image-export';b.dataset.image=key;b.textContent='PNG ↓';b.title=label;b.setAttribute('aria-label',label);return b;},
 save(){try{localStorage.setItem(this.storageKey,JSON.stringify([...this.collapsed]));}catch(_){}},
 applyPanel(id){const root=$(id),closed=this.collapsed.has(id),label=this.panels.find(p=>p[0]===id)[2],button=root.querySelector('[data-panel]');root.classList.toggle('is-collapsed',closed);$(id+'-body').hidden=closed;button.setAttribute('aria-expanded',String(!closed));button.setAttribute('aria-label',`${closed?'Expand':'Collapse'} ${label.toLowerCase()}`);button.title=button.getAttribute('aria-label');},
 toggle(id){if(!this.collapsed.has('map-panel')&&Atlas.map)this.mapView={center:Atlas.map.getCenter(),zoom:Atlas.map.getZoom()};this.collapsed.has(id)?this.collapsed.delete(id):this.collapsed.add(id);this.save();this.applyPanel(id);this.reflow();},
 reflow(){requestAnimationFrame(()=>{window.dispatchEvent(new Event('resize'));requestAnimationFrame(()=>{if(Atlas.map&&!this.collapsed.has('map-panel')){Atlas.map.invalidateSize({pan:false});if(this.mapView){Atlas.map.setView(this.mapView.center,this.mapView.zoom,{animate:false});this.mapView=null;}}});});},
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
 classification(){return mode==='partisan'?'2024 presidential margin':metric()?.label+(metric()?.denominator==='vap'?' · age 18+':'');},
 ready(key){
  if(!data)return false;
  if(key.startsWith('county-')||key==='counties')return CountyView.ready()&&(!['county-table','county-trend','counties'].includes(key)||Tracking.stateReady());
  if(key==='daily'||key.startsWith('daily-'))return Boolean(Tracking.view&&Tracking.key===`${data.generated_at}|${county}|${cohort}|${mode}|${activeMetricId()}`);
  if(key==='map')return Boolean(Atlas.layer&&$('map-loading').hidden);
  if(['profile','demographics','precinct-trend'].includes(key))return $('selection-panel').dataset.county===Atlas.county;
  return mode==='partisan'||demoReady();
 },
 descriptor(key){
  if(!this.ready(key))throw Error('Wait for the selected comparison to finish loading.');
  const title=id=>$(id)?.textContent||'',countyMethod=({total:'Mail + in person',in_person:'In person',mail:'Mail'})[window.CountyView?.votingMethod||'total'],scope=this.scope(),classification=this.classification(),selectedTitle=title('selection-title'),sources='Official county / Texas SOS in-person reports';
  const desc={title:'',nodes:[],scope,classification,source:sources+(mode==='demographic'?' · 2020 Census PL 94-171':mode==='primary'?' · 2026 primary ballots':''),note:'',key};
  if(key==='county-daily'){desc.title=`${CountyView.measure==='daily'?'Daily':'Cumulative'} turnout by county bucket`;desc.nodes=[$('county-daily-charts')];desc.legend=true;desc.note=title('county-bucket-coverage');desc.grid=true;}
  else if(key.startsWith('county-daily-')){const panel=document.querySelectorAll('.county-daily-panel')[Number(key.slice(13))];if(!panel)throw Error('Chart unavailable');desc.title=`${CountyView.measure==='daily'?'Daily':'Cumulative'} turnout · ${panel.querySelector('h3').textContent}`;desc.nodes=[panel.querySelector('svg')];desc.legend=true;desc.note=title('county-bucket-coverage');}
  else if(key==='county-summary'){desc.title='Cumulative turnout by county bucket';desc.nodes=[$('county-bucket-summary')];desc.summaryColumns=CountyView.view.buckets.length;desc.note=`${CountyView.view.coverage.cumulative_groups} counties · Same counties in both years`;desc.footer='2024 and 2026 through the same early-voting day.';}
  else if(key==='daily'){desc.title=`${Tracking.measure==='daily'?'Daily':'Cumulative'} turnout`;desc.nodes=[$('daily-charts')];desc.legend=true;desc.note=title('daily-coverage');desc.footer='Same reported geography in both years at each point; coverage can vary by day.';desc.grid=true;}
  else if(key.startsWith('daily-')){const index=Number(key.slice(6)),panel=document.querySelectorAll('.daily-panel')[index];if(!panel)throw Error('Chart unavailable');desc.title=`${Tracking.measure==='daily'?'Daily':'Cumulative'} turnout · ${panel.querySelector('h3').textContent}`;desc.nodes=[panel.querySelector('svg')];desc.legend=true;desc.note=title('daily-coverage');desc.footer='Same reported geography in both years at each point; coverage can vary by day.';}
  else if(key==='map'){desc.title=`${data.counties.find(c=>c.id===Atlas.county)?.name} County`;desc.scope='';desc.classification=$('map-layer').value==='turnout'?'2026 / 2024 in-person votes':mode==='partisan'?'2024 Harris share':classification;desc.nodes=[document.querySelector('.map-container'),$('map-legend')];desc.source='TLC 2026 primary precincts (November proxy) · '+($('map-layer').value==='turnout'?sources:mode==='demographic'?'2020 Census':mode==='primary'?'County 2026 primary ballots':'2024 presidential votes');desc.footer=mode==='demographic'&&$('map-layer').value==='share'?'2020 Census resident composition; not voter demographics.':$('map-layer').value==='turnout'?'Comparison-group turnout; precincts in the same group share a value.':'Current map extent; selected comparison groups remain highlighted.';}
  else if(key==='regression'){desc.vector=true;desc.title=`Turnout vs. ${title('regression-title')}${mode!=='partisan'?' · '+RegressionCohort.label(regressionWinner):''}`;desc.nodes=[$('regression-stats'),$('regression-chart')];desc.footer='Unweighted OLS · All eligible observations remain in the fit; the selected scale may hide points.';if(bucket!==null)desc.note=`Highlight: ${bucketsFor(data.counties.find(c=>c.id===selected))?.[bucket]?.label||''}`;}
  else if(key==='profile'){desc.title=selectedTitle;desc.scope=title('selection-context');desc.nodes=[document.querySelector('.profile-grid')];desc.source='County / Texas SOS in-person reports · 2020 Census';desc.footer='Census figures describe residents; race and ethnicity categories can overlap.';desc.classification='Precinct profile';}
  else if(key==='demographics'){desc.title=`${selectedTitle} · Residents age 18+`;desc.scope=title('selection-context');desc.classification='2020 Census';desc.nodes=[$('demographic-profile')];desc.source='2020 Census PL 94-171 · TLC blocks assigned to 2026 precincts';desc.footer='Resident composition, not voter demographics. Categories overlap and are not additive.';}
  else if(key==='precinct-trend'){desc.title=`${selectedTitle} · ${document.querySelector('.trend-panel h3').textContent}`;desc.scope=title('selection-context');desc.nodes=[$('turnout-trend')];desc.legend=true;desc.classification='In-person votes';desc.footer='Historical counts use the comparable geographic group where native precincts changed.';}
  else if(key==='matrix'){desc.title=title('bucket-title');desc.nodes=[$('matrix')];desc.footer=`2026 / 2024 cumulative in-person votes · Counties ${title('matrix-page')}${$('matrix-search').value?' · Filter: '+$('matrix-search').value:''} · † fewer than 3 groups or 100 baseline votes · — unavailable.`;}
  else if(key==='detail'||key==='bucket-bars'){desc.title=`${title('detail-name')} · Cumulative votes`;desc.nodes=[$('chart')];desc.scope=title('detail-totals');desc.footer='2024 and 2026 through the same early-voting day.';}
  else if(key==='precinct-table'){desc.title=title('detail-name');desc.nodes=[document.querySelector('.group-scroll')];desc.scope=title('detail-totals');desc.table='precinct';desc.footer=`${$('search').value?`Filter: ${$('search').value} · `:''}Current page ${title('page')}; first 12 rows, in the current sort order.`;}
  else if(key==='county-table'){desc.title='Texas county turnout';desc.nodes=[document.querySelector('.county-scroll')];desc.scope=title('statewide-count');desc.table='county';desc.classification='Cumulative '+countyMethod.toLowerCase()+' votes';desc.footer=`${$('statewide-search').value?`Filter: ${$('statewide-search').value} · `:''}First 12 matching counties in the current sort order. County totals can differ from ordinary-precinct reports.`;}
  else if(key==='county-trend'||key==='counties'){desc.title=`${Tracking.stateCounty==='all'?'Texas':Tracking.state.counties.find(c=>c.id===Tracking.stateCounty)?.name} · ${Tracking.stateMeasure==='daily'?'Daily':'Cumulative'} turnout`;desc.nodes=[$('statewide-chart')];desc.scope='County totals';desc.classification=countyMethod+' votes';desc.legend=true;desc.note=title('statewide-note');desc.footer='Same reported geography in both years at each point; coverage can vary by day.';}
  else throw Error('Unknown visual');
  const isCounty=key.startsWith('county-')||key==='counties';
  const stale=data.counties.filter(c=>c.status!=='current'&&!isCounty&&(key==='county-table'||key==='county-trend'||key==='counties'?false:key==='map'||key==='profile'||key==='demographics'||key==='precinct-trend'?c.id===Atlas.county:county==='all'||c.id===county));
  if(stale.length)desc.note=[desc.note,`Partial or delayed reports: ${stale.length===1?stale[0].name:stale.length+' counties'}`].filter(Boolean).join(' · ');
  if(key==='regression'&&mode!=='partisan')desc.note=[desc.note,'Dots: 2024 Harris blue / Trump red'].filter(Boolean).join(' · ');
  if(['county-table','county-trend','counties','precinct-trend'].includes(key))desc.source=sources;
  if(desc.classification&&desc.title.toLowerCase().includes(desc.classification.toLowerCase()))desc.classification='';
  const p=data.counties.map(period).find(Boolean);desc.period=p?dates(p):data.through;desc.day=day;desc.mode=mode;desc.through=data.through;desc.legendColor=mode==='demographic'?'#137b8a':'#334155';desc.cohortLabel=cohort==='unchanged'&&!['profile','demographics','precinct-trend','county-table','county-trend','counties'].includes(key)?'Unchanged precincts':'';
  if(isCounty){desc.mode=CountyView.mode;desc.scope='County totals · '+countyMethod;desc.classification=CountyView.label();desc.cohortLabel='';desc.legendColor=CountyView.mode==='demographic'?'#137b8a':'#334155';desc.source='Official Texas SOS / county '+countyMethod.toLowerCase()+' reports · 2024 presidential results'+(CountyView.mode==='demographic'?' · 2020 Census':'');if(key.startsWith('county-daily'))desc.footer='Matched counties at each point; coverage can vary by day.';if(CountyView.bucket!==null)desc.note=[desc.note,`Selected bucket: ${CountyView.view?.buckets[CountyView.bucket]?.label}`].filter(Boolean).join(' · ');if(key==='county-trend'||key==='counties'){desc.classification=countyMethod+' votes';desc.source='Official Texas SOS / county '+countyMethod.toLowerCase()+' reports';}}
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
 wrapText(ctx,text,maxWidth){const lines=[];let current='';for(const word of text.split(/\s+/)){if(current&&ctx.measureText(current+' '+word).width>maxWidth){lines.push(current);current=word;}else current+=(current?' ':'')+word;}if(current)lines.push(current);return lines;},
 async download(key,button){
  if(this.busy)return;this.busy=true;button.disabled=true;this.status('Preparing PNG…');
  try{
   if(!data)throw Error('Wait for the dashboard to load');
   await document.fonts.ready;const desc=this.descriptor(key),capture=await this.capture(desc),canvas=document.createElement('canvas');canvas.width=1600;canvas.height=1000;
   const ctx=canvas.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,1600,1000);ctx.fillStyle='#66758a';ctx.font='22px Arial,sans-serif';ctx.fillText('Texas early vote',48,43);
   ctx.font='bold 36px Arial,sans-serif';ctx.fillStyle='#1d2633';const titles=this.wrapText(ctx,desc.title,1504);titles.forEach((line,i)=>ctx.fillText(line,48,98+i*43));
   let top=98+(titles.length-1)*43;ctx.fillStyle='#66758a';ctx.font='21px Arial,sans-serif';const context=[desc.scope,desc.classification,desc.cohortLabel,desc.static?'':`Day ${desc.day}`].filter(Boolean).join(' · ');for(const line of this.wrapText(ctx,context,1504)){top+=29;ctx.fillText(line,48,top);}
   if(!desc.static){top+=30;ctx.fillText(desc.period,48,top);}
   if(desc.legend){const y=top+28;for(const [i,year,color]of [[0,2024,'#8d9aab'],[1,2026,desc.legendColor]]){const x=48+i*120;ctx.strokeStyle=color;ctx.lineWidth=3;ctx.setLineDash(i?[]:[7,5]);ctx.beginPath();ctx.moveTo(x,y-6);ctx.lineTo(x+30,y-6);ctx.stroke();ctx.setLineDash([]);ctx.fillText(String(year),x+40,y);}top+=35;}
   top+=20;ctx.strokeStyle='#e3e7ed';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(48,top);ctx.lineTo(1552,top);ctx.stroke();top+=18;
   ctx.font='19px Arial,sans-serif';const notes=this.wrapText(ctx,[desc.note,desc.footer].filter(Boolean).join(' · '),1504),bottom=934-notes.length*24,available=Math.max(220,bottom-top-20),scale=Math.min(1504/capture.width,available/capture.height),w=capture.width*scale,h=capture.height*scale;
   ctx.drawImage(capture.img,48+(1504-w)/2,top+(available-h)/2,w,h);
   ctx.fillStyle='#66758a';notes.forEach((line,i)=>ctx.fillText(line,48,bottom+24+i*24));ctx.fillStyle='#7b8796';ctx.font='18px Arial,sans-serif';ctx.fillText(desc.source,48,978);
   const blob=await new Promise((resolve,reject)=>canvas.toBlob(value=>value?resolve(value):reject(Error('PNG encoding failed')),'image/png'));
   const url=URL.createObjectURL(blob),link=document.createElement('a'),slug=desc.title.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');link.href=url;link.download=`texas-${desc.key}-${slug}-${desc.mode}-day-${desc.day}-${desc.through}.png`;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);this.status('PNG downloaded');
  }catch(error){this.status(`Image export failed: ${error.message}`,true);}
  finally{this.busy=false;this.sync();}
 }
};
Visuals.init();
