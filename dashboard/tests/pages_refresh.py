"""Focused Pages publication polling, gzip transport, and retained-selection checks."""
import gzip
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

BASE=os.environ.get('TURNOUT_PAGES_URL','http://127.0.0.1:8745/turnout-pages-qa-20261024/')
SITE=Path(os.environ.get('TURNOUT_PAGES_DIR','/tmp/turnout-pages-qa-20261024'))
OUT=Path(__file__).resolve().parents[2]/'analysis/multistate/qa/pages-refresh.json'
report={'checks':[],'errors':[]}
def passed(name,**details):
    report['checks'].append({'name':name,'passed':True,**details});print(name,flush=True)
try:
    with sync_playwright() as pw:
        browser=pw.chromium.launch()
        page=browser.new_page(viewport={'width':1400,'height':1000})
        requests={'publication':0,'manifest':0}
        def count(request):
            if urlparse(request.url).path.endswith('/publication.json'):requests['publication']+=1
            elif urlparse(request.url).path.endswith('/api-manifest.json'):requests['manifest']+=1
        page.on('request',count)
        page.on('pageerror',lambda e:report['errors'].append(str(e)))
        page.goto(BASE+'#state=ga',wait_until='domcontentloaded')
        page.wait_for_function('!States.busy&&States.view?.id==="ga"',timeout=180000)
        assert requests['manifest']==1,requests
        before=dict(requests)
        page.evaluate('async()=>{for(let i=0;i<8;i++)await fetch("/api/status");}')
        assert requests==before,requests
        passed('Repeated five-second status polling reuses the cached publication',requests=dict(requests))
        selected=page.evaluate('({county:States.county,date:States.date})')
        page.locator('#refresh').click()
        expect(page.locator('#refresh')).to_have_text('Check updates')
        page.wait_for_function('!States.busy',timeout=180000)
        assert requests['publication']==before['publication']+1,requests
        assert requests['manifest']==before['manifest'],requests
        assert page.evaluate('({county:States.county,date:States.date})')==selected
        passed('Manual check polls only the small revision when unchanged and retains selection',requests=dict(requests))
        revision='0'*64
        publication=json.loads((SITE/'publication.json').read_text())
        old_generated=publication['generated_at'];publication['revision']=revision
        page.route('**/publication.json?*',lambda route:route.fulfill(content_type='application/json',body=json.dumps(publication)))
        page.locator('#refresh').click()
        expect(page.locator('#refresh')).to_have_text('Check updates')
        page.wait_for_function('!States.busy',timeout=180000)
        assert requests['manifest']==before['manifest']+1,requests
        passed('A new manifest revision loads even when Texas generation is unchanged',texas_generated_at=old_generated,requests=dict(requests))
        page.close()
        # Some CDNs transparently decode gzip: the adapter accepts either representation.
        page=browser.new_page(viewport={'width':1400,'height':1000})
        page.on('pageerror',lambda e:report['errors'].append(str(e)))
        def decoded(route):
            filename=urlparse(route.request.url).path.rsplit('/',1)[-1]
            route.fulfill(content_type='application/json',body=gzip.decompress((SITE/'api-data'/filename).read_bytes()))
        page.route('**/api-data/*.json.gz',decoded)
        page.goto(BASE+'#state=nv',wait_until='domcontentloaded')
        page.wait_for_function('!States.busy&&States.view?.id==="nv"',timeout=180000)
        assert page.evaluate('States.view.counties.length')==2
        expect(page.locator('#state-error')).to_be_hidden()
        passed('Already-decoded gzip artifacts load without a second decompression')
        assert not report['errors'],report['errors']
        browser.close()
    report['passed']=True
except BaseException:
    report['passed']=False
    raise
finally:
    OUT.write_text(json.dumps(report,indent=2)+'\n')
