"""Real downloads, rendered image content, panel persistence, and responsive layout."""
from pathlib import Path
from collections import Counter
import json,os,subprocess
from PIL import Image
from playwright.sync_api import sync_playwright,expect
BASE=os.environ.get('TURNOUT_TEST_URL','http://127.0.0.1:8741')
OUT=Path(__file__).resolve().parents[2]/'analysis/social-images/qa';OUT.mkdir(parents=True,exist_ok=True)
images=[];filenames=[]
def inspect_png(path):
 with Image.open(path) as image:
  assert image.format=='PNG' and image.size==(1600,1000),(path,image.format,image.size)
  assert image.convert('RGBA').getpixel((0,0))[3]==255
  colors=Counter(image.convert('RGB').get_flattened_data())
  assert sum(n for color,n in colors.items() if max(color)-min(color)>35)>100,(path,'missing colored data')
  return colors
def ocr(path):
 result=subprocess.run(['tesseract',str(path),'stdout'],capture_output=True,text=True,check=True)
 return ' '.join(result.stdout.split()).lower()
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium');page=browser.new_page(viewport={'width':1512,'height':1080},reduced_motion='reduce');errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
 page.goto(BASE,wait_until='networkidle');page.wait_for_function('Tracking.view&&Tracking.state&&Atlas.layer&&window.Visuals')
 def navigate(key):
  if key in ['county-table','county-trend']:page.locator('#counties-tab').click()
  else:
   page.locator('#precincts-tab').click();page.locator('#precinct-trends-tab' if key.startswith('daily') or key=='matrix' else '#precinct-explore-tab').click()
   if key.startswith('daily') or key=='matrix':page.locator('#county').select_option('all')
   elif page.locator('#county').input_value()=='all':
    page.locator('#county').select_option('travis');page.wait_for_function('Atlas.county==="travis"&&Atlas.layer&&document.getElementById("map-loading").hidden')
  page.wait_for_timeout(100)
 navigate('daily')
 current_day=page.evaluate('data.days');panels=page.locator('[data-collapsible]');expect(panels).to_have_count(9)
 # Collapse works by keyboard and survives both re-render and reload.
 toggle=page.locator('[data-panel="daily-section"]');toggle.focus();toggle.press('Enter');expect(toggle).to_have_attribute('aria-expanded','false');expect(page.locator('#daily-section-body')).to_be_hidden()
 page.locator('#cohort').select_option('unchanged');page.wait_for_function('Tracking.view?.cohort==="unchanged"');expect(page.locator('#daily-section-body')).to_be_hidden()
 page.reload(wait_until='networkidle');page.wait_for_function('Tracking.view&&Atlas.layer');expect(page.locator('#daily-section-body')).to_be_hidden()
 page.locator('[data-panels="expand"]').click();expect(page.locator('#daily-section-body')).to_be_visible()
 navigate('map')
 # Map camera is preserved across both individual and bulk folds.
 camera=page.evaluate('()=>{Atlas.map.setView([30.32,-97.75],11,{animate:false});return {lat:Atlas.map.getCenter().lat,lng:Atlas.map.getCenter().lng,zoom:Atlas.map.getZoom()}}')
 for individual in [True,False]:
  page.locator('[data-panel="map-panel"]' if individual else '[data-panels="collapse"]').click();expect(page.locator('#map-panel-body')).to_be_hidden()
  if not individual:
   assert page.locator('#precinct-explore [data-collapsible].is-collapsed').count()==4
   assert page.evaluate('document.documentElement.scrollHeight')<1200
  page.locator('[data-panel="map-panel"]' if individual else '[data-panels="expand"]').click();expect(page.locator('#map-panel-body')).to_be_visible();page.wait_for_timeout(200)
  assert page.evaluate('(v)=>{const a=Atlas.map.project(v,v.zoom),b=Atlas.map.project(Atlas.map.getCenter(),v.zoom);return Math.abs(a.x-b.x)<1&&Math.abs(a.y-b.y)<1&&Atlas.map.getZoom()===v.zoom;}',camera)
 # Every visible visual actually produces a valid PNG download.
 keys=page.locator('[data-image]').evaluate_all('(els)=>els.map(e=>e.dataset.image).filter(k=>!k.startsWith("county-daily")&&k!=="county-summary")')
 assert len(keys)==len(set(keys)) and len(keys)==17,keys
 for key in keys:
  navigate(key)
  with page.expect_download(timeout=45000) as download:page.locator(f'[data-image="{key}"]').click()
  filename=download.value.suggested_filename;assert filename not in filenames,('ambiguous filenames',filename);filenames.append(filename);assert filename.endswith('.png') and f'day-{current_day}' in filename
  path=OUT/f'export-{key}.png';download.value.save_as(str(path));colors=inspect_png(path);images.append(key)
  if key in ['demographics','profile']:
   for color in [(19,123,138),(124,91,180),(65,109,155),(210,138,57),(38,140,146)]:assert colors[color]>30,(key,color,'clipped resident bar')
  if key in ['county-table','precinct-table']:assert colors[(34,102,167)]>50,(key,'missing table body')
 assert 'asian' in ocr(OUT/'export-demographics.png')
 county_text=ocr(OUT/'export-county-table.png');assert all(name in county_text for name in ['harris','dallas','montgomery']),county_text
 assert 'unweighted ols' in ocr(OUT/'export-regression.png')
 navigate('map')
 # Exact captured viewport, vector paths, and SVG clipping are retained.
 assert page.evaluate('''async()=>{const d=Visuals.descriptor('map'),c=await Visuals.capture(d);const xml=decodeURIComponent(c.img.src.split(',').slice(1).join(','));return xml.includes('matrix(')&&xml.includes('leaflet-interactive')&&!xml.includes('leaflet-control-zoom');}''')
 assert page.evaluate('''async()=>{const c=await Visuals.capture(Visuals.descriptor('regression'));const xml=decodeURIComponent(c.img.src.split(',').slice(1).join(','));return xml.includes('url(#regression-clip)')&&!xml.includes('url(&quot;http');}''')
 navigate('daily')
 # A filter change while PNG encoding runs cannot relabel the captured data.
 page.evaluate('''()=>{window.realCapture=Visuals.capture;window.imageGate=new Promise(resolve=>window.releaseImage=resolve);window.captureReady=false;Visuals.capture=async function(d){const result=await realCapture.call(this,d);window.captureReady=true;await imageGate;return result;};}''')
 with page.expect_download(timeout=45000) as download:
  page.locator('[data-image="daily-0"]').click();page.wait_for_function('window.captureReady');page.get_by_role('button',name='Day 1',exact=True).click();page.evaluate('window.releaseImage()')
 assert f'day-{current_day}' in download.value.suggested_filename
 path=OUT/'export-frozen-context.png';download.value.save_as(str(path));assert f'day {current_day}' in ocr(path)
 page.evaluate('()=>{Visuals.capture=window.realCapture;}');page.get_by_role('button',name=f'Day {current_day}',exact=True).click()
 # Dynamic charts retain one action each and exports follow the chosen view.
 for view in ['primary','demographic','partisan']:
  page.locator(f'#{view}-mode').click();page.wait_for_function('(v)=>mode===v&&(v==="partisan"||demoReady())&&Tracking.view?.metric===(v==="partisan"?"partisan":activeMetricId())',arg=view)
  expect(page.locator('.daily-panel [data-image]')).to_have_count(6)
 page.locator('#demographic-mode').click();page.locator('#metric').select_option('non_white_vap');page.wait_for_function('demoReady()&&Tracking.view?.metric==="non_white_vap"')
 page.locator('#tracking-measure').select_option('cumulative')
 with page.expect_download() as download:page.locator('[data-image="daily-0"]').click()
 path=OUT/'export-non-white-cumulative.png';download.value.save_as(str(path));text=ocr(path);assert 'cumulative turnout' in text and 'non-white' in text and '2020 census' in text,text
 navigate('map')
 # Map turnout exports describe turnout rather than population composition.
 page.locator('#map-layer').select_option('turnout')
 with page.expect_download(timeout=45000) as download:page.locator('[data-image="map"]').click()
 path=OUT/'export-demographic-turnout-map.png';download.value.save_as(str(path));text=ocr(path);assert 'comparison-group turnout' in text and 'resident composition' not in text,text
 page.locator('#map-layer').select_option('share')
 navigate('county-table')
 # Filtered and sorted table content is the content that gets shared.
 page.locator('#statewide-search').fill('Nueces');page.locator('[data-state-county="nueces"]').click()
 with page.expect_download() as download:page.locator('[data-image="county-table"]').click()
 path=OUT/'export-filtered-table.png';download.value.save_as(str(path));text=ocr(path);assert 'nueces' in text and 'dallas' not in text and 'montgomery' not in text,text;assert page.locator('#statewide-table tbody [data-state-county]').all_text_contents()==['Nueces']
 navigate('daily')
 # Layout and mobile export stay usable; full bucket columns aren't lost to scrolling.
 page.locator('#tracking-measure').select_option('daily')
 for width in [1512,768,390]:
  page.set_viewport_size({'width':width,'height':1000});page.wait_for_timeout(250);page.evaluate('window.scrollTo(0,0)')
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
  page.screenshot(path=str(OUT/f'panels-{width}.png'))
 with page.expect_download(timeout=45000) as download:page.locator('[data-image="matrix"]').click()
 path=OUT/'export-mobile-matrix.png';download.value.save_as(str(path));assert 'madison' in ocr(path),'last matrix column missing'
 with page.expect_download(timeout=45000) as download:page.locator('[data-image="daily"]').click()
 path=OUT/'export-mobile-overview.png';download.value.save_as(str(path));inspect_png(path)
 assert page.evaluate('''async()=>{const c=await Visuals.capture(Visuals.descriptor('daily'));return c.width===1320&&c.height<650;}'''),'mobile overview retained empty grid rows'
 with Image.open(path) as image:
  body=image.convert('RGB');ink_x=[x for x in range(96,1504,8) if any(max(body.getpixel((x,y)))-min(body.getpixel((x,y)))>20 for y in range(250,850,4))];assert min(ink_x)<200 and max(ink_x)>1400,'mobile overview too small'
 page.locator('[data-panels="collapse"]').click();assert page.locator('#precinct-trends [data-collapsible].is-collapsed').count()==2
 page.screenshot(path=str(OUT/'panels-collapsed-mobile.png'));page.locator('[data-panels="expand"]').click()
 # Storage restrictions must not disable the controls.
 private=browser.new_page();private.on('pageerror',lambda error:errors.append(str(error)));private.add_init_script("Object.defineProperty(window,'localStorage',{get(){throw new Error('Storage blocked')}})");private.goto(BASE,wait_until='networkidle');private.wait_for_function('window.Visuals&&Tracking.view');private.locator('[data-panels="collapse"]').click();assert private.locator('[data-collapsible].is-collapsed').count()==3;private.locator('[data-panels="expand"]').click();assert private.locator('[data-collapsible].is-collapsed').count()==0;private.close()
 assert not errors,errors
 report={'status':'passed','png_size':[1600,1000],'visual_downloads':images,'javascript_errors':errors,'checks':['nine keyboard-accessible panel folds across workspaces','map camera retained across individual/bulk collapse','all 17 visual downloads','PNG header/dimensions/opaque background/data pixels','all five Census bars visible','table body and last row visible','SVG map transforms and clipping retained','dynamic view changes retain actions','current demographic/measure and source in image','filtered county table','full matrix columns on mobile','export context frozen across filter changes','controls work with blocked storage','desktop/tablet/mobile no overflow']}
 (OUT/'visuals-verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));browser.close()
