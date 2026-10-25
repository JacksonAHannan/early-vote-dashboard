#!/usr/bin/env python3
"""Verify versioned primary coverage, independently classified views and UI.

Uses the shared native/Pages reader. No official-source refresh or voter records.
"""
import bisect,csv,io,json,math,os,traceback
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from joint_matrix import api,BASE,TAG
from texas_matching_stress import metric_value,resolve
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'analysis/primary-expansion'/TAG;OUT.mkdir(parents=True,exist_ok=True)
ADDED=['bexar','collin','denton','harris','tarrant']
REPORT={'url':BASE,'checks':[],'javascript_errors':[],'api_cases':0}
def run():
 snapshot=api('/api/data');primary=api('/api/primary');edition=json.loads((ROOT/'dashboard/primary/2026.json').read_text());metric=primary['metrics'][0]
 assert primary['metrics']==edition['metrics']
 for county in edition['counties']:
  assert primary['counties'][county]['precincts']==edition['counties'][county]['precincts']
 assert sum(len(c['precincts']) for c in primary['counties'].values())==4351
 assert {c for c,d in primary['counties'].items() if d['precincts']}==set(ADDED+['dallas','ellis','hays','madison','mclennan','montgomery'])
 REPORT['checks'].append('Native/static primary route serves the versioned eleven-county edition: 4,351 precincts')
 for cohort in ['matched','unchanged']:
  for day in range(1,snapshot['days']+1):
   views=api(f'/api/demographic-view?day={day}&cohort={cohort}&metric=primary_dem_share&view=primary')['views'];pooled=[[0,0,0] for _ in range(5)]
   for county in snapshot['counties']:
    period=next((p for p in county['periods'] if p['day']==day),None);expected={};bins=[[0,0,0] for _ in range(5)]
    for i,g in enumerate(period['groups'] if period else []):
     if not g.get('available',True) or cohort=='unchanged' and not g['unchanged']:continue
     x=metric_value(primary,metric,county['id'],g['new'])
     if x is None:continue
     expected[i]=(x,g)
     b=bisect.bisect_right(metric['cuts'],x)
     for k,v in enumerate([1,g['votes_2024'],g['votes_2026']]):bins[b][k]+=v;pooled[b][k]+=v
    actual=views[county['id']];assert {p['group_index'] for p in actual['points']}==set(expected),(county['id'],day,cohort)
    for p in actual['points']:
     x,g=expected[p['group_index']];assert math.isclose(p['x'],x,abs_tol=1e-10);assert (p['votes_2024'],p['votes_2026'])==(g['votes_2024'],g['votes_2026'])
    for b,a in zip(bins,actual['bins']):assert [a[k] for k in ['groups','votes_2024','votes_2026']]==b
   for b,a in zip(pooled,views['all']['bins']):assert [a[k] for k in ['groups','votes_2024','votes_2026']]==b
   REPORT['api_cases']+=1
 REPORT['checks'].append('Every county/day and both cohorts: complete primary membership, summed ballot shares, regression points and pooled buckets agree with an independent oracle')
 # Check observed daily/cumulative comparisons for the five newly covered counties
 # directly against their qualified API source observations and fixed geography.
 refs={c['id']:c for c in api('/api/reference')}
 for cid in ADDED:
  county=next(c for c in snapshot['counties'] if c['id']==cid);ref=refs[cid]
  old=resolve(county['sources'],2024,{p for g in ref['groups'] for p in g['old']});new=resolve(county['sources'],2026,{p for g in ref['groups'] for p in g['new']})
  trend=api(f'/api/trends?county={cid}&cohort=matched&metric=primary_dem_share&view=primary')
  groups=[(g,metric_value(primary,metric,cid,g['new'])) for g in ref['groups']];groups=[(g,x) for g,x in groups if x is not None]
  for bucket in range(5):
   for d in trend['buckets'][bucket]['days'][:snapshot['days']]:
    for index,measure in [(0,'daily'),(1,'cumulative')]:
     a=old[index][d['day']-1];b=new[index][d['day']-1]
     valid=[g for g,x in groups if bisect.bisect_right(metric['cuts'],x)==bucket and a is not None and b is not None and all(p in a for p in g['old']) and all(p in b for p in g['new'])]
     expected=(sum(sum(a[p] for p in g['old']) for g in valid),sum(sum(b[p] for p in g['new']) for g in valid)) if valid else (None,None)
     assert (d[measure+'_2024'],d[measure+'_2026'])==expected,(cid,bucket,d['day'],measure,expected,d)
   for d in trend['buckets'][bucket]['days'][snapshot['days']:]:assert d['daily_2026'] is None and d['cumulative_2026'] is None
 REPORT['checks'].append('New county daily/cumulative primary buckets use independently matched observations on each date; future 2026 days stay empty')
 with sync_playwright() as pw:
  browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True);page=browser.new_page(viewport={'width':1512,'height':1050},accept_downloads=True)
  page.on('pageerror',lambda e:REPORT['javascript_errors'].append(str(e)))
  try:
   page.goto(BASE,wait_until='networkidle',timeout=120000);page.wait_for_function('data&&Atlas.layer',timeout=120000)
   page.locator('#precincts-tab').click();page.locator('#primary-mode').click();page.wait_for_function('demoReady()',timeout=120000);page.get_by_role('button',name='Day 3',exact=True).click();page.wait_for_function('demoReady()',timeout=120000)
   for cid in ADDED:
    page.locator('#county').select_option(cid);page.wait_for_function('(c)=>demoReady()&&county===c',arg=cid,timeout=120000)
    assert page.evaluate('demoViews[county].points.length')>0,cid
    assert page.evaluate('demoViews[county].coverage.included.groups')>0,cid
    page.locator('#precinct-explore-tab').click();assert page.locator('.regression-point').count()>0,cid
    page.locator('#map-county').select_option(cid);page.wait_for_function('(c)=>Atlas.layer?.getLayers()[0]?.feature.properties.county===c&&document.getElementById("map-loading").hidden',arg=cid,timeout=120000)
    pid=next(pid for pid,p in primary['counties'][cid]['precincts'].items() if p['counts']['primary_total']>0)
    page.locator('#county-map').scroll_into_view_if_needed();page.evaluate('(pid)=>Atlas.layers.get(pid).fire("mouseover",{originalEvent:{clientX:500,clientY:500}})',pid)
    counts=primary['counties'][cid]['precincts'][pid]['counts'];expect(page.locator('#precinct-tooltip .hover-primary dd')).to_have_text(f"{counts['primary_dem']/counts['primary_total']*100:.1f}%")
    page.locator('#precinct-trends-tab').click();page.wait_for_function('Tracking.view&&Tracking.key===Tracking.signature()',timeout=120000)
    assert page.evaluate('Tracking.view.coverage.included_counties.includes(county)'),cid
   page.locator('#county').select_option('all');page.wait_for_function('demoReady()',timeout=120000)
   page.locator('#matrix').scroll_into_view_if_needed();page.screenshot(path=str(OUT/'primary-counties.png'))
   with page.expect_download() as dl:page.locator('#download').click()
   path=OUT/'primary-buckets.csv';dl.value.save_as(str(path));rows=list(csv.DictReader(path.open()))
   for name in ['Bexar','Collin','Denton','Harris','Tarrant']:assert any(r['county']==name and int(r['groups'])>0 for r in rows),name
   REPORT['checks'].append('All five added counties have primary points, bucket rows, daily views and exported CSV; pooled view remains available')
   assert not REPORT['javascript_errors'];REPORT['passed']=True
  finally:browser.close()
if __name__=='__main__':
 try:run()
 except BaseException:REPORT['passed']=False;REPORT['failure']=traceback.format_exc();raise
 finally:(OUT/'verification.json').write_text(json.dumps(REPORT,indent=2)+'\n');print(json.dumps(REPORT),flush=True)
