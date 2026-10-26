#!/usr/bin/env python3
"""Same-generation Pages republication and delayed precinct-response regression.

TURNOUT_PAGES_URL=https://jacksonahannan.github.io/early-vote-dashboard/ \
 uv run --with playwright --with pillow python dashboard/tests/texas_revision_stress.py
Routes current frontend assets and anonymous aggregate fixtures over a frozen site.
"""
import copy
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import traceback
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen

from PIL import Image
from playwright.sync_api import expect, sync_playwright

ROOT=Path(__file__).resolve().parents[2]
BASE=os.environ.get('TURNOUT_PAGES_URL','https://jacksonahannan.github.io/early-vote-dashboard/').rstrip('/')+'/'
TAG=os.environ.get('TURNOUT_TEST_TAG','revision')
OUT=ROOT/'analysis/texas-stress';OUT.mkdir(parents=True,exist_ok=True)
REPORT={'url':BASE,'checks':[],'javascript_errors':[],'backend_api_requests':[]}


def passed(name,**details):
    REPORT['checks'].append({'name':name,**details});print(name,flush=True)


def read(path):
    with urlopen(BASE+path,timeout=120) as r:return json.load(r)


def fit(points):
    points=[p for p in points if p['x'] is not None and p['y'] is not None]
    mx=math.fsum(p['x'] for p in points)/len(points);my=math.fsum(p['y'] for p in points)/len(points)
    xx=math.fsum((p['x']-mx)**2 for p in points)
    slope=math.fsum((p['x']-mx)*(p['y']-my) for p in points)/xx
    intercept=my-slope*mx
    yy=math.fsum((p['y']-my)**2 for p in points)
    residual=math.fsum((p['y']-intercept-slope*p['x'])**2 for p in points)
    return {'slope':slope,'intercept':intercept,'r_squared':max(0,min(1,1-residual/yy)) if yy else None,'x_min':min(p['x'] for p in points),'x_max':max(p['x'] for p in points)}


