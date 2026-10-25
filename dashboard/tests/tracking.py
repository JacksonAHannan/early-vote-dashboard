"""Daily timelines, primary maps, county-only tracking and responsive acceptance."""
from pathlib import Path
import os,json,csv
from playwright.sync_api import sync_playwright,expect
BASE=os.environ.get('TURNOUT_TEST_URL','http://127.0.0.1:8741')
OUT=Path(__file__).resolve().parents[2]/'analysis/daily-tracking/qa';OUT.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium');page=browser.new_page(viewport={'width':1512,'height':1050},reduced_motion='reduce');errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
 page.goto(BASE,wait_until='networkidle');page.wait_for_function('Tracking.view&&Tracking.state&&CountyView.view')
 # County-wide coverage is the landing view; precinct timelines are a separate workspace.
 expect(page.locator('#counties-tab')).to_have_attribute('aria-pressed','true')
 expect(page.locator('#county-workspace')).to_be_visible();expect(page.locator('#precinct-workspace')).to_be_hidden()
 expect(page.locator('#statewide-table tbody tr')).to_have_count(254)
 page.locator('#precincts-tab').click();page.locator('#precinct-trends-tab').click()
 expect(page.locator('#daily-section')).to_be_visible();expect(page.locator('#precinct-explore')).to_be_hidden()
 expect(page.locator('.daily-panel')).to_have_count(6)
 for i in range(6):
  panel=page.locator('.daily-panel').nth(i)
  expected=page.evaluate('(i)=>Tracking.view.buckets[i].days',i);assert len(expected)==12
  expect(panel.locator('.timeline-dot[data-year="2024"]')).to_have_count(sum(d['daily_2024'] is not None for d in expected))
  assert all(d['daily_2026'] is None for d in expected if d['day']>5)
  expect(panel.locator('.timeline-dot[data-year="2026"]')).to_have_count(5)
 original=page.locator('.daily-panel .year-2026').first.get_attribute('d')
 page.locator('.daily-panel .timeline-hit[data-day="5"]').first.focus();expect(page.locator('#daily-readout')).to_contain_text('Day 5')
 page.locator('#tracking-measure').select_option('cumulative');assert page.locator('.daily-panel .year-2026').first.get_attribute('d')!=original
 with page.expect_download() as download:page.locator('#tracking-download').click()
 dest=OUT/'daily-buckets.csv';download.value.save_as(str(dest));rows=list(csv.DictReader(dest.open()));assert len(rows)==72 and sum(row['daily_2026']=='' for row in rows)==42
 page.screenshot(path=str(OUT/'daily-desktop.png'),full_page=True)
 # Primary membership and partisan-colored dots; clicking links to native geometry.
 page.locator('#primary-mode').click();page.wait_for_function('mode==="primary"&&demoReady()&&Tracking.view?.metric==="primary_dem_share"')
 expect(page.locator('.daily-panel')).to_have_count(6)
 page.locator('#precinct-explore-tab').click();page.wait_for_function('Atlas.layer&&document.getElementById("county-map").clientWidth>0')
 expect(page.locator('#precinct-trends')).to_be_hidden();expect(page.locator('#regression-chart svg')).to_have_attribute('data-scale','auto')
 expect(page.locator('.regression-quadrant')).to_have_count(0)
 assert page.locator('.regression-point').count()>0
 assert set(page.locator('.regression-point').evaluate_all('(els)=>els.map(e=>e.getAttribute("fill"))')).issubset({'#285b91','#a84236','#77818e'})
 dot=page.locator('.regression-point[tabindex="0"]').first;selected=dot.get_attribute('data-id');dot.focus();dot.press('Enter');page.wait_for_function('(id)=>Atlas.active&&`${Atlas.active.county}:${Atlas.active.group_index}`===id',arg=selected)
 assert page.evaluate('[...Atlas.layers.values()].filter(l=>l.feature.properties.group===Atlas.active.group_index).every(l=>Atlas.map.getBounds().contains(l.getBounds()))')
 with page.expect_download() as download:page.locator('#regression-download').click()
 dest=OUT/'primary-regression.csv';download.value.save_as(str(dest));assert 'primary_dem_share_pct' in next(csv.reader(dest.open()))
 page.locator('#precinct-trends-tab').click();expect(page.locator('#daily-section')).to_be_visible()
 with page.expect_download() as download:page.locator('#tracking-download').click()
 dest=OUT/'primary-daily.csv';download.value.save_as(str(dest));primary_rows=list(csv.DictReader(dest.open()));assert len(primary_rows)==72 and 'Compared precincts' in {r['bucket'] for r in primary_rows}
 page.screenshot(path=str(OUT/'daily-primary.png'),full_page=True)
 # All six demographic metrics, including non-white, drive the same daily engine.
 page.locator('#demographic-mode').click();page.locator('#metric').select_option('non_white_vap');page.wait_for_function('demoReady()&&Tracking.view?.metric==="non_white_vap"')
 expect(page.locator('.daily-panel')).to_have_count(6)
 page.locator('#precinct-explore-tab').click();assert page.locator('.regression-point').count()>0
 page.locator('#precinct-trends-tab').click()
 for mode in ['daily','cumulative']:page.locator('#tracking-measure').select_option(mode)
 page.screenshot(path=str(OUT/'daily-demographic.png'),full_page=True)
 # Replaceable Ellis cumulative files cannot invent earlier daily participation.
 page.locator('#partisan-mode').click();page.locator('#county').select_option('ellis');page.wait_for_function('Tracking.view?.county==="ellis"')
 page.locator('#tracking-measure').select_option('daily');panel=page.locator('.daily-panel').first;expect(panel.locator('.timeline-dot[data-year="2026"]')).to_have_count(1)
 expect(panel.locator('.timeline-dot[data-year="2026"]')).to_have_attribute('data-day','5')
 page.locator('#tracking-measure').select_option('cumulative');expect(panel.locator('.timeline-dot[data-year="2026"]')).to_have_count(2)
 # An unsupported primary county has a real empty state.
 page.locator('#county').select_option('travis');page.locator('#primary-mode').click();page.wait_for_function('Tracking.view?.county==="travis"&&Tracking.view?.metric==="primary_dem_share"');expect(page.locator('#daily-charts')).to_contain_text('No comparable')
 # County-only records remain available; Harris now also links to precinct analysis.
 page.locator('#counties-tab').click();expect(page.locator('#statewide-section')).to_be_visible();expect(page.locator('#precinct-workspace')).to_be_hidden()
 assert page.evaluate('CountyView.mode==="partisan"&&mode==="primary"'), 'County and precinct classification filters must remain independent'
 page.locator('#statewide-search').fill('Harris');expect(page.locator('#statewide-table tbody tr')).to_have_count(2)  # Harris and Harrison
 page.locator('[data-state-county="harris"]').click();expect(page.locator('#statewide-county-title')).to_contain_text('Harris');expect(page.locator('#statewide-precincts')).to_be_visible()
 expect(page.locator('#statewide-chart .timeline-dot[data-year="2024"]')).to_have_count(12)
 page.locator('#statewide-chart .timeline-hit[data-day="12"]').focus();expect(page.locator('#statewide-readout')).to_contain_text('2026 Oct 30: —')
 page.locator('#statewide-search').fill('Johnson');page.locator('[data-state-county="johnson"]').click();expect(page.locator('#statewide-precincts')).to_be_hidden();expect(page.locator('#statewide-note')).to_contain_text('precinct detail unavailable')
 page.locator('#statewide-search').fill('Nueces');page.locator('[data-state-county="nueces"]').click();assert page.locator('#statewide-chart .timeline-dot[data-year="2026"][data-day="5"]').count()==0
 page.locator('#statewide-measure').select_option('cumulative');expect(page.locator('#statewide-chart .timeline-dot[data-year="2026"][data-day="5"]')).to_have_count(1)
 page.locator('#statewide-reset').click();page.locator('#statewide-search').fill('');expect(page.locator('#statewide-table tbody tr')).to_have_count(254)
 for key in ['name','new','old','ratio']:page.locator(f'[data-state-sort="{key}"]').click()
 # Restore a populated analytical view before screenshots.
 page.locator('#precincts-tab').click();page.locator('#precinct-trends-tab').click()
 page.locator('#county').select_option('all');page.locator('#demographic-mode').click();page.wait_for_function('Tracking.view?.county==="all"&&Tracking.view?.metric==="non_white_vap"');page.locator('#tracking-measure').select_option('daily')
 for width in [1512,768,390]:
  page.set_viewport_size({'width':width,'height':1000});page.wait_for_timeout(350);page.evaluate('window.scrollTo(0,0)')
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
  page.screenshot(path=str(OUT/f'daily-{width}.png'),full_page=True)
  page.screenshot(path=str(OUT/f'daily-viewport-{width}.png'))
  page.locator('#daily-section').screenshot(path=str(OUT/f'daily-charts-{width}.png'))
  if width==390:expect(page.locator('#daily-section .year-key')).to_be_visible()
 assert not errors,errors
 report={'status':'passed','javascript_errors':errors,'checks':['Counties landing view and separate precinct Trends/Explore navigation','independent county and precinct classification filters','twelve-day actual historical traces','future 2026 gaps','daily/cumulative switch','daily CSV','primary membership/map selection/CSV','primary partisan colors','non-white demographic timeline','Ellis honest daily/cumulative gaps','unavailable primary empty state','all254county search/sort','Harris precinct shortcut and county-only Johnson drilldown','unconfirmed daily zero retains cumulative','desktop/tablet/mobile no overflow']}
 (OUT/'tracking-verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));browser.close()
