#!/usr/bin/env python3
"""Native polygon hover facts, matched-group qualification and real interaction.

TURNOUT_TEST_URL=http://127.0.0.1:8743 uv run --with playwright python dashboard/tests/precinct_hover.py
TURNOUT_JOINT_STATIC=1 uses the shared Pages artifact reader.
"""
import json,math,os,traceback
from datetime import date,timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from joint_matrix import api
ROOT=Path(__file__).resolve().parents[2]
BASE=os.environ.get('TURNOUT_TEST_URL','http://127.0.0.1:8743').rstrip('/')+'/'
TAG=os.environ.get('TURNOUT_TEST_TAG','local')
OUT=ROOT/'analysis/precinct-hover'/TAG;OUT.mkdir(parents=True,exist_ok=True)
REPORT={'url':BASE,'checks':[],'javascript_errors':[]}
def native_count(county,day,precinct):
 end=(date(2026,10,18)+timedelta(days=day)).isoformat()
 cumulative=[s for s in county['sources'] if s.get('cumulative') and s['date']==end]
 if cumulative:return cumulative[0]['counts'].get(precinct,0)
 daily=[s for s in county['sources'] if not s.get('cumulative') and '2026-10-19'<=s['date']<=end]
 return sum(s['counts'].get(precinct,0) for s in daily) if len(daily)==day else None