def main():
    active={'publication':read('publication.json'),'manifest':read('api-manifest.json')}
    fixtures={};counts={'publication':0,'manifest':0}
    def store(value):
        raw=json.dumps(value,separators=(',',':')).encode();name=hashlib.sha256(raw).hexdigest()+'.json.gz'
        fixtures[name]=gzip.compress(raw);return 'api-data/'+name
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
        page=browser.new_page(viewport={'width':1512,'height':1100},accept_downloads=True,reduced_motion='reduce')
        page.on('pageerror',lambda e:REPORT['javascript_errors'].append(str(e)))
        page.on('request',lambda r:REPORT['backend_api_requests'].append(r.url) if '/api/' in urlparse(r.url).path else None)
        for name in ('pages-api.js','app.js','tracking.js','county-view.js','visuals.js'):
            page.route('**/'+name,lambda route:route.fulfill(path=str(ROOT/'dashboard/static'/Path(urlparse(route.request.url).path).name),content_type='text/javascript'))
        def publication(route):
            counts['publication']+=1;route.fulfill(content_type='application/json',body=json.dumps(active['publication']))
        def manifest(route):
            counts['manifest']+=1;route.fulfill(content_type='application/json',body=json.dumps(active['manifest']))
        def artifact(route):
            name=Path(urlparse(route.request.url).path).name
            if name in fixtures:route.fulfill(content_type='application/gzip',body=fixtures[name])
            else:route.continue_()
        page.route('**/publication.json?*',publication);page.route('**/api-manifest.json?*',manifest);page.route('**/api-data/*',artifact)
        try:
            page.goto(BASE+'#precinct-explore',wait_until='networkidle',timeout=180000)
            page.wait_for_function('data&&CountyView.ready()&&Tracking.stateReady()',timeout=180000)
            page.locator('#county').select_option('tarrant');page.locator('#demographic-mode').click();page.locator('#metric').select_option('non_white_vap')
            page.get_by_role('button',name='Day 3',exact=True).click();page.locator('#regression-scale').select_option('full')
            page.wait_for_function("demoReady()&&mode==='demographic'&&county==='tarrant'&&day===3&&Tracking.view&&Tracking.key",timeout=180000)
            initial=page.evaluate('({data:structuredClone(data),demo:{generated_at:data.generated_at,views:structuredClone(demoViews)},trends:structuredClone(Tracking.view),selection:{county,day,cohort,mode,metric:metricId,winner:regressionWinner,scale:document.getElementById("regression-scale").value}})')
            assert initial['trends']['metric']=='non_white_vap'
            point=initial['demo']['views']['tarrant']['points'][0];target=point['id'];index=point['group_index'];bucket=point['bucket'];delta=101
            old_votes=point['votes_2026'];sentinel=old_votes+delta
            updated_data=copy.deepcopy(initial['data']);updated_demo=copy.deepcopy(initial['demo']);updated_trends=copy.deepcopy(initial['trends'])
            period=next(p for c in updated_data['counties'] if c['id']=='tarrant' for p in c['periods'] if p['day']==3)
            period['groups'][index]['votes_2026']=sentinel;period['county_2026']+=delta;period['county_ratio']=period['county_2026']/period['county_2024']
            for scope in ('tarrant','all'):
                view=updated_demo['views'][scope];p=next(p for p in view['points'] if p['id']==target)
                p['votes_2026']=sentinel;p['y']=100*sentinel/p['votes_2024']
                view['bins'][bucket]['votes_2026']+=delta;view['bins'][bucket]['ratio']=view['bins'][bucket]['votes_2026']/view['bins'][bucket]['votes_2024'];view['fit']=fit(view['points'])
            for panel in (updated_trends['buckets'][bucket],updated_trends['totals']):
                row=next(d for d in panel['days'] if d['day']==3);row['cumulative_2026']+=delta
            expected=updated_demo['views']['tarrant']['bins'][bucket]['votes_2026']
            expected_fit=updated_demo['views']['tarrant']['fit']
            expected_trend=next(d for d in updated_trends['buckets'][bucket]['days'] if d['day']==3)['cumulative_2026']
            # Hold old same-key requests while the next publication becomes active.
            # A new load must create distinct requests, not accept these old ones.
            page.evaluate('''old=>{window.__revisionOld=old;window.__revisionFetch=window.fetch;window.__revisionHeld=[];window.__revisionSeen=new Set();window.fetch=(input,init)=>{const path=new URL(typeof input==='string'?input:input.url,location.href).pathname,key=path.endsWith('/api/demographic-view')?'demo':path.endsWith('/api/trends')?'trends':null;if(key&&!window.__revisionSeen.has(key)){window.__revisionSeen.add(key);return new Promise(resolve=>window.__revisionHeld.push({key,resolve}));}return window.__revisionFetch(input,init);};demoKey='';Tracking.key='';ensureDemo();Tracking.update(Tracking.ctx);}''',{'demo':initial['demo'],'trends':initial['trends']})
            page.wait_for_function('window.__revisionHeld.length===2')
            updated_manifest=copy.deepcopy(active['manifest'])
            updated_manifest['routes']['/api/data']=store(updated_data)
            demo_key='/api/demographic-view?'+urlencode(sorted({'day':'3','cohort':'matched','view':'demographic','metric':'non_white_vap'}.items()))
            trends_key='/api/trends?'+urlencode(sorted({'county':'tarrant','cohort':'matched','view':'demographic','metric':'non_white_vap'}.items()))
            assert demo_key in updated_manifest['routes'] and trends_key in updated_manifest['routes']
            updated_manifest['routes'][demo_key]=store(updated_demo);updated_manifest['routes'][trends_key]=store(updated_trends)
            generation=initial['data']['generated_at'];active['manifest']=updated_manifest
            active['publication']={**active['publication'],'revision':hashlib.sha256(json.dumps(updated_manifest).encode()).hexdigest()}
            page.locator('#refresh').click();expect(page.locator('#refresh')).to_be_enabled(timeout=120000)
            page.evaluate('''()=>{for(const h of window.__revisionHeld)h.resolve(new Response(JSON.stringify(window.__revisionOld[h.key]),{headers:{'Content-Type':'application/json'}}));window.fetch=window.__revisionFetch;}''')
            page.wait_for_function('demoReady()&&Tracking.view&&Tracking.key&&!Tracking.pending',timeout=120000)
            actual=page.evaluate('e=>({generation:data.generated_at,bin:demoViews.tarrant.bins[e.bucket].votes_2026,fit:demoViews.tarrant.fit,trend:Tracking.view.buckets[e.bucket].days.find(d=>d.day===3).cumulative_2026,selection:{county,day,cohort,mode,metric:metricId,winner:regressionWinner,scale:document.getElementById("regression-scale").value}})',{'bucket':bucket})
            assert actual['generation']==generation
            assert actual['selection']==initial['selection']
            assert actual['bin']==expected,(actual,expected)
            assert actual['trend']==expected_trend,(actual,expected_trend)
            for key in ('slope','intercept','r_squared'):assert math.isclose(actual['fit'][key],expected_fit[key],abs_tol=1e-10),(key,actual['fit'],expected_fit)
            line=page.locator('#regression-chart .regression-fit')
            assert math.isclose(float(line.get_attribute('data-slope')),expected_fit['slope'],abs_tol=1e-10)
            displayed=float(page.locator(f'#regression-chart .regression-point[data-id="{target}"]').get_attribute('data-y'))
            assert math.isclose(displayed,100*sentinel/point['votes_2024'],abs_tol=1e-10)
            passed('Same-generation republication refreshes bins, displayed points, All OLS and trends; old pending responses cannot overwrite them',target=target,previous_votes=old_votes,current_votes=sentinel,generated_at=generation,selection=actual['selection'])
            # Repeated status reads inside the hourly TTL must not invalidate data.
            before=page.evaluate('({demo:demoKey,trend:Tracking.key})');before_counts=counts.copy()
            page.evaluate('async()=>{for(let i=0;i<12;i++)await fetch("/api/status");}')
            assert counts==before_counts and page.evaluate('({demo:demoKey,trend:Tracking.key})')==before
            passed('Unchanged publication status checks preserve the accepted derived caches',requests=counts)
            with page.expect_download(timeout=60000) as event:page.locator('[data-image="regression"]').click()
            png=OUT/f'visual-{TAG}-revision.png';event.value.save_as(png)
            with Image.open(png) as image:assert (image.width == 1600 and 800 <= image.height <= 2000)
            assert not REPORT['javascript_errors'] and not REPORT['backend_api_requests'],REPORT
            passed('Updated regression exports a real PNG with zero JavaScript errors or backend API requests',file=png.name)
            REPORT['passed']=True
        finally:browser.close()


if __name__=='__main__':
    try:main()
    except BaseException:REPORT['passed']=False;REPORT['failure']=traceback.format_exc();raise
    finally:(OUT/f'visual-{TAG}-revision-verification.json').write_text(json.dumps(REPORT,indent=2)+'\n')
