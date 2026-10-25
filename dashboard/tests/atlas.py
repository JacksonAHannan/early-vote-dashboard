"""Linked atlas browser acceptance; backend formulas audited separately."""
from pathlib import Path
from collections import Counter
import json,os,csv,math
from playwright.sync_api import sync_playwright,expect
BASE=os.environ.get('TURNOUT_TEST_URL','http://127.0.0.1:8741')
OUT=Path(__file__).resolve().parents[2]/'analysis/updated-through-2026-10-22/qa'
OUT.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
 b=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
 page=b.new_page(viewport={'width':1512,'height':1100},reduced_motion='reduce');errors=[]
 page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto(BASE,wait_until='networkidle')
 def precinct_view(section):
  if page.locator('#precinct-workspace').is_hidden():page.locator('#precincts-tab').click()
  page.locator(f'#precinct-{section}-tab').click()
  expect(page.locator(f'#precinct-{section}')).to_be_visible()
 expect(page.locator('#county-workspace')).to_be_visible()
 precinct_view('explore')
 snapshot=page.request.get(BASE+'/api/data').json();census=page.request.get(BASE+'/api/demographics').json()
 counts={c['id']:len(census['counties'][c['id']]['precincts']) for c in snapshot['counties']}
 records={c['id']:c for c in snapshot['counties']}
 page.wait_for_function('(n)=>Atlas.layer && Atlas.layers.size===n',arg=254)
 assert set(page.locator('#map-county option').evaluate_all('(options)=>options.map(o=>o.value)'))==set(counts)|{'all'}
 for county,n in counts.items():
  page.locator('#map-county').select_option(county)
  page.wait_for_function('(v)=>Atlas.county===v[0]&&Atlas.layers.size===v[1]',arg=[county,n])
  expect(page.locator('#county-map path[data-precinct]')).to_have_count(n)
  assert page.locator('#county').input_value()==county
  assert page.locator('.regression-point').evaluate_all('(els,id)=>els.every(e=>e.dataset.county===id)',county)
  assert page.evaluate('Atlas.map.getBounds().contains(Atlas.layer.getBounds())')
 page.locator('#map-county').select_option('all');page.wait_for_function('Atlas.county==="all"&&Atlas.layers.size===254')
 # Cross-county point selection, with all member geometries selected and visible.
 travis=next(c for c in snapshot['counties'] if c['id']=='travis')['periods'][-1]
 index=next(i for i,g in enumerate(travis['groups']) if g['bucket'] is not None and len(g['new'])>1 and g['votes_2024']>0)
 group=travis['groups'][index]
 dot=page.locator(f'.regression-point[data-id="travis:{index}"]');dot.focus();dot.press('Enter')
 page.wait_for_function('(v)=>Atlas.county==="travis"&&Atlas.active?.group_index===v[0]&&Atlas.layers.size===v[1]',arg=[index,counts['travis']])
 expect(page.locator('#selection-panel')).to_have_attribute('data-group',str(index))
 assert page.evaluate('(i)=>[...Atlas.layers.values()].filter(l=>l.feature.properties.group===i).every(l=>Atlas.map.getBounds().contains(l.getBounds())&&l.options.color==="#713bc2")',index)
 assert page.evaluate('document.querySelector(".active-point").parentNode.lastElementChild.classList.contains("active-point")')
 expected=sum(census['counties']['travis']['precincts'][x]['counts']['population'] for x in group['new'])
 assert f'{expected:,}' in page.locator('#selection-stats').inner_text()
 # Native map click exposes native counts, retaining group labels for shared history.
 native=group['new'][0]
 page.evaluate('(id)=>Atlas.layers.get(id).fire("click")',native)
 expect(page.locator('#selection-title')).to_have_text('Precinct '+native)
 expect(page.locator('#selection-stats')).to_contain_text('Group vs. 2024')
 expected=census['counties']['travis']['precincts'][native]['counts']['population']
 assert f'{expected:,}' in page.locator('#selection-stats').inner_text()
 # Hover links in both directions without replacing the selected group.
 page.evaluate('(id)=>Atlas.layers.get(id).fire("mouseover")',native)
 expect(page.locator(f'.regression-point[data-id="travis:{index}"]')).to_have_class('regression-point active-point linked-hover')
 page.evaluate('(id)=>Atlas.layers.get(id).fire("mouseout")',native)
 page.locator('#map-reset').click();assert page.evaluate('Atlas.active===null')
 page.locator('#county').select_option('travis')
 fit=page.locator('.regression-fit').get_attribute('data-slope')
 precinct_view('trends')
 page.locator('#matrix [data-cell="travis:0"]').click()
 precinct_view('explore')
 assert page.locator('.regression-fit').get_attribute('data-slope')==fit
 assert page.locator('.regression-point[fill-opacity="0.16"]').count()>0
 assert page.evaluate('[...Atlas.layers.values()].some(l=>l.options.fillOpacity===.2)')
 page.locator('#clear-filter').click()
 page.locator('#county').select_option('all')
 page.screenshot(path=str(OUT/'atlas-desktop.png'),full_page=True)
 # All Census modes, stable selections, metric CSV, and race-safe controls.
 page.locator('#demographic-mode').click()
 page.wait_for_function('document.querySelectorAll("#matrix tbody tr").length===5')
 for metric in census['metrics']:
  page.locator('#metric').select_option(metric['id'])
  page.wait_for_function('(id)=>demoReady()&&metricId===id',arg=metric['id'])
  assert page.locator('.regression-point').count()>0
  expect(page.locator('#bucket-title')).to_contain_text(metric['label'])
  expect(page.locator('#regression-chart svg')).to_have_attribute('data-scale','auto')
  assert page.locator('#regression-chart svg').evaluate('el=>Number(el.dataset.yMax)>Number(el.dataset.yMin)')
  expect(page.locator('.regression-quadrant')).to_have_count(0)
  expect(page.locator('.partisan-key')).to_be_visible()
  dots=page.locator('.regression-point').evaluate_all('(els)=>els.map(e=>({county:e.dataset.county,group:+e.dataset.group,share:e.dataset.harrisShare,party:e.dataset.party,color:e.getAttribute("fill")}))')
  for dot in dots:
   record=records[dot['county']]
   g=next(p for p in record['periods'] if p['day']==snapshot['days'])['groups'][dot['group']]
   party='unknown' if g['harris']+g['trump']==0 else 'harris' if g['harris']>g['trump'] else 'trump' if g['harris']<g['trump'] else 'tie'
   expected_color={'harris':'#285b91','trump':'#a84236','tie':'#77818e','unknown':'#77818e'}[party]
   assert dot['party']==party and dot['color']==expected_color,(metric['id'],dot,party)
   if party!='unknown':assert math.isclose(float(dot['share']),100*g['harris']/(g['harris']+g['trump']))
  assert {'harris','trump'}.issubset({dot['party'] for dot in dots})
 page.locator('#metric').select_option('non_white_vap')
 page.wait_for_function('demoReady()&&metricId==="non_white_vap"')
 precinct_view('trends')
 with page.expect_download() as download:page.locator('#download').click()
 path=OUT/'demographic-buckets.csv';download.value.save_as(str(path))
 with path.open() as f:rows=list(csv.DictReader(f))
 eligible={c['name'] for c in snapshot['counties'] if any(p['day']==snapshot['days'] for p in c['periods'])}
 bin_count=len(next(m for m in census['metrics'] if m['id']=='non_white_vap')['cuts'])+1
 assert len(rows)==bin_count*len(eligible) and {r['metric'] for r in rows}=={'non_white_vap'}
 assert Counter(r['county'] for r in rows)==Counter({name:bin_count for name in eligible})
 precinct_view('explore')
 profile=page.locator('.demographic-bar').filter(has_text='Total non-white')
 county_counts=census['counties']['travis']['assigned_totals']
 expect(profile).to_contain_text(f"{100*(county_counts['vap']-county_counts['white_nh_vap'])/county_counts['vap']:.1f}%")
 with page.expect_download() as download:page.locator('#regression-download').click()
 point_path=OUT/'non-white-regression.csv';download.value.save_as(str(point_path))
 with point_path.open() as f:point_rows=list(csv.DictReader(f))
 assert point_rows and 'non_white_vap_pct' in point_rows[0] and 'harris_share_2024_pct' in point_rows[0]
 page.locator('#map-layer').select_option('turnout');expect(page.locator('#map-legend')).to_contain_text('150%+')
 page.locator('#map-layer').select_option('share')
 page.screenshot(path=str(OUT/'atlas-demographic.png'),full_page=True)
 page.locator('#county').select_option('ellis');page.get_by_role('button',name='Day 1',exact=True).click()
 page.wait_for_function('demoReady()')
 expect(page.locator('#regression-chart')).to_contain_text('No comparable precinct groups')
 page.evaluate('Atlas.layer.getLayers()[0].fire("click")')
 expect(page.locator('#selection-title')).to_contain_text('Precinct')
 assert page.locator('#selection-stats dd').first.inner_text()=='—'
 page.get_by_role('button',name='Day 4',exact=True).click();page.locator('#county').select_option('all')
 page.locator('#map-county').select_option('travis');page.wait_for_function('(n)=>Atlas.county==="travis"&&Atlas.layers.size===n&&demoReady()',arg=counts['travis'])
 page.locator('#cohort').select_option('unchanged');page.wait_for_function('demoReady()');page.locator('#cohort').select_option('matched');page.wait_for_function('demoReady()')
 for width,height in [(768,1024),(390,844)]:
  page.set_viewport_size({'width':width,'height':height});page.wait_for_timeout(200)
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  assert page.evaluate('Atlas.map.getBounds().contains(Atlas.layer.getBounds())')
  page.screenshot(path=str(OUT/f'atlas-{width}.png'),full_page=True)
 assert not errors,errors
 result={'status':'passed','map_features':sum(counts.values()),'county_maps':len(counts),'metrics':len(census['metrics']),'checks':['cross-county keyboard dot selection','all group polygons fit and highlight','native precinct Census profile','group historical labels','linked hover','bucket map and dot emphasis; stable OLS','demographic CSV','all metrics and cohorts','non-white complements and exports','demographic dots retain presidential party colors','missing Ellis cutoff; Census retained','desktop tablet mobile geometry and overflow','reduced motion'],'javascript_errors':errors}
 (OUT/'atlas-browser-verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));b.close()