def run():
 snapshot=api('/api/data');census=api('/api/demographics');references={r['id']:r for r in api('/api/reference')}
 day=min(3,snapshot['days']);target=None
 for c in snapshot['counties']:
  for p in c['periods']:
   if p['day']!=day:continue
   for index,g in enumerate(p['groups']):
    if not g.get('available',True) or len(g['new'])<2 or g['bucket'] is None or not g['votes_2024']:continue
    precinct=next((pid for pid in g['new'] if native_count(c,day,pid) is not None and native_count(c,day,pid)!=g['votes_2026'] and census['counties'].get(c['id'],{}).get('precincts',{}).get(pid,{}).get('counts',{}).get('vap',0)>0),None)
    if precinct:target={'county':c,'day':day,'group':g,'index':index,'precinct':precinct};break
   if target:break
  if target:break
 assert target,'real multi-precinct fixture'
 c=target['county'];pid=target['precinct'];g=target['group'];counts=census['counties'][c['id']]['precincts'][pid]['counts']
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
  page=browser.new_page(viewport={'width':1512,'height':1050},has_touch=True,reduced_motion='reduce')
  page.on('pageerror',lambda e:REPORT['javascript_errors'].append(str(e)))
  try:
   page.goto(BASE,wait_until='networkidle',timeout=120000);page.wait_for_function('data&&Atlas.layer',timeout=120000)
   page.locator('#precincts-tab').click();page.locator('#precinct-explore-tab').click()
   page.get_by_role('button',name=f'Day {day}',exact=True).click();page.locator('#map-county').select_option(c['id'])
   page.wait_for_function('(c)=>Atlas.layer?.getLayers()[0]?.feature.properties.county===c&&document.getElementById("map-loading").hidden',arg=c['id'],timeout=120000)
   page.locator('#county-map').scroll_into_view_if_needed()
   def enter():page.evaluate('(pid)=>{const l=Atlas.layers.get(pid);l.fire("mouseover",{originalEvent:{clientX:innerWidth-20,clientY:innerHeight-20}});}',pid)
   enter();card=page.locator('#precinct-tooltip');expect(card).to_be_visible();expect(card).to_have_attribute('data-precinct',pid)
   expect(card.locator('.hover-heading strong')).to_have_text('Precinct '+pid)
   expect(card.locator('.hover-heading span')).to_have_text(c['name']+' County')
   expect(card.locator('.hover-turnout strong').nth(0)).to_have_text(f'{native_count(c,day,pid):,}')
   expect(card.locator('.hover-turnout span').nth(1)).to_have_text('Group cumulative vs. 2024')
   expect(card.locator('.hover-turnout strong').nth(1)).to_have_text(f"{g['votes_2026']/g['votes_2024']*100:.1f}%")
   expect(card.locator('.hover-comparison b')).to_have_text(f"{g['votes_2026']:,} / {g['votes_2024']:,}")
   expect(card.locator('.hover-geography')).to_contain_text(f"{len(g['new'])} current / {len(g['old'])} historical")
   expect(card.locator('.hover-census').nth(0)).to_contain_text(f"{counts['population']:,}")
   expect(card.locator('.hover-census-heading b')).to_have_text(f"{counts['vap']:,}")
   for label,key in [('Total non-white','non_white_vap'),('Hispanic','hispanic_vap'),('White non-Hispanic','white_nh_vap'),('Black','black_vap'),('Asian','asian_vap')]:
    row=card.locator('.hover-census > div').filter(has=page.get_by_text(label,exact=True))
    expect(row.locator('dd')).to_have_text(f"{counts[key]/counts['vap']*100:.1f}%")
   old=[references[c['id']]['presidential'].get(old) for old in g['old']]
   if all(old):
    h=sum(r['harris'] for r in old);t=sum(r['trump'] for r in old)
    expect(card.locator('.hover-party b')).to_have_text(f'Harris {h/(h+t)*100:.1f}% · Trump {t/(h+t)*100:.1f}%')
   assert page.locator(f'.regression-point[data-id="{c["id"]}:{target["index"]}"].linked-hover').count()==1
   REPORT['native_fixture']={'county':c['id'],'precinct':pid,'native_votes':native_count(c,day,pid),'group_votes_2026':g['votes_2026'],'group_votes_2024':g['votes_2024']}
   REPORT['checks'].append('Real split-group polygon shows its own native votes/Census, distinct labeled group comparison, complete presidential shares and linked regression highlight')
   # Pure hover must not alter the selected comparison or map camera.
   before=page.evaluate('({active:Atlas.active,native:Atlas.native,zoom:Atlas.map.getZoom(),center:Atlas.map.getCenter()})')
   enter();assert page.evaluate('({active:Atlas.active,native:Atlas.native,zoom:Atlas.map.getZoom(),center:Atlas.map.getCenter()})')==before
   for width,height in [(1512,1050),(768,500),(390,844)]:
    page.set_viewport_size({'width':width,'height':height});page.locator('#county-map').scroll_into_view_if_needed();page.mouse.move(0,0);page.wait_for_timeout(200)
    for x,y in [(1,1),(width-1,1),(1,height-1),(width-1,height-1)]:
     page.evaluate('(p)=>Atlas.layers.get(p.pid).fire("mouseover",{originalEvent:{clientX:p.x,clientY:p.y}})',{'pid':pid,'x':x,'y':y})
     expect(card).to_be_visible();box=card.bounding_box();assert box['x']>=9 and box['y']>=9 and box['x']+box['width']<=width-9 and box['y']+box['height']<=height-9,(width,height,box)
    page.screenshot(path=str(OUT/f'hover-{width}.png'))
   page.set_viewport_size({'width':1512,'height':1050});page.locator('#county-map').scroll_into_view_if_needed()
   enter();page.evaluate('(pid)=>Atlas.layers.get(pid).fire("mouseout")',pid);expect(card).to_be_hidden()
   after=page.evaluate('({active:Atlas.active,native:Atlas.native})');assert after=={'active':before['active'],'native':before['native']}
   REPORT['checks'].append('Hover does not select/zoom; card remains inside all viewport corners on desktop, short tablet and mobile; mouseout dismisses')
   # Keyboard uses one map entry and moves between individual polygons.
   path=page.locator(f'#county-map path[data-precinct="{pid}"]');path.focus();expect(card).to_be_visible()
   expect(page.locator('#county-map path[data-precinct][tabindex="0"]')).to_have_count(1)
   path.press('Escape');expect(card).to_be_hidden();path.press('ArrowRight');expect(card).to_be_visible()
   next_id=card.get_attribute('data-precinct');assert next_id!=pid
   expect(page.locator(f'#county-map path[data-precinct="{next_id}"]')).to_be_focused()
   page.locator(f'#county-map path[data-precinct="{next_id}"]').press('Enter')
   expect(card).to_be_hidden();expect(page.locator('#selection-title')).to_have_text('Precinct '+next_id)
   REPORT['checks'].append('Roving map focus exposes details; arrows change polygons; Escape dismisses; Enter opens the native profile')
   # True mouse hover and touch select use a point inside the rendered polygon.
   page.evaluate('(pid)=>Atlas.map.fitBounds(Atlas.layers.get(pid).getBounds(),{padding:[35,35],animate:false})',pid)
   point=page.evaluate('''pid=>{const e=Atlas.layers.get(pid).getElement(),b=e.getBBox(),m=e.getScreenCTM(),r=document.getElementById('county-map').getBoundingClientRect();for(let i=1;i<40;i++)for(let j=1;j<40;j++){const q=new DOMPoint(b.x+b.width*i/40,b.y+b.height*j/40);if(!e.isPointInFill(q))continue;const p=q.matrixTransform(m);if(p.x>r.left&&p.x<r.right&&p.y>r.top&&p.y<r.bottom&&document.elementFromPoint(p.x,p.y)===e)return {x:p.x,y:p.y};}throw Error('No visible interior point');}''',pid)
   page.mouse.move(point['x'],point['y']);expect(card).to_be_visible();expect(card).to_have_attribute('data-precinct',pid)
   page.screenshot(path=str(OUT/'actual-pointer.png'))
   page.evaluate('window.__touchEvents=[];for(const type of ["pointerdown","pointerup","click","focusin","blur"])document.addEventListener(type,e=>window.__touchEvents.push({type,target:e.target.dataset.precinct,x:e.clientX,y:e.clientY}),true)')
   page.touchscreen.tap(point['x'],point['y']);REPORT['touch_events']=page.evaluate('window.__touchEvents');REPORT['touch_point']=point;expect(card).to_be_hidden();expect(page.locator('#selection-title')).to_have_text('Precinct '+pid)
   REPORT['checks'].append('Actual pointer over a visible polygon opens the card; touch selection keeps the existing profile and dismisses the hover card')
   page.mouse.move(0,0)
   # Updates clear old details; re-enter uses the new selected date/cohort/mode.
   enter();page.get_by_role('button',name='Day 1',exact=True).click();expect(card).to_be_hidden();enter()
   expect(card.locator('.hover-dates')).to_have_text('Oct 19, 2026 / Oct 21, 2024')
   page.locator('#demographic-mode').click();page.wait_for_function('demoReady()',timeout=120000);expect(card).to_be_hidden();enter();expect(card.locator('.hover-census-heading b')).to_have_text(f"{counts['vap']:,}")
   page.locator('#metric').select_option('under18');page.wait_for_function('demoReady()',timeout=120000);enter()
   age=next(m for m in census['metrics'] if m['id']=='under18');expect(card.locator('.hover-current-metric dd')).to_have_text(f"{counts[age['numerator']]/counts[age['denominator']]*100:.1f}%")
   page.locator('#primary-mode').click();page.wait_for_function('demoReady()',timeout=120000);page.locator('#map-county').select_option(c['id']);page.wait_for_function('(c)=>Atlas.layer?.getLayers()[0]?.feature.properties.county===c&&document.getElementById("map-loading").hidden',arg=c['id']);enter()
   primary=api('/api/primary');pm=primary['metrics'][0];pr=primary['counties'].get(c['id'],{}).get('precincts',{}).get(pid,{}).get('counts',{})
   value=f"{pr[pm['numerator']]/pr[pm['denominator']]*100:.1f}%" if pr.get(pm['numerator']) is not None and pr.get(pm['denominator'],0)>0 else '—'
   expect(card.locator('.hover-primary dd')).to_have_text(value)
   page.locator('#cohort').select_option('unchanged');expect(card).to_be_hidden();enter();expect(card.locator('.hover-comparison b')).to_have_text('Unavailable')
   # A missing selected-day comparison still exposes native Census and guarded reference data.
   page.locator('#cohort').select_option('matched');page.get_by_role('button',name='Day 1',exact=True).click();page.locator('#map-county').select_option('ellis')
   page.wait_for_function('Atlas.layer?.getLayers()[0]?.feature.properties.county==="ellis"&&document.getElementById("map-loading").hidden',timeout=120000)
   missing=page.evaluate('()=>{const l=Atlas.layer.getLayers().find(l=>Atlas.censusCounts("ellis",l.feature.properties.precinct)?.vap>0);l.fire("mouseover",{originalEvent:{clientX:500,clientY:500}});return l.feature.properties.precinct;}')
   expect(card).to_be_visible();expect(card.locator('.hover-comparison b')).to_have_text('Unavailable');expect(card.locator('.hover-turnout strong').nth(0)).to_have_text('—')
   assert census['counties']['ellis']['precincts'][missing]['counts']['vap']>0
   expect(card.locator('.hover-census-heading b')).to_have_text(f"{census['counties']['ellis']['precincts'][missing]['counts']['vap']:,}")
   # Incomplete presidential membership must never show a partial party share.
   unknown=next(({'county':r['id'],'index':i,'precinct':g['new'][0]} for r in references.values() for i,g in enumerate(r['groups']) if any(old not in r['presidential'] for old in g['old'])),None)
   assert unknown
   page.locator('#map-county').select_option(unknown['county']);page.wait_for_function('(id)=>Atlas.layer?.getLayers()[0]?.feature.properties.county===id&&document.getElementById("map-loading").hidden',arg=unknown['county'],timeout=120000)
   page.evaluate('(q)=>Atlas.layers.get(q.precinct).fire("mouseover",{originalEvent:{clientX:500,clientY:500}})',unknown);expect(card.locator('.hover-party b')).to_have_text('Unknown')
   page.locator('#precinct-trends-tab').click();expect(card).to_be_hidden()
   REPORT['checks'].append('Date/mode/cohort changes clear stale cards; unpaired turnout stays unavailable while Census remains; incomplete presidential groups stay Unknown; navigation closes the card')
   assert not REPORT['javascript_errors'];REPORT['passed']=True
  finally:browser.close()
if __name__=='__main__':
 try:run()
 except BaseException:REPORT['passed']=False;REPORT['failure']=traceback.format_exc();raise
 finally:(OUT/'verification.json').write_text(json.dumps(REPORT,indent=2)+'\n');print(json.dumps(REPORT),flush=True)
