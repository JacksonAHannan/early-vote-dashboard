"""Real intermediate camera/reveal frames, cancellation, reduced motion and PNGs.

TURNOUT_TEST_URL=http://127.0.0.1:8744/ uv run --with playwright --with pillow python dashboard/tests/motion.py
Uses retained static artifacts or the actual public website; no collector writes.
"""
import json,os,traceback
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright,expect
BASE=os.environ.get('TURNOUT_TEST_URL','http://127.0.0.1:8744/').rstrip('/')+'/'
OUT=Path(__file__).resolve().parents[2]/'analysis/motion'/os.environ.get('TURNOUT_TEST_TAG','local');OUT.mkdir(parents=True,exist_ok=True)
REPORT={'url':BASE,'checks':[],'javascript_errors':[]}
def run():
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
  page=browser.new_page(viewport={'width':1512,'height':1100},accept_downloads=True,reduced_motion='no-preference')
  page.on('pageerror',lambda e:REPORT['javascript_errors'].append(e.stack))
  def settle():page.wait_for_function('Motion.flights.size===0&&Motion.effects.size===0',timeout=20000)
  def record(map):
   page.evaluate('m=>{window.cameraFrames=[];window.cameraEnds=0;const map=m==="Atlas"?Atlas.map:States.map;map.on("move",()=>cameraFrames.push({z:map.getZoom(),lat:map.getCenter().lat,lng:map.getCenter().lng,t:performance.now()}));map.on("moveend",()=>cameraEnds++);}',map)
  def travel(label):
   page.wait_for_function('cameraEnds>0&&cameraFrames.length>3',timeout=10000);settle()
   frames=page.evaluate('cameraFrames');assert len({round(f['z'],3) for f in frames})>3,(label,frames)
   assert frames[-1]['t']-frames[0]['t']>200,(label,'instant camera jump')
   print('Accepted flight:',label,flush=True)
   REPORT['checks'].append({'flight':label,'frames':len(frames),'duration_ms':round(frames[-1]['t']-frames[0]['t'])})
  try:
   page.goto(BASE,wait_until='networkidle',timeout=120000);page.wait_for_function('data&&Atlas.layer',timeout=120000)
   page.get_by_role('button',name='Day 3',exact=True).click()
   # Record actual browser animations, including short effects that finish before
   # Playwright's click returns on a busy machine. Keep the browser API intact.
   page.evaluate('''()=>{window.animationRecords=[];const animate=Element.prototype.animate;Element.prototype.animate=function(...args){const effect=animate.apply(this,args);animationRecords.push({target:this.id,frames:effect.effect.getKeyframes(),duration:effect.effect.getTiming().duration});return effect;};}''')
   page.locator('#precincts-tab').click();page.locator('#precinct-explore-tab').click()
   section=page.evaluate('animationRecords.filter(r=>r.target==="precinct-explore")');assert section and section[-1]['duration']>0 and section[-1]['frames'][0]['opacity']!=section[-1]['frames'][-1]['opacity'];settle()
   record('Atlas');page.locator('#map-county').select_option('tarrant');page.wait_for_function('Atlas.county==="tarrant"&&document.getElementById("map-loading").hidden&&cameraFrames.length>3',timeout=120000)
   page.screenshot(path=str(OUT/'county-midflight.png'));travel('Texas to Tarrant')
   assert page.evaluate('Atlas.map.getBounds().contains(Atlas.layer.getBounds())')
   page.screenshot(path=str(OUT/'county-settled.png'))
   page.evaluate('cameraFrames=[];cameraEnds=0')
   dot=page.locator('.regression-point[data-county="tarrant"][aria-hidden="false"]').first
   dot.focus();dot.press('Enter');travel('Regression point to precinct')
   assert page.evaluate('Atlas.active?.county==="tarrant"')
   page.screenshot(path=str(OUT/'precinct-settled.png'))
   page.evaluate('cameraFrames=[];cameraEnds=0');page.locator('#map-reset').click();travel('County to Texas')
   page.locator('#map-county').select_option('tarrant');page.wait_for_timeout(100);page.locator('#map-county').select_option('travis');page.wait_for_function('Atlas.county==="travis"&&document.getElementById("map-loading").hidden',timeout=120000);settle()
   assert page.evaluate('Atlas.map.getBounds().contains(Atlas.layer.getBounds())')
   assert page.evaluate('Object.values(Atlas.map._layers).filter(l=>l instanceof L.GeoJSON).length')==1,'retired geometry leaked'
   REPORT['checks'].append('Rapid county selections finish at the last county with one geometry layer')
   page.locator('#precinct-trends-tab').click();page.wait_for_function('Tracking.view&&Tracking.key===Tracking.signature()',timeout=120000);settle()
   page.locator('#tracking-measure').select_option('cumulative');assert page.evaluate('animationRecords.some(r=>r.target==="daily-charts"&&r.duration>0&&r.frames[0].opacity!==r.frames.at(-1).opacity)')
   with page.expect_download(timeout=60000) as dl:page.locator('[data-image="daily-0"]').click()
   dl.value.save_as(str(OUT/'timeline.png'));assert page.evaluate('Motion.effects.size')==0
   with Image.open(OUT/'timeline.png') as im:assert im.size==(1600,1000)
   page.locator('#precinct-explore-tab').click();settle();page.locator('#map-county').select_option('tarrant');page.wait_for_function('Atlas.county==="tarrant"&&document.getElementById("map-loading").hidden',timeout=120000)
   with page.expect_download(timeout=60000) as dl:page.locator('[data-image="map"]').click()
   dl.value.save_as(str(OUT/'map.png'));assert page.evaluate('Motion.flights.size')==0
   page.wait_for_timeout(350);assert page.evaluate('Atlas.map.getBounds().contains(Atlas.layer.getBounds())')
   REPORT['checks'].append('Timeline changes animate; PNGs settle chart styles and final camera geometry')
   page.locator('#map-county').select_option('travis');page.wait_for_function('Atlas.county==="travis"&&document.getElementById("map-loading").hidden',timeout=120000)
   page.locator('[data-panels="collapse"]').click();page.locator('[data-panels="expand"]').click();settle()
   assert page.evaluate('Atlas.map.getBounds().contains(Atlas.layer.getBounds())')
   REPORT['checks'].append('Bulk collapse during a flight preserves the final county camera on expansion')
   # A state map below the headline animates on arrival in the viewport.
   page.locator('#state-select').select_option('ga');page.wait_for_function('States.view&&States.layer?.state==="ga"&&!States.busy',timeout=120000)
   record('States');page.locator('#state-map').scroll_into_view_if_needed();travel('Georgia entry')
   page.screenshot(path=str(OUT/'georgia-map.png'))
   county=page.evaluate('States.view.counties.find(c=>c.selected?.cumulative_2024>0&&c.fips).id')
   page.evaluate('cameraFrames=[];cameraEnds=0')
   page.locator(f'#state-body-table tr[data-state-county="{county}"]').first.click();page.locator('#state-map').scroll_into_view_if_needed();travel('State results to county')
   assert page.evaluate('States.county')==county
   page.locator('#state-select').select_option('nc');page.wait_for_function('States.view&&States.layer?.state==="nc"&&!States.busy',timeout=120000)
   page.evaluate('cameraFrames=[];cameraEnds=0');page.locator('#state-map').scroll_into_view_if_needed();travel('Georgia to North Carolina')
   page.set_viewport_size({'width':390,'height':844});settle();page.locator('#state-map').scroll_into_view_if_needed();page.wait_for_timeout(850);settle();page.screenshot(path=str(OUT/'mobile.png'));assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
   # Preference changes settle in-flight motion and disable further transitions.
   page.set_viewport_size({'width':1512,'height':1100});page.locator('#state-select').select_option('tx');page.locator('#precinct-explore-tab').click();settle()
   page.locator('#map-reset').click();page.wait_for_function('Atlas.county==="all"&&document.getElementById("map-loading").hidden');page.emulate_media(reduced_motion='reduce');settle();assert page.evaluate('Motion.entries.size')==0
   record('Atlas');page.locator('#map-county').select_option('travis');page.wait_for_function('Atlas.county==="travis"&&document.getElementById("map-loading").hidden',timeout=120000)
   assert page.evaluate('Motion.flights.size===0&&Motion.effects.size===0');assert page.evaluate('Atlas.map.getBounds().contains(Atlas.layer.getBounds())')
   assert len(page.evaluate('cameraFrames'))<=2,'reduced motion camera animated'
   page.locator('#precinct-trends-tab').click();page.locator('#tracking-measure').select_option('daily');assert page.evaluate('Motion.effects.size')==0
   REPORT['checks'].append('Mobile has no overflow; changing reduced-motion preference settles flights and disables reveals/camera tweening')
   assert not REPORT['javascript_errors'],REPORT['javascript_errors'];REPORT['passed']=True
  except BaseException:
   page.screenshot(path=str(OUT/'failure.png'),full_page=True);raise
  finally:browser.close()
if __name__=='__main__':
 try:run()
 except BaseException:REPORT.update(passed=False,failure=traceback.format_exc());raise
 finally:(OUT/'verification.json').write_text(json.dumps(REPORT,indent=2)+'\n');print(json.dumps(REPORT),flush=True)
