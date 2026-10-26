#!/usr/bin/env python3
"""Independent all-county bucket arithmetic, persistent filters, sticky layout and PNG.

TURNOUT_TEST_URL=http://127.0.0.1:8741 uv run --with playwright --with pillow python dashboard/tests/matrix_total.py
Set TURNOUT_MATRIX_SERVED=1 to verify deployed assets without routing local changes.
"""
import json,math,os,traceback
import xml.etree.ElementTree as ET
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[2]
BASE=os.environ.get('TURNOUT_TEST_URL','http://127.0.0.1:8741').rstrip('/')+'/'
SERVED=os.environ.get('TURNOUT_MATRIX_SERVED')=='1'
TAG=os.environ.get('TURNOUT_TEST_TAG','local')
OUT=ROOT/'analysis/matrix-total'/TAG;OUT.mkdir(parents=True,exist_ok=True)
REPORT={'url':BASE,'served':SERVED,'checks':[],'javascript_errors':[]}
def check_column(page):
 state=page.evaluate('({snapshot:{counties:data.counties.map(c=>({reference_groups:c.reference_groups,periods:c.periods.map(p=>({day:p.day,coverage:p.coverage,county_2024:p.county_2024,county_2026:p.county_2026,buckets:p.buckets}))}))},day,cohort,mode,demo:demoViews?.all?{bins:demoViews.all.bins}:null,rows:[...document.querySelectorAll("#matrix tbody tr")].map(r=>({text:r.querySelector(".matrix-total").textContent,title:r.querySelector(".matrix-total").title})),footer:[...document.querySelectorAll("#matrix tfoot .matrix-total")].map(e=>e.textContent)})')
 periods=[p for c in state['snapshot']['counties'] for p in c['periods'] if p['day']==state['day'] and p.get('coverage',{}).get('available_groups',1)>0]
 if state['mode']=='partisan':
  bins=[{'groups':sum(p['buckets'][i][state['cohort']]['groups'] for p in periods),'votes_2024':sum(p['buckets'][i][state['cohort']]['votes_2024'] for p in periods),'votes_2026':sum(p['buckets'][i][state['cohort']]['votes_2026'] for p in periods)} for i in range(6)]
 else:bins=state['demo']['bins']
 assert len(state['rows'])==len(bins)
 for row,b in zip(state['rows'],bins):
  ratio=b['votes_2026']/b['votes_2024'] if b['votes_2024'] else None
  if ratio is None:assert row['text']=='—',row
  else:assert math.isclose(float(row['text'].rstrip('†%')),ratio*100,abs_tol=.05000001),(row,b)
  assert f"{b['votes_2026']:,} / {b['votes_2024']:,} votes; {b['groups']} groups" in row['title'],(row,b)
 n=sum(p['county_2026'] for p in periods);o=sum(p['county_2024'] for p in periods)
 assert f'{n:,} / {o:,}' in state['footer'][0]
 assert state['footer'][1]==f"{sum(p['coverage']['available_precincts'] for p in periods):,} / {sum(len(g['new']) for c in state['snapshot']['counties'] for g in c['reference_groups']):,}"
 print(f"Verified {state['mode']} / {state['cohort']} / day {state['day']}",flush=True)
 return state['rows']
