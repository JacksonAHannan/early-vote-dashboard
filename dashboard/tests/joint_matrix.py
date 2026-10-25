#!/usr/bin/env python3
"""Independent demographic/partisan intersections and browser/export acceptance.

TURNOUT_TEST_URL=http://127.0.0.1:8743 uv run --with playwright --with pillow python dashboard/tests/joint_matrix.py
Set TURNOUT_JOINT_STATIC=1 for a generated/hosted Pages site.
"""
import bisect,csv,gzip,hashlib,io,json,math,os,traceback
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode,urlsplit,parse_qsl
from urllib.request import urlopen
from PIL import Image
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[2]
BASE=os.environ.get('TURNOUT_TEST_URL','http://127.0.0.1:8743').rstrip('/')+'/'
STATIC=os.environ.get('TURNOUT_JOINT_STATIC')=='1'
TAG=os.environ.get('TURNOUT_TEST_TAG','local')
OUT=ROOT/'analysis/joint-matrix'/TAG;OUT.mkdir(parents=True,exist_ok=True)
REPORT={'url':BASE,'static':STATIC,'checks':[],'assertions':0,'api_cases':0,'javascript_errors':[]}
LABELS=['Harris 30+','Harris 15–30','Harris 0–15','Trump 0–15','Trump 15–30','Trump 30+','Tied / unknown']
def check(condition,detail):
 REPORT['assertions']+=1
 assert condition,detail
def read(path):
 with urlopen(BASE+path,timeout=120) as r:return r.read()
@lru_cache(maxsize=1)
def manifest():
 raw=read('api-manifest.json');publication=json.loads(read('publication.json'))
 check(hashlib.sha256(raw).hexdigest()==publication['revision'],'manifest hash')
 return json.loads(raw)
def api(path):
 if STATIC:
  parsed=urlsplit(path);query=urlencode(sorted(parse_qsl(parsed.query)));key=parsed.path+('?' + query if query else '')
  file=manifest()['routes'][key];raw=read(file);raw=gzip.decompress(raw) if raw[:2]==b'\x1f\x8b' else raw
  check(hashlib.sha256(raw).hexdigest()==Path(file).name.split('.')[0],file)
  return json.loads(raw)
 return json.loads(read(path.lstrip('/')))
@lru_cache(maxsize=1)
def presidential_references():
 return {r['id']:r['presidential'] for r in api('/api/reference')}
def matrix_column(county,group):
 # Independently sum raw reference members, rather than trusting the snapshot's
 # homogeneous-member bucket or its derived combined presidential totals.
 returns=presidential_references()[county]
 if any(p not in returns for p in group['old']):return 6
 h=sum(returns[p]['harris'] for p in group['old']);t=sum(returns[p]['trump'] for p in group['old'])
 if h==t:return 6
 share=h/(h+t)
 return 0 if share>=.65 else 1 if share>=.575 else 2 if share>.5 else 3 if share>.425 else 4 if share>.35 else 5
def oracle(snapshot,demographics,metric,day,cohort,homogeneous=False):
 result={};cuts=[v for v in metric['cuts'] if 0<v<100]
 for c in snapshot['counties']:
  cells=[[[0,0,0] for j in LABELS] for i in range(len(cuts)+1)]
  periods=[p for p in c['periods'] if p['day']==day]
  for g in periods[0]['groups'] if periods else []:
   if not g.get('available',True) or cohort=='unchanged' and not g['unchanged']:continue
   precincts=demographics['counties'].get(c['id'],{}).get('precincts',{})
   counts=[precincts.get(member,{}).get('counts',{}) for member in g['new']]
   values=[(p.get(metric['numerator']),p.get(metric['denominator'])) for p in counts]
   if not values or any(n is None or d is None or not math.isfinite(n) or not math.isfinite(d) or not 0<=n<=d for n,d in values):continue
   n=sum(v[0] for v in values);d=sum(v[1] for v in values)
   if not d:continue
   i=bisect.bisect_right(cuts,n/d*100);j=(g['bucket'] if g['bucket'] is not None else 6) if homogeneous else matrix_column(c['id'],g)
   for k,v in enumerate((1,g['votes_2024'],g['votes_2026'])):cells[i][j][k]+=v
  result[c['id']]=cells
 result['all']=[[[sum(cells[i][j][k] for cells in result.values()) for k in range(3)] for j in range(7)] for i in range(len(cuts)+1)]
 return result
