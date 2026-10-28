#!/usr/bin/env python3
"""County matrix selection, weighted totals, Census presets and image framing.

TURNOUT_TEST_URL=http://127.0.0.1:8743 uv run --with playwright --with pillow python dashboard/tests/county_selection.py
"""
import csv, io, json, math, os
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[2]
BASE=os.environ.get('TURNOUT_TEST_URL','http://127.0.0.1:8743').rstrip('/')
OUT=ROOT/'analysis/county-selection'/os.environ.get('TURNOUT_TEST_TAG','native')
OUT.mkdir(parents=True,exist_ok=True)
REPORT={'checks':[],'errors':[],'images':[]}

def check_totals(page):
 state=page.evaluate('''()=>{
 const ids=new Set(matrixSelectedCounties().map(c=>c.id));
 const bins=mode==='partisan'?Array.from({length:6},(_,i)=>data.counties[0].periods[0].buckets[i].label):matrixViews().all.bins.map(b=>b.label);
 const source=matrixMeasure==='daily'?matrixDaily.counties:data.counties;
 const expected=bins.map((_,i)=>{let old=0,current=0,groups=0;for(const c of source){if(!ids.has(c.id))continue;const p=c.periods.find(p=>p.day===day);if(!p||p.coverage?.available_groups===0)continue;const b=mode==='partisan'?p.buckets[i][cohort]:matrixViews()[c.id]?.bins[i];if(b){old+=b.votes_2024;current+=b.votes_2026;groups+=b.groups;}}return {old,current,groups};});
 return {expected,actual:[...document.querySelectorAll('#matrix tbody .matrix-selection-total')].map(n=>({text:n.textContent,title:n.title})),ids:[...ids]};
}''')
 for expected,actual in zip(state['expected'],state['actual'],strict=True):
  if expected['old']==0:assert actual['text']=='—',actual
  else:assert math.isclose(float(actual['text'].rstrip('†%')),100*expected['current']/expected['old'],abs_tol=.050001),(expected,actual)
  assert f"{expected['groups']} groups" in actual['title']
  assert f"{expected['current']:,} / {expected['old']:,} votes" in actual['title']
 return state

def image(page,name):
 with page.expect_download(timeout=120000) as event:page.locator('[data-image="matrix"]').click()
 path=OUT/(name+'.png');event.value.save_as(path)
 with Image.open(path) as im:
  assert im.width==1600 and 800<=im.height<=2600,im.size
  im.resize((800,round(im.height/2))).save(OUT/(name+'-preview.png'))
 REPORT['images'].append(name)

