#!/usr/bin/env python3
"""Largest county source/reference recoveries, cumulative-only safety and exports."""
import json,os
from pathlib import Path
from PIL import Image
from texas_matching_stress import resolve
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[2];BASE=os.environ.get('TURNOUT_TEST_URL','http://127.0.0.1:8743').rstrip('/');OUT=ROOT/'analysis/large-county-recovery'/os.environ.get('TURNOUT_TEST_TAG','native');OUT.mkdir(parents=True,exist_ok=True)
REPORT={'url':BASE,'checks':[],'images':[],'errors':[]}
def png(page,key,name):
 expect(page.locator(f'[data-image="{key}"]')).to_be_enabled(timeout=120000)
 with page.expect_download(timeout=120000) as event:page.locator(f'[data-image="{key}"]').click()
 path=OUT/(name+'.png');event.value.save_as(path)
 with Image.open(path) as im:
  assert im.width==1600 and 800<=im.height<=2000
  im.resize((800,round(im.height/2))).save(OUT/(name+'-preview.png'))
 REPORT['images'].append(name)
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
 page=browser.new_page(viewport={'width':1512,'height':1100},accept_downloads=True,reduced_motion='reduce');page.on('pageerror',lambda e:REPORT['errors'].append(str(e)))
 try:
  page.goto(BASE+'/#precinct-explore',wait_until='networkidle',timeout=180000);page.wait_for_function('data&&references&&Visuals&&Atlas.layer&&census&&places',timeout=120000)
  snap=page.evaluate('data');counties={c['id']:c for c in snap['counties']};assert len(counties)>=248
  for id,n in [('dallas',686),('tarrant',639),('travis',284)]:assert next(p for p in counties[id]['periods'] if p['day']==1)['coverage']['available_precincts']>=n,(id,'Day1')
  refs={r['id']:r for r in page.evaluate('references')}
  for id,n,h,t in [('denton',240,191503,250521),('fortbend',175,179310,173592),('grayson',41,14800,50556)]:
   votes=refs[id]['presidential'];assert len(votes)==n and sum(v['harris'] for v in votes.values())==h and sum(v['trump'] for v in votes.values())==t
  for id,n in [('denton',206),('fortbend',100)]:
   day1=next(p for p in counties[id]['periods'] if p['day']==1);assert sum(len(g['new']) for g in day1['groups'] if g.get('available') and g['bucket'] is not None)>=n
  REPORT['checks'].append('Day1 paired geography restored in Dallas/Tarrant/Travis; full native Denton/Fort Bend canvasses conserve county totals and restore partisan coverage')
  page.get_by_role('button',name='Day 8',exact=True).click();page.locator('#county').select_option('tarrant');page.wait_for_function('Atlas.county==="tarrant"&&document.getElementById("map-loading").hidden',timeout=120000)
  anchor=next(s for s in counties['tarrant']['sources'] if s['date']=='2026-10-26' and s.get('cumulative'));assert anchor['allow_daily_difference'] is False
  assert next(p for p in counties['tarrant']['periods'] if p['day']==8)['coverage']['available_precincts']>0
  missing=page.evaluate('()=>{const p=Atlas.period("tarrant");const g=p.groups.find(g=>g.available===false);return {id:g.new[0],count:Atlas.counts("tarrant",g.new[0])};}');assert missing['count'] is None
  assert page.locator('#regression-chart .regression-point').count()>0
  png(page,'regression','tarrant-day8-cumulative');page.locator('#workspace').screenshot(path=str(OUT/'tarrant-day8.png'))
  # Actual dated SOS observations now exist for October26; the cumulative-only
  # anchor still must not be used to manufacture any daily value.
  page.locator('[data-section="precinct-trends"]').click() if page.locator('[data-section="precinct-trends"]').count() else page.evaluate('location.hash="precinct-trends"')
  page.locator('#matrix-measure').select_option('daily');page.wait_for_function('matrixReady()&&Tracking.view&&Tracking.key===Tracking.signature()',timeout=120000)
  tracking=page.evaluate('Tracking.view');assert tracking['county']=='tarrant'
  tc=counties['tarrant'];groups=tc['reference_groups'];oldids={p for g in groups for p in g['old']};newids={p for g in groups for p in g['new']}
  daily_old=resolve(tc['sources'],2024,oldids)[0][7] or {};daily_new=resolve(tc['sources'],2026,newids)[0][7] or {}
  for index,b in enumerate(tracking['buckets']):
   chosen=[g for g in groups if g['bucket']==index and all(p in daily_old for p in g['old']) and all(p in daily_new for p in g['new'])]
   row=next(d for d in b['days'] if d['day']==8)
   assert row['daily_groups']==len(chosen)
   assert (row['daily_2024'] or 0)==sum(daily_old[p] for g in chosen for p in g['old'])
   assert (row['daily_2026'] or 0)==sum(daily_new[p] for g in chosen for p in g['new'])
  REPORT['checks'].append('Tarrant dated cumulative anchor renders linked points/map; withheld precincts remain unknown and same-day charts do not derive votes from its different source')
  page.evaluate('location.hash="precinct-explore"');page.locator('#county').select_option('collin');page.wait_for_function('Atlas.county==="collin"&&document.getElementById("map-loading").hidden',timeout=120000)
  cp=next(p for p in counties['collin']['periods'] if p['day']==8);assert cp['coverage']['available_precincts']>200
  png(page,'regression','collin-day8-partisan')
  page.get_by_role('button',name='Day 1',exact=True).click()
  for id in ['dallas','grayson','denton','fortbend']:
   page.locator('#county').select_option(id);page.wait_for_function('(id)=>Atlas.county===id&&document.getElementById("map-loading").hidden',arg=id,timeout=120000)
   assert page.locator('#regression-chart .regression-point').count()>0
   png(page,'regression',id+'-day1-partisan')
  page.locator('#demographic-mode').click();page.locator('#metric').select_option('non_white_vap');page.wait_for_function('demoReady()',timeout=120000)
  png(page,'regression','fortbend-day1-demographic')
  for width in [1512,390]:
   page.set_viewport_size({'width':width,'height':1100});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');page.locator('#workspace').screenshot(path=str(OUT/f'fortbend-{width}.png'))
  REPORT['checks'].append('Recovered county partisan/demographic regressions, seven real PNGs and desktop/mobile layouts render without JavaScript errors')
  assert not REPORT['errors'],REPORT['errors']
 finally:
  (OUT/'verification.json').write_text(json.dumps(REPORT,indent=2));browser.close()
print(json.dumps(REPORT,indent=2))
