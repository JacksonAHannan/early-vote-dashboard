#!/usr/bin/env python3
"""Focused Pages revision checks at the exact hourly boundary.

Routes the current adapter over a frozen static export; no site files are edited.
TURNOUT_PAGES_URL=http://127.0.0.1:8745/turnout-pages-mail-20261025/ \
  uv run --with playwright python dashboard/tests/pages_hourly.py
"""
import copy
import gzip
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import traceback
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
BASE = os.environ.get('TURNOUT_PAGES_URL', 'http://127.0.0.1:8745/turnout-pages-mail-20261025/').rstrip('/') + '/'
ADAPTER = Path(os.environ.get('TURNOUT_PAGES_ADAPTER', ROOT / 'dashboard/static/pages-api.js'))
USE_SERVED_ADAPTER = os.environ.get('TURNOUT_PAGES_USE_SERVED_ADAPTER') == '1'
TAG = os.environ.get('TURNOUT_TEST_TAG', 'green')
assert TAG and all(c.isalnum() or c in '-_.' for c in TAG)
OUT = ROOT / 'analysis/mail-turnout/qa/pages-hourly' / TAG
OUT.mkdir(parents=True, exist_ok=True)
REPORT = {'base': BASE, 'adapter': str(ADAPTER), 'checks': [], 'javascript_errors': [], 'server_api_requests': []}


def passed(name, **details):
    REPORT['checks'].append({'name': name, **details})
    print(name, flush=True)


def read(path):
    with urlopen(BASE + path, timeout=120) as response:
        return json.load(response)


