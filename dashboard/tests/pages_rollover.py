#!/usr/bin/env python3
"""A retained Pages manifest must recover once when deployment removes its blobs."""
import copy,gzip,hashlib,json,os,traceback
from pathlib import Path
from urllib.parse import urlparse,urlencode
from urllib.request import urlopen
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[2]
BASE=os.environ.get('TURNOUT_PAGES_URL','http://127.0.0.1:8745/turnout-texas-stress-site-20261025/').rstrip('/')+'/'
TAG=os.environ.get('TURNOUT_TEST_TAG','rollover')
REMOVED_STATUS=int(os.environ.get('TURNOUT_ROLLOVER_STATUS','404'));assert REMOVED_STATUS in (404,410)
USE_SERVED=os.environ.get('TURNOUT_PAGES_USE_SERVED_ADAPTER')=='1'
OUT=ROOT/'analysis/texas-stress';OUT.mkdir(exist_ok=True)
REPORT={'removed_status':REMOVED_STATUS,'served_adapter':USE_SERVED,'checks':[],'javascript_errors':[]}
def read(path):
 with urlopen(BASE+path,timeout=120) as r:return r.read()
def key(**query):return '/api/county-buckets?'+urlencode(sorted(query.items()))
def main():
 active={'publication':json.loads(read('publication.json')),'manifest':json.loads(read('api-manifest.json'))}
 if USE_SERVED:
  assert read('pages-api.js')==(ROOT/'dashboard/static/pages-api.js').read_bytes(),'Served adapter differs from local source'
  REPORT['checks'].append('Actual served adapter bytes match verified source')
 counts={'publication':0,'manifest':0,'removed':0,'replacement':0};blocked=set();fixtures={}
 route=key(day='3',method='mail',metric='black_vap',view='demographic');oldfile=active['manifest']['routes'][route]
 payload=json.loads(gzip.decompress(read(oldfile)));payload['rollover_marker']='current'
 raw=json.dumps(payload,separators=(',',':')).encode();newfile='api-data/'+hashlib.sha256(raw).hexdigest()+'.json.gz'
 fixtures[newfile]=gzip.compress(raw)
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True);page=browser.new_page(viewport={'width':1512,'height':1100})
  page.on('pageerror',lambda e:REPORT['javascript_errors'].append(str(e)))
  if not USE_SERVED:page.route('**/pages-api.js',lambda r:r.fulfill(path=str(ROOT/'dashboard/static/pages-api.js'),content_type='text/javascript'))
  def publication(r):counts['publication']+=1;r.fulfill(body=json.dumps(active['publication']),content_type='application/json')
  def manifest(r):counts['manifest']+=1;r.fulfill(body=json.dumps(active['manifest']),content_type='application/json')
  def artifact(r):
   path='api-data/'+Path(urlparse(r.request.url).path).name
   if path in blocked:counts['removed']+=1;r.fulfill(status=REMOVED_STATUS,body='Removed by next publication')
   elif path in fixtures:counts['replacement']+=1;r.fulfill(content_type='application/gzip',body=fixtures[path])
   else:r.continue_()
  page.route('**/publication.json?*',publication);page.route('**/api-manifest.json?*',manifest);page.route('**/api-data/*',artifact)
  try:
   page.goto(BASE,wait_until='networkidle',timeout=180000);page.wait_for_function('CountyView.ready()&&Tracking.stateReady()',timeout=120000)
   assert counts['publication']==counts['manifest']==1
   active['manifest']=copy.deepcopy(active['manifest']);active['manifest']['routes'][route]=newfile
   active['publication']={**active['publication'],'revision':hashlib.sha256(json.dumps(active['manifest']).encode()).hexdigest()};blocked.add(oldfile)
   page.evaluate('()=>{window.__rolloverLoads=0;const original=window.load;window.load=async(...args)=>{window.__rolloverLoads++;return original(...args);};window.__rolloverProbe=fetch("/api/county-buckets?day=3&method=mail&metric=black_vap&view=demographic").then(async r=>({status:r.status,value:await r.json()}));CountyView.mode="demographic";CountyView.metricId="black_vap";CountyView.votingMethod="mail";document.getElementById("county-method").value="mail";day=3;updateView();}')
   page.wait_for_function('!CountyView.pending&&(CountyView.ready()&&CountyView.view?.rollover_marker==="current"||!document.getElementById("county-error").hidden)',timeout=120000)
   actual=page.evaluate('({ready:!!CountyView.ready(),marker:CountyView.view?.rollover_marker,error:document.getElementById("county-error").hidden?null:document.getElementById("county-error").textContent,selection:{day,mode:CountyView.mode,metric:CountyView.metricId,method:CountyView.votingMethod}})')
   REPORT['rollover']={'actual':actual,'requests':counts.copy()}
   assert actual['ready'] and actual.get('marker')=='current' and not actual['error'],REPORT['rollover']
   assert actual['selection']=={'day':3,'mode':'demographic','metric':'black_vap','method':'mail'}
   probe=page.evaluate('window.__rolloverProbe');assert probe['status']==200 and probe['value']['rollover_marker']=='current',probe
   assert page.evaluate('window.__rolloverLoads')==1
   assert counts=={'publication':2,'manifest':2,'removed':1,'replacement':1},counts
   REPORT['checks'].append('Concurrent removed-artifact reads coalesce one publication refresh, replacement fetch and preserved-filter view reload')
   # A genuine missing file under an unchanged publication must fail promptly.
   missing=active['manifest']['routes'][key(day='2',method='mail',metric='under18',view='demographic')];blocked.add(missing)
   before=counts.copy();result=page.evaluate('async()=>{const r=await fetch("/api/county-buckets?day=2&method=mail&metric=under18&view=demographic");return {status:r.status,value:await r.json()};}')
   assert result['status']==503 and result['value']['error']=='Published selection unavailable',result
   assert counts['publication']==before['publication']+1 and counts['manifest']==before['manifest'] and counts['removed']==before['removed']+1,counts
   REPORT['checks'].append('Unchanged revision and genuinely missing artifact return an error after one publication check')
   assert not REPORT['javascript_errors'];REPORT['passed']=True;REPORT['requests']=counts
   page.screenshot(path=str(OUT/f'visual-{TAG}-rollover.png'),full_page=True)
  finally:browser.close()
if __name__=='__main__':
 try:main()
 except BaseException:REPORT['passed']=False;REPORT['failure']=traceback.format_exc();raise
 finally:(OUT/f'visual-{TAG}-rollover-verification.json').write_text(json.dumps(REPORT,indent=2)+'\n')