with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
 page=browser.new_page(viewport={'width':1512,'height':1100},accept_downloads=True,reduced_motion='reduce')
 page.on('pageerror',lambda e:REPORT['errors'].append(str(e)))
 try:
  page.goto(BASE+'/#precinct-trends',wait_until='networkidle',timeout=180000)
  page.wait_for_function('data&&matrixReady()&&Visuals',timeout=120000)
  # The all-selected total initially exactly equals All Counties.
  assert page.locator('#matrix tbody .matrix-total:not(.matrix-selection-total)').all_text_contents()==page.locator('#matrix tbody .matrix-selection-total').all_text_contents()
  page.locator('#matrix-county-picker summary').click()
  page.locator('#matrix-select-none').click()
  for name in ['Cameron','Hidalgo','Starr']:
   page.locator('#matrix-search').fill(name)
   page.get_by_role('checkbox',name=name,exact=True).check()
  assert page.get_by_role('checkbox',name='Starr',exact=True).evaluate('(n)=>n===document.activeElement')
  page.locator('#matrix-search').fill('')
  assert set(page.evaluate('matrixSelectedCounties().map(c=>c.id)'))=={'cameron','hidalgo','starr'}
  headers=page.locator('#matrix thead th').all_text_contents()
  assert headers[1:3]==['All Counties','All Selected Counties']
  assert len(headers)==6,headers
  page.locator('#matrix-county-picker summary').click()
  for mode in ['partisan','demographic','primary','place']:
   page.locator('#'+mode+'-mode').click()
   for cohort in ['matched','unchanged']:
    page.locator('#cohort').select_option(cohort)
    for measure in ['daily','cumulative']:
     page.locator('#matrix-measure').select_option(measure)
     page.wait_for_function('matrixReady()',timeout=120000)
     check_totals(page)
  REPORT['checks'].append('Manual county selection sums matched votes, never county percentages, across every classification/cohort and both measures')
  page.locator('#partisan-mode').click();page.locator('#cohort').select_option('matched')
  page.wait_for_function('matrixReady()')
  with page.expect_download() as event:page.locator('#download').click()
  rows=list(csv.DictReader(io.StringIO(event.value.path().read_text())))
  assert set(r['county'] for r in rows)<= {'Cameron','Hidalgo','Starr'}
  assert rows and all(r['measure']=='cumulative' for r in rows)
  image(page,'three-county-cumulative')
  assert '3 selected counties'==page.evaluate('Visuals.descriptor("matrix").scope')
  # Search changes the checkbox list, never the selected total or table.
  before=page.locator('#matrix').inner_html()
  page.locator('#matrix-county-picker summary').click();page.locator('#matrix-search').fill('Dallas')
  assert page.locator('#matrix').inner_html()==before
  page.locator('#matrix-select-none').click();check_totals(page)
  assert page.locator('#matrix thead th').all_text_contents()[1:]==['All Counties','All Selected Counties']
  expect(page.locator('#matrix tfoot .matrix-selection-total').first).to_have_text('Unavailable')
  page.locator('#matrix-select-shown').click()
  assert page.evaluate('matrixSelectedCounties().map(c=>c.id)')==['dallas']
  REPORT['checks'].append('Search, clear and select-search actions; zero selection stays unavailable; CSV includes selected counties only')
  # Presets come from whole-county Census counts, independently recomputed here.
  reference=json.loads((ROOT/'dashboard/data/county-reference.json').read_text())
  for metric in ['hispanic_vap','non_white_vap','black_vap','asian_vap','white_nh_vap','under18']:
   page.locator('#matrix-county-demographic').select_option(metric)
   page.wait_for_function('matrixCountyPreset&&matrixCountyPreset.metric===document.getElementById("matrix-county-demographic").value&&!matrixCountyPresetPending',timeout=120000)
   assert page.evaluate('matrixCountyPreset.day')==1  # County classification does not depend on latest-day turnout.
   for bucket in [0,4]:
    page.locator('#matrix-county-bucket').select_option(str(bucket));page.locator('#matrix-apply-bucket').click()
    m=next(m for m in reference['metrics'] if m['id']==metric)
    actual=page.evaluate('matrixSelectedCounties().map(c=>c.id)')
    available=set(page.evaluate('data.counties.map(c=>c.id)'));expected=[]
    for county_id,c in reference['counties'].items():
     n=c['counts'].get(m['numerator']);d=c['counts'].get(m['denominator'])
     if county_id in available and n is not None and d is not None and d>0 and 0<=n<=d:
      share=100*n/d;index=sum(share>=cut for cut in m['cuts'])
      if index==bucket:expected.append(county_id)
    assert set(actual)==set(expected),(metric,bucket,actual,expected)
    check_totals(page)
  REPORT['checks'].append('Every demographic preset uses independent whole-county Census counts, correct lower/upper boundaries and missing/zero denominator exclusion')
  page.locator('#matrix-county-demographic').select_option('place_type')
  page.wait_for_function('matrixCountyPreset?.metric==="place_type"&&!matrixCountyPresetPending',timeout=120000)
  page.locator('#matrix-county-bucket').select_option('0');page.locator('#matrix-apply-bucket').click()
  assert set(page.evaluate('matrixSelectedCounties().map(c=>c.id)'))==set(page.evaluate('matrixCountyPreset.counties.filter(c=>c.bucket===0&&data.counties.some(d=>d.id===c.id)).map(c=>c.id)'))
  # A demographic selection can still compare presidential precinct buckets.
  page.locator('#matrix-county-demographic').select_option('hispanic_vap')
  page.wait_for_function('matrixCountyPreset?.metric==="hispanic_vap"&&!matrixCountyPresetPending',timeout=120000)
  page.locator('#matrix-county-bucket').select_option('4');page.locator('#matrix-apply-bucket').click()
  assert 'Hispanic age 18+' in page.evaluate('Visuals.descriptor("matrix").scope')
  page.locator('#matrix-county-picker summary').click();image(page,'hispanic-counties-partisan-precincts')
  # A slow prior criterion cannot overwrite a newer choice or enable its Apply button.
  page.locator('#matrix-county-picker summary').click()
  page.evaluate("()=>{window.__presetFetch=window.fetch;window.__presetHeld=null;window.fetch=(input,init)=>String(input).includes('/api/county-buckets?')&&String(input).includes('metric=black_vap')?new Promise(resolve=>window.__presetHeld=()=>window.__presetFetch(input,init).then(resolve)):window.__presetFetch(input,init);}")
  page.locator('#matrix-county-demographic').select_option('black_vap')
  page.wait_for_function('Boolean(window.__presetHeld)')
  expect(page.locator('#matrix-apply-bucket')).to_be_disabled()
  page.locator('#matrix-county-demographic').select_option('hispanic_vap')
  page.wait_for_function('matrixCountyPreset?.metric==="hispanic_vap"&&!matrixCountyPresetPending',timeout=120000)
  before=page.locator('#matrix-county-bucket').inner_html()
  page.evaluate('async()=>{await window.__presetHeld();window.fetch=window.__presetFetch;}')
  assert page.locator('#matrix-county-bucket').inner_html()==before
  assert page.evaluate('matrixCountyPreset.metric')=='hispanic_vap'
  page.locator('#matrix-county-picker summary').click()
  REPORT['checks'].append('County checkbox keyboard focus survives updates; pending/obsolete county preset responses cannot apply or overwrite another criterion')
  # More than one page: selected pooled values and CSV must include the hidden page.
  page.locator('#matrix-county-picker summary').click();page.locator('#matrix-select-all').click();page.locator('#matrix-county-picker summary').click()
  before=check_totals(page);page.locator('#matrix-next').click();after=check_totals(page)
  assert before==after
  with page.expect_download() as event:page.locator('#download').click()
  rows=list(csv.DictReader(io.StringIO(event.value.path().read_text())))
  assert len(set(r['county'] for r in rows))>12
  for width in [1512,768,390]:
   page.set_viewport_size({'width':width,'height':1100});page.locator('#bucket-section').scroll_into_view_if_needed()
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
   boxes=page.evaluate('''()=>{const m=document.getElementById('matrix');m.scrollLeft=700;return [...m.querySelectorAll('thead th')].slice(0,3).map(n=>{const b=n.getBoundingClientRect();return {x:b.x,w:b.width};});}''')
   assert boxes[0]['x']>=0 and boxes[2]['x']+boxes[2]['w']<=width
   assert abs(boxes[1]['x']-boxes[0]['x']-boxes[0]['w'])<3,boxes
   assert abs(boxes[2]['x']-boxes[1]['x']-boxes[1]['w'])<3,boxes
   page.locator('#bucket-section').screenshot(path=str(OUT/f'county-selection-{width}.png'))
  REPORT['checks'].append('Place presets; full-selection totals/CSV survive pagination; both totals pinned on desktop/tablet/mobile; complete branded PNGs')
  assert not REPORT['errors'],REPORT['errors']
 finally:
  (OUT/'verification.json').write_text(json.dumps(REPORT,indent=2));browser.close()
print(json.dumps(REPORT,indent=2))