def main():
    active = {'publication': read('publication.json'), 'manifest': read('api-manifest.json')}
    observed = {'publication': 0, 'manifest': 0, 'fixtures': []}
    fixtures = {}
    adapter = ADAPTER.read_text()
    REPORT['adapter_sha256'] = hashlib.sha256(adapter.encode()).hexdigest()
    REPORT['adapter_source'] = 'served' if USE_SERVED_ADAPTER else 'routed-local'
    if USE_SERVED_ADAPTER:
        class Scripts(HTMLParser):
            def __init__(self):
                super().__init__()
                self.adapters = []

            def handle_starttag(self, tag, attrs):
                src = dict(attrs).get('src', '')
                name = urlparse(src).path.rsplit('/', 1)[-1]
                if tag == 'script' and name.startswith('pages-api') and name.endswith('.js'):
                    self.adapters.append(src)
        with urlopen(BASE, timeout=120) as response:
            index = response.read().decode()
        scripts = Scripts()
        scripts.feed(index)
        assert len(scripts.adapters) == 1, scripts.adapters
        served_url = urljoin(BASE, scripts.adapters[0])
        with urlopen(served_url, timeout=120) as response:
            served = response.read()
        assert served == adapter.encode(), ('Served adapter differs from current local source', served_url, hashlib.sha256(served).hexdigest(), REPORT['adapter_sha256'])
        REPORT['served_adapter_url'] = served_url
        passed('Actual adapter asset referenced by the served index exactly matches current local source', url=served_url, sha256=REPORT['adapter_sha256'])
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path='/usr/bin/chromium')
        page = browser.new_page(viewport={'width': 1512, 'height': 1050}, reduced_motion='reduce')
        # Freezing Date.now makes the threshold check exact, independent of how
        # long browser rendering takes. Browser waits and timers still run normally.
        page.add_init_script('window.__hourlyNow=1792886400000;Date.now=()=>window.__hourlyNow;')
        page.on('pageerror', lambda error: REPORT['javascript_errors'].append(str(error)))
        def count(request):
            path = urlparse(request.url).path
            if path.endswith('/publication.json'):
                observed['publication'] += 1
            elif path.endswith('/api-manifest.json'):
                observed['manifest'] += 1
            elif '/api/' in path:
                REPORT['server_api_requests'].append(request.url)
        page.on('request', count)
        if not USE_SERVED_ADAPTER:
            page.route('**/pages-api*.js*', lambda route: route.fulfill(content_type='text/javascript', body=adapter))
        page.route('**/publication.json?*', lambda route: route.fulfill(content_type='application/json', body=json.dumps(active['publication'])))
        page.route('**/api-manifest.json?*', lambda route: route.fulfill(content_type='application/json', body=json.dumps(active['manifest'])))
        def artifact(route):
            filename = urlparse(route.request.url).path.rsplit('/', 1)[-1]
            if filename in fixtures:
                observed['fixtures'].append(filename)
                route.fulfill(content_type='application/gzip', body=fixtures[filename])
            else:
                route.continue_()
        page.route('**/api-data/*', artifact)
        page.goto(BASE + '#counties', wait_until='networkidle')
        page.wait_for_function('CountyView.ready()&&Tracking.stateReady()&&!CountyView.pending', timeout=120000)
        assert (observed['publication'], observed['manifest']) == (1, 1), observed

        # The initial publication check occurred at the frozen epoch. Neither
        # repeated status reads nor the last millisecond before expiry may poll.
        page.evaluate('async()=>{window.__hourlyNow+=3599999;for(let i=0;i<12;i++)await fetch("/api/status");}')
        assert (observed['publication'], observed['manifest']) == (1, 1), observed
        page.evaluate('async()=>{window.__hourlyNow+=1;await fetch("/api/status");}')
        assert (observed['publication'], observed['manifest']) == (2, 1), observed
        page.evaluate('async()=>{for(let i=0;i<12;i++)await fetch("/api/status");}')
        assert (observed['publication'], observed['manifest']) == (2, 1), observed
        passed('Exactly one hour triggers one small publication check; unchanged revision reuses the manifest', **observed)

        # Preserve an actual nondefault user selection through the revision swap.
        page.locator('#county-demographic').click()
        page.locator('#county-metric').select_option('non_white_vap')
        page.locator('#county-method').select_option('mail')
        page.get_by_role('button', name='Day 3', exact=True).click()
        page.wait_for_function('CountyView.ready()&&!CountyView.pending&&CountyView.view.voting_method==="mail"&&CountyView.view.day===3&&Tracking.stateReady()&&Tracking.state.voting_method==="mail"', timeout=120000)
        page.locator('#county-bucket-measure').select_option('cumulative')
        page.locator('#statewide-measure').select_option('cumulative')
        page.locator('[data-state-county="harris"]').click()
        selected = page.evaluate('({method:CountyView.votingMethod,view:CountyView.mode,metric:CountyView.metricId,measure:CountyView.measure,day,stateCounty:Tracking.stateCounty,stateMeasure:Tracking.stateMeasure})')
        generation = page.evaluate('data.generated_at')
        before = page.evaluate('({county:CountyView.key,state:Tracking.stateKey})')
        assert before['county'] and before['state'], before
        county_view = page.evaluate('structuredClone(CountyView.view)')
        county_state = page.evaluate('structuredClone(Tracking.state)')
        county_row = next(row for row in county_view['counties'] if row['id'] == 'harris')
        stamp = next(row for row in county_state['counties'] if row['id'] == 'harris')['days'][2]
        old_votes = county_row['votes_2026']
        sentinel = old_votes + 101
        assert stamp['cumulative_2026'] == old_votes
        county_row['votes_2026'] = sentinel
        county_row['ratio'] = sentinel / county_row['votes_2024']
        for bucket in [county_view['buckets'][county_row['bucket']], county_view['totals']]:
            bucket['days'][2]['cumulative_2026'] += 101
        stamp['cumulative_2026'] = sentinel
        stamp['by_method']['mail']['cumulative_2026'] = sentinel
        updated = copy.deepcopy(active['manifest'])
        def store(value):
            raw = json.dumps(value, separators=(',', ':')).encode()
            filename = hashlib.sha256(raw).hexdigest() + '.json.gz'
            fixtures[filename] = gzip.compress(raw)
            return 'api-data/' + filename
        query = {'day': '3', 'method': 'mail', 'metric': 'non_white_vap', 'view': 'demographic'}
        county_key = '/api/county-buckets?' + urlencode(sorted(query.items()))
        assert county_key in updated['routes'], county_key
        updated['routes'][county_key] = store(county_view)
        updated['routes']['/api/statewide?method=mail'] = store(county_state)
        eq_generation = active['publication']['generated_at']
        active['manifest'] = updated
        active['publication'] = {**active['publication'], 'revision': hashlib.sha256(json.dumps(updated).encode()).hexdigest()}
        assert active['publication']['generated_at'] == eq_generation

        # Fetching a status at the next exact boundary discovers the changed
        # publication without changing the precinct snapshot's generation.
        page.evaluate('async()=>{window.__hourlyNow+=3600000;await fetch("/api/status");}')
        assert (observed['publication'], observed['manifest']) == (3, 2), observed
        cleared = page.evaluate('({county:CountyView.key,state:Tracking.stateKey})')
        assert cleared == {'county': '', 'state': ''}, (before, cleared)
        assert page.evaluate('data.generated_at') == generation
        passed('A county-only publication invalidates both derived caches with unchanged Texas precinct generation', before=before, after=cleared, generated_at=generation)

        page.locator('#refresh').click()
        expect(page.locator('#refresh')).to_have_text('Check updates')
        expect(page.locator('#refresh')).to_be_enabled()
        page.wait_for_function('(n)=>CountyView.ready()&&!CountyView.pending&&Tracking.stateReady()&&CountyView.view.counties.find(c=>c.id==="harris").votes_2026===n&&Tracking.state.counties.find(c=>c.id==="harris").days[2].cumulative_2026===n', arg=sentinel, timeout=120000)
        after = page.evaluate('({method:CountyView.votingMethod,view:CountyView.mode,metric:CountyView.metricId,measure:CountyView.measure,day,stateCounty:Tracking.stateCounty,stateMeasure:Tracking.stateMeasure})')
        assert after == selected, (selected, after)
        assert page.evaluate('data.generated_at') == generation
        assert (observed['publication'], observed['manifest']) == (4, 2), observed
        row = page.locator('#statewide-table tr:has([data-state-county="harris"])')
        expect(row).to_contain_text(f'{sentinel:,}')
        exported = page.evaluate('async()=>{const r=await fetch(document.querySelector("#statewide-download").href);return r.text();}')
        assert str(sentinel) in exported
        assert len(set(observed['fixtures'])) == 2, observed
        passed('Check updates renders changed county values and CSV while preserving method, demographic view, metric and selected date', selection=after, previous_votes=old_votes, new_votes=sentinel, fixture_artifacts=sorted(set(observed['fixtures'])))
        assert not REPORT['server_api_requests'], REPORT['server_api_requests']
        assert not REPORT['javascript_errors'], REPORT['javascript_errors']
        page.screenshot(path=str(OUT / 'county-revision.png'), full_page=True)
        passed('Project-subpath update uses no backend API requests and has zero JavaScript errors')
        REPORT['requests'] = observed
        browser.close()


try:
    main()
    REPORT['passed'] = True
except BaseException:
    REPORT['passed'] = False
    REPORT['failure'] = traceback.format_exc()
    raise
finally:
    (OUT / 'verification.json').write_text(json.dumps(REPORT, indent=2) + '\n')
