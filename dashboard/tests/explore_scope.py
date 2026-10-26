"""Independent place-category arithmetic and linked geography/measure/export QA.

TURNOUT_TEST_URL=http://127.0.0.1:8743 uv run --with playwright --with pillow python dashboard/tests/explore_scope.py
Set TURNOUT_JOINT_STATIC=1 to check generated/hosted Pages artifacts.
"""
import collections,csv,importlib.util,io,json,math,os,traceback
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright,expect
spec=importlib.util.spec_from_file_location('matrix_transport',Path(__file__).with_name('joint_matrix.py'));t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)
BASE=t.BASE;OUT=t.ROOT/'analysis/explore-scope'/os.environ.get('TURNOUT_TEST_TAG','local');OUT.mkdir(parents=True,exist_ok=True)
REPORT={'url':BASE,'assertions':0,'checks':[],'javascript_errors':[]}
LABELS=['Rural Anglo','Rural Hispanic','Suburban','Exurban','Urban','Other / unclassified']
def check(ok,msg):REPORT['assertions']+=1;assert ok,msg
def category(c):
 v=c.get('vap',0)
 if v<0:return None
 keys=['city_vap','suburb_vap','fringe_vap','rural_vap','unclassified_vap']
 if any(k not in c or c[k]<0 for k in keys) or sum(c[k] for k in keys)!=v:return None
 winners=[k for k in keys[:4] if 2*c[k]>v]
 if not winners:return 5
 winner=winners[0]
 if winner=='rural_vap':return 0 if 2*c['white_nh_vap']>v else 1 if 2*c['hispanic_vap']>v else 5
 return {'city_vap':4,'suburb_vap':2,'fringe_vap':3}[winner]
def api_checks():
 s=t.api('/api/data');place=t.api('/api/places');census=t.api('/api/demographics');geo=t.api('/api/map/texas')
 check(len(place['counties'])==254 and len(geo['features'])==254,'all Texas counties represented')
 check({f['properties']['county'] for f in geo['features']}==set(place['counties']),'county map identities')
 for id,c in census['counties'].items():
  check(set(c['precincts'])==set(place['counties'][id]['precincts']),(id,'native ids'))
  for precinct,p in c['precincts'].items():
   a=place['counties'][id]['precincts'][precinct]['counts']
   for k in ['population','vap','white_nh_vap','hispanic_vap']:check(a[k]==p['counts'][k],(id,precinct,k))
   check(sum(a[k] for k in ['city_vap','suburb_vap','fringe_vap','rural_vap','unclassified_vap'])==a['vap'],(id,precinct,'partition'))
 for day in sorted({1,min(3,s['days']),s['days']}):
  for cohort in ['matched','unchanged']:
   payload=t.api(f'/api/demographic-view?day={day}&cohort={cohort}&metric=place_type&view=place');allbins=[[0,0,0] for _ in LABELS]
   for c in s['counties']:
    expected=[[0,0,0] for _ in LABELS];p=next((p for p in c['periods'] if p['day']==day),None)
    for g in p['groups'] if p else []:
     if not g.get('available',True) or cohort=='unchanged' and not g['unchanged']:continue
     rows=[place['counties'][c['id']]['precincts'].get(id,{}).get('counts',{}) for id in g['new']]
     counts={k:sum(row[k] for row in rows) for k in rows[0] if all(k in row for row in rows)} if rows else {}
     bucket=category(counts)
     if bucket is None:continue
     for i,n in enumerate([1,g['votes_2024'],g['votes_2026']]):expected[bucket][i]+=n
    v=payload['views'][c['id']];check(v['fit'] is None,'no OLS on categorical codes')
    check([b['label'] for b in v['bins']]==LABELS,'place labels')
    for index,(bin,counts) in enumerate(zip(v['bins'],expected)):
     check([bin[k] for k in ['groups','votes_2024','votes_2026']]==counts,(c['id'],day,cohort,index))
     for i,n in enumerate(counts):allbins[index][i]+=n
   for actual,expected in zip(payload['views']['all']['bins'],allbins):check([actual[k] for k in ['groups','votes_2024','votes_2026']]==expected,'pooled place counts')
 for method in ['total','in_person','mail']:
  v=t.api(f'/api/county-buckets?day=1&view=place&metric=place_type&method={method}');check(len(v['counties'])==254,'no county dropped')
  check([b['label'] for b in v['buckets']]==LABELS,'county place labels')
  for row in v['counties']:check(row['bucket']==category(place['counties'][row['id']]['assigned_totals']),(method,row['id'],'county place'))
 trends=t.api('/api/trends?county=all&cohort=matched&view=place&metric=place_type')
 for day in range(1,s['days']+1):
  v=t.api(f'/api/demographic-view?day={day}&cohort=matched&metric=place_type&view=place')['views']['all']
  for b,source in zip(v['bins'],trends['buckets']):
   p=next(x for x in source['days'] if x['day']==day)
   # An empty observed cohort is missing in timelines and zero groups in tables.
   if p['cumulative_groups']:
    check([p['cumulative_2024'],p['cumulative_2026'],p['cumulative_groups']]==[b['votes_2024'],b['votes_2026'],b['groups']],('same cutoff matrix/trend',day,b['label']))
 REPORT['checks'].append('All county identities and 8,950 native Census assignments reconcile; independent categorical buckets across days/cohorts, all three county methods, and cumulative timeline/table parity')