def main():
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
  page=browser.new_page(viewport={'width':1512,'height':1100},accept_downloads=True,reduced_motion='reduce')
  page.on('pageerror',lambda e:REPORT['javascript_errors'].append(str(e)))
  if not SERVED:
   for name in ['app.js','style.css']:
    page.route('**/'+name,lambda route:route.fulfill(path=str(ROOT/'dashboard/static'/Path(route.request.url.split('?')[0]).name)))
  try:
   page.goto(BASE,wait_until='networkidle',timeout=120000)
   page.wait_for_function('data&&window.Visuals&&Tracking.view',timeout=120000)
   page.locator('#precincts-tab').click();page.locator('#precinct-trends-tab').click()
   expect(page.locator('#matrix th.matrix-total')).to_have_text('All Counties')
   original=check_column(page)
   for action in ['next','search','empty','county']:
    if action=='next':page.locator('#matrix-next').click()
    elif action=='search':page.locator('#matrix-search').fill('Harris')
    elif action=='empty':page.locator('#matrix-search').fill('no such county qqq')
    else:page.locator('#county').select_option('tarrant')
    assert check_column(page)==original,action
    expect(page.locator('#matrix th:nth-child(2)')).to_have_text('All Counties')
   REPORT['checks'].append('All-county vote sums and coverage persist through pagination, search, no matches and county selection')
   for mode in ['partisan','demographic','primary']:
    page.locator('#'+mode+'-mode').click()
    if mode=='demographic':page.locator('#metric').select_option('non_white_vap')
    for cohort in ['matched','unchanged']:
     page.locator('#cohort').select_option(cohort)
     for day in [1,3]:
      page.get_by_role('button',name=f'Day {day}',exact=True).click()
      page.wait_for_function('mode==="partisan"||demoReady()',timeout=120000)
      check_column(page)
   REPORT['checks'].append('Independent pooled sums follow both cohorts, days 1/3 and partisan/non-white/primary classifications')
   page.locator('#partisan-mode').click();page.locator('#cohort').select_option('matched');page.locator('#county').select_option('all')
   for width in [1512,768,390]:
    page.set_viewport_size({'width':width,'height':1100})
    page.locator('#matrix').scroll_into_view_if_needed()
    positions=page.evaluate('()=>{const box=document.getElementById("matrix"),label=box.querySelector("tbody .band"),total=box.querySelector("tbody .matrix-total"),rect=el=>({x:el.getBoundingClientRect().x,width:el.getBoundingClientRect().width});box.scrollLeft=0;const before={label:rect(label),total:rect(total)};box.scrollLeft=box.scrollWidth;return {before,after:{label:rect(label),total:rect(total)},overflow:document.documentElement.scrollWidth>innerWidth,scroll:box.scrollLeft};}')
    assert positions['scroll']>0 and not positions['overflow'],positions
    for key in ['label','total']:assert abs(positions['before'][key]['x']-positions['after'][key]['x'])<1,positions
    assert abs(positions['after']['label']['x']+positions['after']['label']['width']-positions['after']['total']['x'])<1,positions
    page.locator('#matrix').screenshot(path=str(OUT/f'matrix-{width}.png'))
   REPORT['checks'].append('Bucket labels and All Counties stay adjacent and pinned while county columns scroll at desktop/tablet/mobile widths')
   # Export must include the aggregate and every visible county even when scrolled.
   headers=page.locator('#matrix thead th').all_text_contents()
   with page.expect_download(timeout=60000) as download:page.locator('[data-image="matrix"]').click()
   download.value.save_as(str(OUT/'matrix-full-export.png'))
   xml=page.evaluate('async()=>{const c=await Visuals.capture(Visuals.descriptor("matrix"));return decodeURIComponent(c.img.src.split(",").slice(1).join(","));}')
   export_text="".join(ET.fromstring(xml).itertext())
   assert all(label in export_text for label in headers),headers
   page.locator('#matrix-search').fill('no such county qqq')
   expect(page.locator('#matrix thead th')).to_have_count(2)
   assert page.evaluate('()=>{const m=document.getElementById("matrix"),a=m.querySelector("th:first-child").getBoundingClientRect(),b=m.querySelector("th.matrix-total").getBoundingClientRect();return Math.abs(a.right-b.left)<1&&document.documentElement.scrollWidth<=innerWidth;}')
   page.locator('#county').select_option('harris')
   expect(page.locator('#matrix thead th')).to_have_count(3)
   assert page.evaluate('()=>{const m=document.getElementById("matrix"),a=m.querySelector("th:first-child").getBoundingClientRect(),b=m.querySelector("th.matrix-total").getBoundingClientRect();return Math.abs(a.right-b.left)<1&&document.documentElement.scrollWidth<=innerWidth;}')
   page.locator('#county').select_option('all')
   page.locator('#matrix-search').fill('Harris')
   with page.expect_download(timeout=60000) as download:page.locator('[data-image="matrix"]').click()
   path=OUT/'matrix-export.png';download.value.save_as(str(path))
   with Image.open(path) as image:assert image.size==(1600,1000) and image.format=='PNG'
   xml=page.evaluate('async()=>{const c=await Visuals.capture(Visuals.descriptor("matrix"));return decodeURIComponent(c.img.src.split(",").slice(1).join(","));}')
   assert 'All Counties' in xml and 'Harris' in xml
   assert 'position: sticky' not in xml
   REPORT['checks'].append('Real full-page and filtered mobile PNGs retain All Counties; empty and single-county layouts keep pinned columns aligned')
   # Existing county drilldown remains a keyboard control after adding the column.
   link=page.locator('#matrix [data-county="harris"]');link.focus();link.press('Enter')
   expect(page.locator('#detail-name')).to_have_text('Harris precincts')
   assert not REPORT['javascript_errors'];REPORT['passed']=True
  finally:browser.close()
if __name__=='__main__':
 try:main()
 except BaseException:REPORT['passed']=False;REPORT['failure']=traceback.format_exc();raise
 finally:(OUT/'verification.json').write_text(json.dumps(REPORT,indent=2)+'\n');print(json.dumps(REPORT),flush=True)
