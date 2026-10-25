"""Verify a generated Pages bundle, including operation under a repository subpath.
TURNOUT_PAGES_URL=http://127.0.0.1:8745/turnout-pages-qa-20261024/ \
  uv run --with playwright python dashboard/tests/pages_browser.py
"""
import json
import os
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, expect

BASE=os.environ.get('TURNOUT_PAGES_URL','http://127.0.0.1:8745/turnout-pages-qa-20261024/')
LIVE=os.environ.get('TURNOUT_LIVE_URL','http://127.0.0.1:8741')
OUT=Path(__file__).resolve().parents[2]/'analysis/multistate/qa'
OUT.mkdir(parents=True,exist_ok=True)
report={'base':BASE,'live':LIVE,'checks':[],'errors':[],'network_api_requests':[]}

def passed(name,**details):
    report['checks'].append({'name':name,'passed':True,**details})
    print(name,flush=True)

def selected(page,state):
    page.goto(BASE+'#state='+state,wait_until='domcontentloaded')
    page.wait_for_function('(s)=>States.id===s&&States.view?.id===s&&!States.busy',arg=state,timeout=180000)
    expect(page.locator('#state-error')).to_be_hidden()

try:
    with sync_playwright() as pw:
        browser=pw.chromium.launch()
        page=browser.new_page(viewport={'width':1512,'height':1000},accept_downloads=True)
        page.on('pageerror',lambda e:report['errors'].append(str(e)))
        page.on('request',lambda r:report['network_api_requests'].append(r.url) if '/api/' in r.url and '/api-data/' not in r.url else None)
        selected(page,'ga')
        assert page.evaluate('States.classification')=='race'
        assert page.locator('#state-buckets svg').count()>0
        assert page.evaluate('States.view.counties.length')==159
        passed('Subpath Georgia loads with statewide voter race and county map')
        paths=[
            '/api/data','/api/statewide','/api/demographics','/api/primary','/api/reference','/api/completeness',
            '/api/trends?county=all&cohort=matched&view=partisan&metric=partisan',
            '/api/trends?county=tarrant&cohort=unchanged&view=demographic&metric=non_white_vap',
            '/api/demographic-view?day=1&cohort=matched&view=demographic&metric=black_vap',
            '/api/county-buckets?day=3&view=demographic&metric=non_white_vap',
            '/api/states/ga?method=in_person&classification=race&date=2026-10-23',
            '/api/states/ga?method=total&classification=age&date=2026-10-30',
            '/api/states/nc?method=in_person&classification=white_nonwhite&date=2026-10-20',
            '/api/states/nc?method=mail&classification=demographic&metric=under18&date=2026-10-24',
            '/api/states/va?method=total&classification=partisan&date=2026-09-20',
            '/api/states/nv?method=mail&classification=party&date=2026-10-23',
            '/api/states/nv?method=in_person&classification=demographic&metric=black_nh_vap&date=2026-10-30',
            '/api/states/nc/precincts?county=37119&method=in_person&measure=cumulative&date=2026-10-23',
            '/api/states/va/precincts?county=51059&method=in_person&measure=daily&date=2026-10-23',
            '/api/states/nv/precincts?county=32003&method=total&measure=cumulative&date=2026-10-23',
            '/api/map/tarrant','/api/states/nv/map',
        ]
        for path in paths:
            result=page.evaluate('async p=>{const r=await fetch(p);return {status:r.status,value:await r.json()};}',path)
            assert result['status']==200,(path,result)
            if os.environ.get('TURNOUT_PAGES_SKIP_LIVE')!='1':
                with urlopen(LIVE+path,timeout=180) as response:
                    live=json.load(response)
                assert result['value']==live,f'Published/live response differs: {path}'
            passed('API parity '+path)
        for state,count in [('nc',100),('va',133),('nv',2)]:
            selected(page,state)
            assert page.evaluate('States.view.counties.length')==count
            page.wait_for_function('!!States.layer',timeout=30000)
            passed('Subpath state UI '+state,counties=count)
        page.locator('#refresh').click()
        expect(page.locator('#refresh')).to_have_text('Check updates')
        expect(page.locator('#refresh')).to_be_enabled()
        passed('Manual update check returns without a stuck refreshing state')
        selected(page,'ga')
        page.locator('#state-date').fill('2026-10-30')
        page.locator('#state-date').dispatch_event('change')
        page.wait_for_function('!States.busy&&States.view.date==="2026-10-30"',timeout=180000)
        assert page.evaluate('States.view.series.find(r=>r.date_2026==="2026-10-30").cumulative_2026') is None
        passed('Future date retains historical baseline without current zero')
        page.set_viewport_size({'width':390,'height':844})
        page.wait_for_timeout(500)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(OUT/'pages-ga-mobile.png'),full_page=True)
        passed('Mobile subpath layout has no horizontal overflow')
        page.set_viewport_size({'width':1512,'height':1000})
        page.select_option('#state-select','tx')
        page.wait_for_function('States.id==="tx"&&data?.counties.length>0',timeout=180000)
        page.wait_for_function('CountyView.ready()',timeout=180000)
        assert page.evaluate('data.counties.length')==215
        page.locator('#precincts-tab').click()
        page.locator('#precinct-trends-tab').click()
        with page.expect_download() as download:
            page.locator('#download').click()
        content=Path(download.value.path()).read_text()
        assert 'votes_2024' in content and len(content.splitlines())>10
        passed('Texas partisan CSV download works through Pages adapter',bytes=len(content))
        assert not report['network_api_requests'],report['network_api_requests']
        assert not report['errors'],report['errors']
        passed('No server API requests or JavaScript errors')
        browser.close()
    report['passed']=True
except BaseException:
    report['passed']=False
    raise
finally:
    (OUT/'pages-browser.json').write_text(json.dumps(report,indent=2)+'\n')
