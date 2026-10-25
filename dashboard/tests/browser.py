"""Browser acceptance checks against the running Rust server."""
from pathlib import Path
import csv
import io
import json
import os
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[2]
BASE=os.environ.get('TURNOUT_TEST_URL','http://127.0.0.1:8741')
OUT=ROOT/'analysis/updated-through-2026-10-22/qa'
OUT.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
    context=browser.new_context(viewport={'width':1512,'height':1100},device_scale_factor=1)
    page=context.new_page();errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(BASE+'/',wait_until='networkidle')
    page.locator('#precincts-tab').click()
    page.get_by_role('button',name='Day 4',exact=True).click()
    expect(page.locator('#matrix [data-county]')).to_have_count(min(12,len(page.request.get(BASE+'/api/data').json()['counties'])))
    expect(page.locator('#matrix tbody tr')).to_have_count(6)
    expect(page.locator('#period')).to_contain_text('Oct 19–22')
    expect(page.locator('#detail-name')).to_have_text('Travis precincts')
    assert page.locator('#error').is_hidden()
    page.screenshot(path=str(OUT/'dashboard-desktop.png'),full_page=True)
    page.get_by_role('button',name='Day 1',exact=True).click()
    assert page.locator('#matrix [data-cell^="ellis:"]').count()==0
    page.get_by_role('button',name='Day 4',exact=True).click()
    page.locator('#cohort').select_option('unchanged')
    assert 'unchanged' in page.locator('#download').get_attribute('href')
    page.locator('#county').select_option('dallas')
    expect(page.locator('#matrix [data-county]')).to_have_count(1)
    expect(page.locator('#detail-name')).to_have_text('Dallas precincts')
    page.locator('#cohort').select_option('matched')
    page.locator('#matrix [data-cell="dallas:0"]').click()
    expect(page.locator('#clear-filter')).to_be_visible()
    page.locator('#clear-filter').click()
    target=page.locator('#groups tbody tr td').first.inner_text().split(',')[0].split('\n')[0].strip()
    page.locator('#search').fill(target)
    rows=page.locator('#groups tbody tr').all_text_contents()
    assert rows and all(target in r for r in rows),rows
    page.locator('#search').clear()
    page.locator('#sort-2024').click()
    page.locator('#next').click();expect(page.locator('#page')).to_contain_text('31')
    page.locator('#previous').click();expect(page.locator('#page')).to_contain_text('1')
    page.locator('#precinct-trends-tab').click()
    with page.expect_download() as info:page.locator('#download').click()
    download=info.value;download.save_as(str(OUT/'dallas-buckets.csv'))
    with (OUT/'dallas-buckets.csv').open() as f:records=list(csv.DictReader(f))
    assert len(records)==6 and {r['county'] for r in records}=={'Dallas'}
    page.locator('#methods summary').click();expect(page.locator('#sources')).to_be_visible()
    assert page.locator('#sources a').count()>=60
    page.locator('#county').select_option('all')
    page.locator('#matrix [data-county="travis"]').click()
    page.locator('#methods summary').click()
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),page.evaluate('[document.documentElement.scrollWidth,innerWidth]')
    expect(page.locator('#days')).to_be_visible()
    page.locator('#precinct-trends-tab').click()
    page.locator('#county').select_option('madison')
    assert page.locator('#matrix').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
    page.locator('#county').select_option('all')
    page.locator('#matrix [data-county="travis"]').click()
    page.screenshot(path=str(OUT/'dashboard-mobile.png'),full_page=True)
    # Exercise stale and unavailable county rendering without altering the saved snapshot.
    snapshot=page.request.get(BASE+'/api/data').json()
    snapshot['counties'][0]['status']='stale';snapshot['counties'][0]['error']='test source offline'
    snapshot['counties'][1]['status']='missing';snapshot['counties'][1]['periods']=[];snapshot['counties'][1]['error']='test export not posted'
    page.route('**/api/data',lambda route:route.fulfill(json=snapshot))
    page.reload(wait_until='networkidle')
    expect(page.locator('#error')).to_contain_text('last successful download')
    expect(page.locator('#error')).to_contain_text('Dallas: data unavailable')
    assert page.locator('#matrix [data-cell^="dallas:"]').count()==0
    assert page.locator('#matrix [data-cell^="travis:"]').count()==6
    page.unroute('**/api/data')
    page.route('**/api/refresh',lambda route:route.fulfill(status=202,body='Refresh started'))
    page.locator('#refresh').click();expect(page.locator('#sync')).to_have_text('Refreshing…')
    assert not errors,errors
    (OUT/'browser-verification.json').write_text(json.dumps({'status':'passed','checks':['paginated precinct-county matrix','day cutoffs and unavailable Ellis earlier days','cohort switch','county selection','bucket selection','precinct search','sorting','pagination','CSV download','source disclosure','mobile overflow','stale retention','missing county','refresh interaction'],'javascript_errors':errors},indent=2)+'\n')
    print('Browser checks passed; desktop/mobile screenshots saved.')
    browser.close()