def assert_cohort(actual,counts,label):
 check([actual[k] for k in ['groups','votes_2024','votes_2026']]==counts,label)
 ratio=counts[2]/counts[1] if counts[1] else None
 check(actual['ratio'] is None if ratio is None else actual['ratio'] is not None and math.isclose(actual['ratio'],ratio,abs_tol=1e-12),('ratio',label))
def api_acceptance():
 snapshot=api('/api/data');census=api('/api/demographics')
 cases=[(m,snapshot['days'],cohort,'demographic',census) for m in census['metrics'] for cohort in ['matched','unchanged']]
 hispanic=next(m for m in census['metrics'] if m['id']=='hispanic_vap')
 cases.extend((hispanic,1,cohort,'demographic',census) for cohort in ['matched','unchanged'])
 primary=api('/api/primary');cases.append((primary['metrics'][0],min(3,snapshot['days']),'matched','primary',primary))
 for metric,day,cohort,view,data in cases:
  expected=oracle(snapshot,data,metric,day,cohort)
  payload=api('/api/demographic-view?'+urlencode({'day':day,'cohort':cohort,'metric':metric['id'],'view':view}))
  check(payload['generated_at']==snapshot['generated_at'],'source generation')
  check(set(payload['views'])==set(expected),'county membership')
  for county,cells in expected.items():
   v=payload['views'][county];matrix=v['partisan_matrix']
   check(matrix['columns']==LABELS,(county,'column labels'))
   check(len(matrix['cells'])==len(cells),(county,'row count'))
   for i,row in enumerate(cells):
    for j,counts in enumerate(row):assert_cohort(matrix['cells'][i][j],counts,(county,i,j))
    assert_cohort(v['bins'][i],[sum(c[k] for c in row) for k in range(3)],(county,i,'row margin'))
   for j in range(7):assert_cohort(matrix['totals'][j],[sum(row[j][k] for row in cells) for k in range(3)],(county,j,'column margin'))
   assert_cohort(v['coverage']['included'],[sum(cell[k] for row in cells for cell in row) for k in range(3)],(county,'grand total'))
  before=oracle(snapshot,data,metric,day,cohort,homogeneous=True)['all'];after=expected['all']
  for oldrow,newrow in zip(before,after):
   for j in range(6):check(all(newrow[j][k]>=oldrow[j][k] for k in range(3)),('previously classified votes retained',metric['id'],j))
   check([sum(c[k] for c in oldrow) for k in range(3)]==[sum(c[k] for c in newrow) for k in range(3)],'classification preserves demographic row totals')
  if cohort=='unchanged':check(before==after,'strict unchanged matrix remains identical')
  REPORT.setdefault('classification_impact',[]).append({'metric':metric['id'],'day':day,'cohort':cohort,
   'groups':sum(c[0] for row in after for c in row),
   'unknown_before':sum(row[6][0] for row in before),'unknown_after':sum(row[6][0] for row in after),
   'newly_classified_2024_votes':sum(old[6][1]-new[6][1] for old,new in zip(before,after))})
  REPORT['api_cases']+=1;print(f"API {view}/{metric['id']}/{cohort}/day{day} passed",flush=True)
 REPORT['checks'].append('Independent Census member-count sums, group eligibility, partisan membership and all joint cells/marginals match across counties, metrics, days and cohorts')
def browser_cells(page):
 actual=page.evaluate('()=>{const v=jointViews[county],rows=[...document.querySelectorAll("#matrix tbody tr")];return {bins:v.bins,matrix:v.partisan_matrix,total:v.coverage.included,rows:rows.map(row=>[...row.querySelectorAll("td")].map(c=>({text:c.textContent,title:c.title}))),footer:[...document.querySelectorAll("#matrix tfoot td")].map(c=>({text:c.textContent,title:c.title}))};}')
 def compare(cell,value):
  if value['ratio'] is None:check(cell['text']=='—',cell)
  else:check(math.isclose(float(cell['text'].rstrip('†%')),100*value['ratio'],abs_tol=.050001),cell)
  check(f"{value['votes_2026']:,} / {value['votes_2024']:,} votes; {value['groups']:,} groups" in cell['title'],cell)
 for i,row in enumerate(actual['rows']):
  for cell,value in zip(row,[actual['bins'][i],*actual['matrix']['cells'][i]]):compare(cell,value)
 for cell,value in zip(actual['footer'],[actual['total'],*actual['matrix']['totals']]):compare(cell,value)
 return actual

