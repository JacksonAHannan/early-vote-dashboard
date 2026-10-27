#!/usr/bin/env python3
"""Recovered county coverage, linked geometry, Census and real image exports."""
import json,os
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[2]
BASE=os.environ.get('TURNOUT_TEST_URL','http://127.0.0.1:8743').rstrip('/')
OUT=ROOT/'analysis/county-recovery'/os.environ.get('TURNOUT_TEST_TAG','native');OUT.mkdir(parents=True,exist_ok=True)
ADDED='aransas borden bowie cass coleman cooke culberson henderson lamar medina redriver refugio roberts vanzandt ward zapata zavala johnson hunt liberty hopkins maverick matagorda gonzales shelby somervell dimmit mcculloch martin hudspeth sansaba mason mcmullen'.split()
RECOVERED=['dallas','montgomery','waller','washington','sanpatricio']
REPORT={'url':BASE,'checks':[],'errors':[],'images':[]}
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
 page=browser.new_page(viewport={'width':1512,'height':1100},accept_downloads=True,reduced_motion='reduce')
 page.on('pageerror',lambda e:REPORT['errors'].append(str(e)))
 try:
  page.goto(BASE+'/#precinct-explore',wait_until='networkidle',timeout=180000)
  page.wait_for_function('data&&Visuals&&Atlas.layer&&census&&places',timeout=120000)
  state=page.evaluate('({days:data.days,counties:data.counties.map(c=>({id:c.id,name:c.name,groups:c.reference_groups,periods:c.periods.map(p=>({day:p.day,coverage:p.coverage}))})),census:census.counties,places:places.counties})')
  counties={c['id']:c for c in state['counties']};assert len(counties)>=248
  for id in RECOVERED:assert any(p['day']==state['days'] and p['coverage']['available_groups']>0 for p in counties[id]['periods']),id
  for id in ADDED:
   c=counties[id];assert any(p['coverage']['available_groups']>0 for p in c['periods']),id
   geometry=page.evaluate('async id=>{const r=await fetch("/api/map/"+id);if(!r.ok)throw Error(id+" mapHTTP"+r.status);return r.json();}',id)
   pcs={p:i for i,g in enumerate(c['groups']) for p in g['new']}
   assert {f['properties']['precinct'] for f in geometry['features']}==set(pcs),id
   for f in geometry['features']:
    pc=f['properties']['precinct'];assert f['properties']['group']==pcs[pc]
    assert pc in state['census'][id]['precincts'] and pc in state['places'][id]['precincts'],(id,pc)
  REPORT['checks'].append('All33 additions have paired observations, complete linkednative geometry, Census/place profiles; all5 repaired counties retain latest-day pairs')
  for id in RECOVERED+['henderson','johnson','medina','mcmullen']:
   c=counties[id];cutoff=max(p['day'] for p in c['periods'] if p['coverage']['available_groups']>0)
   page.get_by_role('button',name='Day '+str(cutoff),exact=True).click();page.locator('#county').select_option(id)
   page.wait_for_function('(id)=>Atlas.county===id&&document.getElementById("map-loading").hidden',arg=id,timeout=120000)
   expect(page.locator('#explore-scope')).to_contain_text(c['name'])
   assert page.locator('#regression-chart .regression-point').count()>0,(id,'partisan points')
   assert page.locator('#groups tbody tr').count()>0
  REPORT['checks'].append('Recovered and new full/partialcounty selections render matchedpoints, native map andprecinct records')
  page.get_by_role('button',name='Day '+str(state['days']),exact=True).click();page.locator('#county').select_option('dallas');page.wait_for_function('Atlas.county==="dallas"&&document.getElementById("map-loading").hidden')
  page.locator('#regression-scale').select_option('full')
  point=page.locator('#regression-chart .regression-point[aria-hidden="false"]').first;point.focus();point.press('Enter')
  page.wait_for_function('selection?.county==="dallas"&&document.getElementById("selection-panel").dataset.county==="dallas"')
  page.locator('#workspace').screenshot(path=str(OUT/'dallas-linked.png'))
  png(page,'regression','dallas-regression');png(page,'map','dallas-map')
  page.locator('#county').select_option('henderson');page.locator('#demographic-mode').click();page.locator('#metric').select_option('non_white_vap')
  page.wait_for_function('demoReady()&&Atlas.county==="henderson"&&document.getElementById("map-loading").hidden',timeout=120000)
  assert page.locator('#regression-chart .regression-point').count()>0
  png(page,'regression','henderson-demographics')
  for width in [1512,390]:
   page.set_viewport_size({'width':width,'height':1100});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
   page.locator('#workspace').screenshot(path=str(OUT/f'henderson-{width}.png'))
  REPORT['checks'].append('Dallas point/map linkage, newcounty demographic regression, three actualPNG exports and desktop/mobile layouts pass')
  assert not REPORT['errors'],REPORT['errors']
 finally:
  (OUT/'verification.json').write_text(json.dumps(REPORT,indent=2));browser.close()
print(json.dumps(REPORT,indent=2))