def browser_checks():
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True);page=browser.new_page(viewport={'width':1512,'height':1100},accept_downloads=True,reduced_motion='reduce')
  page.on('pageerror',lambda e:REPORT['javascript_errors'].append(str(e)))
  try:
   page.goto(BASE+'#precinct-explore',wait_until='networkidle',timeout=120000);page.wait_for_function('data&&Atlas.layer&&Atlas.county==="all"&&document.getElementById("map-loading").hidden',timeout=120000)
   page.get_by_role('button',name='Day 3',exact=True).click()
   check(page.locator('#county').input_value()=='all' and page.locator('#map-county').input_value()=='all','shared initial scope')
   check(page.evaluate('Atlas.layers.size')==254,'statewide county overview')
   expect(page.locator('.leaflet-control-attribution')).to_have_text('U.S. Census Bureau')
   expect(page.locator('#detail')).to_be_hidden();expect(page.locator('#selection-panel')).to_be_hidden()
   unsupported=page.evaluate('()=>[...Atlas.layers.keys()].find(id=>!data.counties.some(c=>c.id===id))')
   check(bool(unsupported),'county-only map fixture')
   page.evaluate('(id)=>Atlas.layers.get(id).fire("click")',unsupported)
   expect(page.locator('#county-workspace')).to_be_visible();check(page.evaluate('Tracking.stateCounty')==unsupported,'county-only polygon opens county totals')
   page.locator('#precincts-tab').click();page.locator('#precinct-explore-tab').click()

   check(page.locator('.regression-point').evaluate_all('(p)=>new Set(p.map(x=>x.dataset.county)).size')>100,'statewide regression')
   page.locator('#map-county').select_option('tarrant');page.wait_for_function('Atlas.county==="tarrant"&&Atlas.layer&&document.getElementById("map-loading").hidden')
   check(page.locator('#county').input_value()=='tarrant','map selection scopes all views')
   expect(page.locator('.leaflet-control-attribution')).to_have_text('Texas Legislative Council')
   check(page.locator('.regression-point').evaluate_all('(p)=>p.length>0&&p.every(x=>x.dataset.county==="tarrant")'),'county regression')
   expect(page.locator('#selection-title')).to_have_text('Tarrant County');expect(page.locator('#detail')).to_be_visible()
   page.locator('#county').select_option('travis');page.wait_for_function('Atlas.county==="travis"&&Atlas.layer&&document.getElementById("map-loading").hidden')
   check(page.locator('.regression-point').evaluate_all('(p)=>p.length>0&&p.every(x=>x.dataset.county==="travis")'),'toolbar selection scopes map and regression')
   page.locator('[data-panel="map-panel"]').click();page.locator('#county').select_option('tarrant')
   page.wait_for_function('Atlas.county==="tarrant"&&Atlas.layer&&document.getElementById("map-loading").hidden')
   page.locator('[data-panel="map-panel"]').click();page.wait_for_timeout(250)
   check(page.evaluate('Atlas.map.getBounds().contains(Atlas.layer.getBounds())'),'reopening map fits the newly selected county')
   page.locator('#map-reset').click();page.wait_for_function('county==="all"&&Atlas.county==="all"&&Atlas.layers.size===254&&document.getElementById("map-loading").hidden')
   circle=page.locator('.regression-point[data-county="bexar"][aria-hidden="false"]').first;circle.click();page.wait_for_function('county==="bexar"&&Atlas.county==="bexar"&&Atlas.active&&document.getElementById("map-loading").hidden')
   check(page.locator('.regression-point').evaluate_all('(p)=>p.every(x=>x.dataset.county==="bexar")'),'point drilldown scopes fit')
   page.locator('#selection-clear').click();check(page.locator('#county').input_value()=='bexar','clear point retains county')
   page.locator('#map-reset').click();page.wait_for_function('county==="all"&&Atlas.layers.size===254')
   page.locator('#map-layer').select_option('turnout');expect(page.locator('#map-legend')).to_contain_text('Cumulative 2026 as % of 2024')
   with page.expect_download(timeout=60000) as download:page.locator('[data-image="map"]').click()
   download.value.save_as(str(OUT/'texas-overview.png'))
   page.locator('#place-mode').click();page.wait_for_function('mode==="place"&&demoReady()&&Tracking.view?.metric==="place_type"',timeout=120000)
   page.locator('#map-layer').select_option('share');expect(page.locator('#map-legend')).to_contain_text('Rural Hispanic')
   check(page.locator('.regression-point').evaluate_all('(p)=>p.length>0&&p.some(x=>+x.dataset.x>10)&&p.every(x=>x.dataset.place)'),'numeric Harris axis with categorical colors')
   expect(page.locator('#regression-legend')).to_contain_text('Rural Hispanic')
   page.locator('#regression-place').select_option('0');check(page.locator('.regression-point').evaluate_all('(p)=>p.length>0&&p.every(x=>x.dataset.place==="Rural Anglo")'),'place filter')
   with page.expect_download() as download:page.locator('#regression-download').click()
   rows=list(csv.DictReader(io.StringIO(download.value.path().read_text())));check(rows and all(r['place_type']=='Rural Anglo' for r in rows),'place CSV records classification')
   page.locator('#regression-place').select_option('all');page.locator('#precinct-trends-tab').click();page.wait_for_function('Tracking.view?.metric==="place_type"')
   expect(page.locator('#bucket-unit')).to_have_text('Cumulative 2026 as % of 2024');check(page.locator('#matrix tbody tr').count()==6,'place bucket matrix')
   page.locator('[data-matrix-layout="joint"]').click();page.locator('#matrix-metric').select_option('place_type');page.wait_for_function('jointReady()&&jointViews.all.metric.id==="place_type"');check(page.locator('#matrix tbody tr').count()==6,'place by partisanship matrix');expect(page.locator('#matrix')).to_contain_text('Rural Hispanic')
   page.locator('[data-matrix-layout="counties"]').click()
   expect(page.locator('#daily-title')).to_contain_text('Same-day');page.locator('#tracking-measure').select_option('cumulative');expect(page.locator('#daily-title')).to_contain_text('Cumulative')
   page.locator('#counties-tab').click();page.locator('#county-place').click();page.wait_for_function('CountyView.ready()&&CountyView.mode==="place"',timeout=120000)
   check(page.evaluate('CountyView.view.buckets.length')==6,'county place buckets');expect(page.locator('#statewide-share-label')).to_have_text('Place type')
   card=page.evaluate('Visuals.descriptor("county-summary")');check(card['period'].startswith('Through ') and 'NCES 2025 / 2020 Census' in card['source'],'county card includes pre-opening mail and place provenance')
   page.locator('#precincts-tab').click();page.locator('#precinct-explore-tab').click();page.wait_for_function('Atlas.layer&&document.getElementById("map-loading").hidden')
   expect(page.locator('.leaflet-control-attribution')).to_have_text('U.S. Census Bureau')
   for width in [1512,768,390]:
    page.set_viewport_size({'width':width,'height':1100});page.locator('#workspace').scroll_into_view_if_needed();page.wait_for_timeout(180)
    check(page.evaluate('document.documentElement.scrollWidth<=innerWidth'),'no page overflow')
    page.screenshot(path=str(OUT/f'explore-{width}.png'),full_page=False)
   with page.expect_download(timeout=60000) as download:page.locator('[data-image="regression"]').click()
   download.value.save_as(str(OUT/'place-regression.png'))
   for file in ['texas-overview.png','place-regression.png']:
    with Image.open(OUT/file) as im:check((im.width == 1600 and 800 <= im.height <= 2000),'social PNG size')
   check(not REPORT['javascript_errors'],REPORT['javascript_errors']);REPORT['checks'].append('Statewide/counties/points share map and regression scope; clear/back behavior; explicit measures; categorical maps and numeric regression/filter/CSV; county place views; responsive layout and real PNGs')
  except BaseException:page.screenshot(path=str(OUT/'failure.png'),full_page=True);raise
  finally:browser.close()
if __name__=='__main__':
 try:api_checks();browser_checks();REPORT['passed']=True
 except BaseException:REPORT['passed']=False;REPORT['failure']=traceback.format_exc();raise
 finally:(OUT/'verification.json').write_text(json.dumps(REPORT,indent=2)+'\n');print(json.dumps(REPORT),flush=True)