def browser_acceptance():
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
  page=browser.new_page(viewport={'width':1512,'height':1100},accept_downloads=True,reduced_motion='reduce')
  page.on('pageerror',lambda e:REPORT['javascript_errors'].append(str(e)))
  try:
   page.goto(BASE,wait_until='networkidle',timeout=120000);page.wait_for_function('data&&window.Visuals&&Tracking.view',timeout=120000)
   page.locator('#precincts-tab').click();page.locator('#precinct-trends-tab').click()
   page.locator('[data-matrix-layout="joint"]').click()
   page.wait_for_function('jointReady()&&jointViews[county]?.partisan_matrix',timeout=120000)
   expect(page.locator('#matrix-metric')).to_have_value('hispanic_vap');expect(page.locator('#matrix-county-controls')).to_be_hidden()
   check(page.locator('#matrix thead th').count()==9,'all demographic/partisan columns')
   browser_cells(page)
   page.locator('[data-panel="bucket-section"]').click();expect(page.locator('#matrix')).to_be_hidden();page.locator('[data-panel="bucket-section"]').click()
   for metric in page.locator('#matrix-metric option').evaluate_all('(options)=>options.map(o=>o.value)'):
    page.locator('#matrix-metric').select_option(metric);page.wait_for_function('jointReady()',timeout=120000);browser_cells(page)
   for cohort,county,day in [('unchanged','tarrant',1),('matched','harris',3),('matched','all',3)]:
    page.locator('#cohort').select_option(cohort);page.locator('#county').select_option(county);page.get_by_role('button',name=f'Day {day}',exact=True).click()
    page.wait_for_function('jointReady()',timeout=120000);browser_cells(page)
   page.locator('#matrix-metric').select_option('hispanic_vap');page.wait_for_function('jointReady()',timeout=120000)
   expected=browser_cells(page)
   with page.expect_download() as download:page.locator('#download').click()
   raw=download.value.path().read_text();rows=list(csv.DictReader(io.StringIO(raw)));check(len(rows)==35,'CSV has joint cells without duplicate marginals')
   for i,row in enumerate(rows):
    cell=expected['matrix']['cells'][i//7][i%7]
    check([int(row[k]) for k in ['groups','votes_2024','votes_2026']]==[cell[k] for k in ['groups','votes_2024','votes_2026']],row)
    check(row['demographic_bucket']==expected['bins'][i//7]['label'] and row['partisan_bucket']==LABELS[i%7],row)
   REPORT['checks'].append('Actual browser cells, tooltips, marginals and CSV follow every Census metric, county, day and cohort; collapse and classification controls remain independent')
   # Delayed response must not replace a more recent metric selection.
   page.evaluate('()=>{window.__jointFetch=window.fetch;window.__jointHeld=null;window.fetch=(input,init)=>{const u=new URL(typeof input==="string"?input:input.url,location.href);if(u.pathname.endsWith("/api/demographic-view")&&u.searchParams.get("metric")==="under18"&&u.searchParams.get("view")==="demographic")return new Promise(resolve=>window.__jointHeld=()=>window.__jointFetch(input,init).then(resolve));return window.__jointFetch(input,init);};}')
   page.locator('#matrix-metric').select_option('under18');page.wait_for_function('Boolean(window.__jointHeld)')
   expect(page.locator('[data-image="matrix"]')).to_be_disabled();expect(page.locator('#download')).to_have_attribute('aria-disabled','true')
   page.locator('#matrix-metric').select_option('non_white_vap');page.wait_for_function('jointReady()',timeout=120000)
   page.evaluate('async()=>{await window.__jointHeld();window.fetch=window.__jointFetch;}');page.wait_for_function('classificationPending.size===0')
   check(page.evaluate('jointMetricId==="non_white_vap"&&jointViews.all.metric.id==="non_white_vap"'),'late response rejected');browser_cells(page)
   # Both views can share a single in-flight canonical classification request.
   page.evaluate('()=>{window.__jointRequests=0;window.__jointFetch=window.fetch;window.fetch=(input,init)=>{const u=new URL(typeof input==="string"?input:input.url,location.href);if(u.pathname.endsWith("/api/demographic-view")&&u.searchParams.get("metric")==="non_white_vap"&&u.searchParams.get("view")==="demographic")window.__jointRequests++;return window.__jointFetch(input,init);};mode="demographic";metricId="non_white_vap";document.getElementById("metric").value=metricId;invalidateComparisonViews();ensureDemo();renderMatrix();}')
   page.wait_for_function('demoReady()&&jointReady()',timeout=120000)
   check(page.evaluate('window.__jointRequests')==1,'shared canonical request');page.evaluate('()=>{window.fetch=window.__jointFetch;}')
   # Same-generation invalidation must re-render changed cells.
   change=page.evaluate('()=>{const v=structuredClone(jointViews.all),m=v.partisan_matrix;let ri=0,cj=0;outer:for(let i=0;i<m.cells.length;i++)for(let j=0;j<m.cells[i].length;j++)if(m.cells[i][j].votes_2024>0){ri=i;cj=j;break outer;}for(const c of [m.cells[ri][cj],m.totals[cj],v.bins[ri],v.coverage.included]){c.votes_2026+=101;c.ratio=c.votes_2026/c.votes_2024;}window.__jointFixture={generated_at:data.generated_at,views:{all:v}};window.__jointFetch=window.fetch;window.fetch=(input,init)=>{const u=new URL(typeof input==="string"?input:input.url,location.href);return u.pathname.endsWith("/api/demographic-view")?Promise.resolve(new Response(JSON.stringify(window.__jointFixture),{headers:{"Content-Type":"application/json"}})):window.__jointFetch(input,init);};const result={row:ri,column:cj,votes:v.partisan_matrix.cells[ri][cj].votes_2026,generation:data.generated_at};invalidateComparisonViews();renderMatrix();return result;}')
   page.wait_for_function('jointReady()',timeout=120000);check(page.evaluate('(c)=>jointViews.all.partisan_matrix.cells[c.row][c.column].votes_2026',change)==change['votes'],'new same-generation values')
   check(str(f"{change['votes']:,}") in page.locator('#matrix tbody tr').nth(change['row']).locator('td').nth(change['column']+1).get_attribute('title'),'changed cell rendered')
   page.evaluate('()=>{window.fetch=window.__jointFetch;invalidateComparisonViews();updateView();}');page.wait_for_function('jointReady()&&demoReady()',timeout=120000)
   REPORT['checks'].append('Loading blocks exports; stale requests cannot overwrite selected metrics; shared requests coalesce; same-generation invalidation replaces joint cells')
   page.locator('#matrix-metric').select_option('hispanic_vap');page.wait_for_function('jointReady()',timeout=120000)
   for width in [1512,768,390]:
    page.set_viewport_size({'width':width,'height':1100});page.locator('#matrix').scroll_into_view_if_needed()
    probe=page.evaluate('()=>{const m=document.getElementById("matrix"),a=m.querySelector("tbody th"),b=m.querySelector("tbody .matrix-total"),x=e=>e.getBoundingClientRect().x;m.scrollLeft=0;const before=[x(a),x(b)];m.scrollLeft=m.scrollWidth;return {before,after:[x(a),x(b)],adjacent:Math.abs(a.getBoundingClientRect().right-b.getBoundingClientRect().left)<1,overflow:document.documentElement.scrollWidth>innerWidth};}')
    check(not probe['overflow'] and probe['adjacent'] and all(abs(a-b)<1 for a,b in zip(probe['before'],probe['after'])),probe)
    page.locator('#matrix').screenshot(path=str(OUT/f'matrix-{width}.png'))
    page.screenshot(path=str(OUT/f'page-{width}.png'),full_page=False)
   focus=page.locator('#matrix tbody td').nth(2);focus.focus();expect(focus).to_be_focused();expect(focus).to_have_attribute('aria-label',focus.get_attribute('title'))
   with page.expect_download(timeout=60000) as download:page.locator('[data-image="matrix"]').click()
   image=OUT/'matrix-export.png';download.value.save_as(str(image))
   with Image.open(image) as img:check(img.size==(1600,1000) and img.format=='PNG','real PNG')
   captured=page.evaluate('async()=>{const desc=Visuals.descriptor("matrix"),c=await Visuals.capture(desc);return {title:desc.title,classification:desc.classification,source:desc.source,xml:decodeURIComponent(c.img.src.split(",").slice(1).join(","))};}')
   check('Hispanic' in captured['classification'] and 'Census' in captured['source'] and all(label in captured['xml'] for label in LABELS),'complete and correctly labeled capture')
   page.locator('[data-matrix-layout="counties"]').click();expect(page.locator('#matrix th.matrix-total')).to_have_text('All Counties');expect(page.locator('#matrix-county-controls')).to_be_visible()
   REPORT['checks'].append('Desktop/tablet/mobile pinned labels and All column, accessible count details, actual complete PNG and switch back to existing county matrix')
   check(not REPORT['javascript_errors'],REPORT['javascript_errors'])
  finally:browser.close()
if __name__=='__main__':
 try:api_acceptance();browser_acceptance();REPORT['passed']=True
 except BaseException:REPORT['passed']=False;REPORT['failure']=traceback.format_exc();raise
 finally:(OUT/'verification.json').write_text(json.dumps(REPORT,indent=2)+'\n');print(json.dumps(REPORT),flush=True)
