#!/usr/bin/env python3
"""Daily/cumulative matrices: matched arithmetic, labels, exports and response races.

TURNOUT_TEST_URL=http://127.0.0.1:8743 uv run --with playwright --with pillow python dashboard/tests/matrix_measure.py
"""
import csv, io, json, math, os
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[2]
BASE=os.environ.get('TURNOUT_TEST_URL','http://127.0.0.1:8743').rstrip('/')
OUT=ROOT/'analysis/matrix-measure'/os.environ.get('TURNOUT_TEST_TAG','native');OUT.mkdir(parents=True,exist_ok=True)
REPORT={'checks':[],'errors':[],'images':[]}
def compare(a,b):
 assert len(a)==len(b),(len(a),len(b))
 for x,y in zip(a,b):
  assert [x[k] for k in ['groups','votes_2024','votes_2026']]==[y[k] for k in ['groups','votes_2024','votes_2026']],(x,y)
def download(page,name):
 with page.expect_download(timeout=120000) as event:page.locator('[data-image="matrix"]').click()
 path=OUT/(name+'.png');event.value.save_as(path)
 with Image.open(path) as im:
  assert im.width==1600 and 800<=im.height<=2000
  im.resize((800,round(im.height/2))).save(OUT/(name+'-preview.png'))
 desc=page.evaluate('Visuals.descriptor("matrix")')
 assert ('Same-day' if page.locator('#matrix-measure').input_value()=='daily' else 'Cumulative') in desc['title']
 REPORT['images'].append({'name':name,'period':desc['period'],'title':desc['title']})
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
 page=browser.new_page(viewport={'width':1512,'height':1100},accept_downloads=True,reduced_motion='reduce')
 page.on('pageerror',lambda e:REPORT['errors'].append(str(e)))
 try:
  page.goto(BASE+'/#precinct-trends',wait_until='networkidle',timeout=180000)
  page.wait_for_function('data&&Tracking.view&&Visuals',timeout=120000)
  expect(page.locator('#matrix-measure')).to_have_value('cumulative')
  baseline=page.locator('#matrix tbody .matrix-total:not(.matrix-selection-total)').all_text_contents()
  for mode in ['partisan','demographic','primary','place']:
   page.locator('#'+mode+'-mode').click()
   if mode=='demographic':page.locator('#metric').select_option('non_white_vap')
   for cohort in ['matched','unchanged']:
    page.locator('#cohort').select_option(cohort)
    for day in [1,3]:
     page.get_by_role('button',name=f'Day {day}',exact=True).click()
     page.locator('#matrix-measure').select_option('daily')
     page.wait_for_function('matrixReady()&&Tracking.view&&Tracking.key===Tracking.signature()',timeout=120000)
     # Independent existing timeline analyzer must agree with every pooled bucket.
     values=page.evaluate('()=>({bins:mode==="partisan"?Array.from({length:6},(_,i)=>matrixCounties().reduce((a,c)=>{const b=matrixBuckets(c)?.[i];for(const k of ["groups","votes_2024","votes_2026"])a[k]+=b?.[k]||0;return a;},{groups:0,votes_2024:0,votes_2026:0})):matrixViews().all.bins,trend:Tracking.view.buckets.map(b=>b.days.find(d=>d.day===day)),basis:document.getElementById("bucket-unit").textContent,period:document.getElementById("matrix-period").textContent})')
     expected=[{'groups':r['daily_groups'],'votes_2024':r['daily_2024'] or 0,'votes_2026':r['daily_2026'] or 0} for r in values['trend']]
     compare(values['bins'],expected)
     assert 'Same-day' in values['basis'] and '–' not in values['period']
     expect(page.locator('#matrix tfoot')).to_contain_text('Matched same-day votes')
     with page.expect_download() as event:page.locator('#download').click()
     if mode=='partisan':assert 'hispanic' not in event.value.suggested_filename
     rows=list(csv.DictReader(io.StringIO(event.value.path().read_text())))
     assert rows and all(r['measure']=='daily' for r in rows)
     assert sum(int(r['votes_2026']) for r in rows)==sum(b['votes_2026'] for b in values['bins'])
  REPORT['checks'].append('All four classifications, both cohorts and days 1/3: daily pooled bins and CSV agree with independent Rust timeline analyzer')
  page.locator('#cohort').select_option('matched');page.locator('#partisan-mode').click()
  page.wait_for_function('matrixReady()')
  pooled=page.locator('#matrix tbody .matrix-total:not(.matrix-selection-total)').all_text_contents()
  page.locator('#matrix-county-picker summary').click()
  page.locator('#matrix-search').fill('Harris')
  assert page.locator('#matrix tbody .matrix-total:not(.matrix-selection-total)').all_text_contents()==pooled
  page.locator('#county').select_option('tarrant');page.wait_for_function('matrixReady()')
  assert page.locator('#matrix tbody .matrix-total:not(.matrix-selection-total)').all_text_contents()==pooled
  assert page.locator('#matrix thead th').all_text_contents()[1:]==['All Counties','All Selected Counties','TarrantCoverage note'] or page.locator('#matrix thead th').all_text_contents()[1:]==['All Counties','All Selected Counties','Tarrant']
  page.locator('#county').select_option('all');page.wait_for_function('matrixReady()')
  page.locator('#matrix-county-picker summary').click()
  REPORT['checks'].append('Daily All Counties stays global through search and a single-county selection')
  page.locator('[data-matrix-layout="joint"]').click()
  for metric in ['hispanic_vap','non_white_vap','place_type']:
   page.locator('#matrix-metric').select_option(metric);page.wait_for_function('matrixReady()',timeout=120000)
   state=page.evaluate('()=>({v:matrixDaily.views.all,rows:[...document.querySelectorAll("#matrix tbody tr")].map(r=>[...r.querySelectorAll("td")].map(c=>({text:c.textContent,title:c.title})))})')
   for i,cells in enumerate(state['v']['partisan_matrix']['cells']):
    for k in ['groups','votes_2024','votes_2026']:assert sum(c[k] for c in cells)==state['v']['bins'][i][k]
    for j,cell in enumerate(cells):
     dom=state['rows'][i][j+1];assert 'Same-day' in dom['title']
     if cell['ratio'] is None:assert dom['text']=='—'
     else:assert math.isclose(float(dom['text'].rstrip('†%')),cell['ratio']*100,abs_tol=.050001)
   with page.expect_download() as event:page.locator('#download').click()
   rows=list(csv.DictReader(io.StringIO(event.value.path().read_text())))
   assert all(r['measure']=='daily' for r in rows)
   assert sum(int(r['votes_2026']) for r in rows)==state['v']['coverage']['included']['votes_2026']
  REPORT['checks'].append('Daily Hispanic, non-white and place × partisanship cells, marginals and CSV conserve matched totals and carry the basis')
  page.locator('#matrix-metric').select_option('hispanic_vap');page.wait_for_function('matrixReady()',timeout=120000)
  download(page,'joint-same-day')
  page.locator('#matrix-measure').select_option('cumulative');page.wait_for_function('matrixReady()',timeout=120000)
  assert 'Oct 19–21' in page.locator('#matrix-period').text_content()
  download(page,'joint-cumulative')
  with page.expect_download() as event:page.locator('#download').click()
  assert all(r['measure']=='cumulative' for r in csv.DictReader(io.StringIO(event.value.path().read_text())))
  # Hold a real daily request, switch back, then release the obsolete result.
  page.evaluate('()=>{window.__matrixFetch=window.fetch;window.__matrixHeld=null;window.fetch=(input,init)=>String(input).includes("/api/matrix-view")?new Promise(resolve=>window.__matrixHeld=()=>window.__matrixFetch(input,init).then(resolve)):window.__matrixFetch(input,init);matrixDailyKey="";}')
  page.locator('#matrix-measure').select_option('daily');page.wait_for_function('Boolean(window.__matrixHeld)')
  expect(page.locator('[data-image="matrix"]')).to_be_disabled();expect(page.locator('#download')).to_have_attribute('aria-disabled','true')
  page.locator('#matrix-measure').select_option('cumulative');page.wait_for_function('matrixReady()')
  before=page.locator('#matrix').inner_html()
  page.evaluate('async()=>{await window.__matrixHeld();window.fetch=window.__matrixFetch;}');page.wait_for_function('matrixDailyPending===""')
  assert page.locator('#matrix').inner_html()==before
  REPORT['checks'].append('Pending daily values block PNG/CSV; obsolete responses cannot replace cumulative values or labels')
  page.locator('[data-matrix-layout="counties"]').click();page.get_by_role('button',name='Day 3',exact=True).click()
  for basis in ['daily','cumulative']:
   page.locator('#matrix-measure').select_option(basis);page.wait_for_function('matrixReady()')
   download(page,'county-'+basis)
   with page.expect_download() as event:page.locator('#download').click()
   rows=list(csv.DictReader(io.StringIO(event.value.path().read_text())))
   assert rows and all(r['measure']==basis for r in rows)
  # Day 7 initial reference must be unchanged after visiting daily views.
  page.get_by_role('button',name='Day '+str(page.evaluate('data.days')),exact=True).click();page.wait_for_function('matrixReady()')
  assert page.locator('#matrix tbody .matrix-total:not(.matrix-selection-total)').all_text_contents()==baseline
  for width in [1512,768,390]:
   page.set_viewport_size({'width':width,'height':1100});page.locator('#bucket-section').scroll_into_view_if_needed()
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
   expect(page.locator('#matrix-measure')).to_be_visible()
   page.locator('#bucket-section').screenshot(path=str(OUT/f'matrix-{width}.png'))
  REPORT['checks'].append('Cumulative values preserved; native day/range labels, complete PNGs and desktop/tablet/mobile controls verified')
  assert not REPORT['errors'],REPORT['errors']
 finally:
  (OUT/'verification.json').write_text(json.dumps(REPORT,indent=2));browser.close()
print(json.dumps(REPORT,indent=2))
