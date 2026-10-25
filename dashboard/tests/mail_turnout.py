#!/usr/bin/env python3
"""Independent raw-source, API, export and browser checks for mail + early voting.

TURNOUT_TEST_URL=http://127.0.0.1:8743 uv run --with playwright --with pillow \
    python dashboard/tests/mail_turnout.py
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
from functools import lru_cache
import hashlib
from html.parser import HTMLParser
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import traceback
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'analysis/mail-turnout/qa'
TAG = os.environ.get('TURNOUT_TEST_TAG', '')
if TAG:
    assert re.fullmatch(r'[A-Za-z0-9_.-]+', TAG), 'Invalid QA artifact tag'
    OUT /= TAG
BASE = os.environ.get('TURNOUT_TEST_URL', 'http://127.0.0.1:8743').rstrip('/')
REPORT = {'base': BASE, 'checks': [], 'counts': {}, 'images': [], 'javascript_errors': []}
COUNTS = collections.Counter()


def passed(name, **details):
    REPORT['checks'].append({'name': name, **details})
    print(name, flush=True)


def eq(actual, expected, context):
    COUNTS['assertions'] += 1
    assert actual == expected, (context, actual, expected)


def get(path, params=None):
    with urlopen(BASE + path + ('?' + urlencode(params) if params else ''), timeout=120) as response:
        return json.load(response)


def canonical(name):
    return ''.join(c for c in name.casefold() if c.isascii() and c.isalnum())


class Table(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
        elif tag in ('th', 'td') and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ('th', 'td') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def number(value):
    if value is None or str(value).strip() in ('', '-', '—', 'N/A', 'NA'):
        return None
    text = str(value).replace(',', '')
    assert text.isdigit(), value
    return int(text)


class TexasSources:
    """Start with immutable publisher bytes, not API or derived by_method values."""
    def __init__(self):
        self.state = json.loads((ROOT / 'dashboard/data/statewide.json').read_text())
        self.through = self.state['through']
        self.observed = (dt.date.fromisoformat(self.through) - dt.date(2026, 10, 19)).days + 1
        self.reference = json.loads((ROOT / 'dashboard/data/county-reference.json').read_text())
        self.ids = {c['state_id']: c['id'] for c in self.state['counties']}
        self.names = {canonical(c['name']): c['id'] for c in self.state['counties']}
        self.native = {}
        self.controls = {}
        for row in json.loads((ROOT / 'dashboard/data/completeness.json').read_text())['controls']:
            if row['completed'] and row['scope'] == 'in_person':
                self.controls[row['county'], row['date']] = row
        for year in (2024, 2026):
            directory = ROOT / f'dashboard/data/statewide-cache/{year}'
            for file in sorted(directory.glob('????-??-??.json')):
                cache = json.loads(file.read_text())
                source = cache['source']
                extension = 'html' if year == 2024 else 'json'
                raw_file = directory / f"{cache['date']}.{source['sha256']}.response.{extension}"
                if not raw_file.exists():
                    raw_file = directory / f"{cache['date']}.response.{extension}"
                raw = raw_file.read_bytes()
                eq(hashlib.sha256(raw).hexdigest(), source['sha256'], str(raw_file) + '/source hash')
                if year == 2026:
                    native = json.loads(raw)
                    eq(native['early_voting_date'], cache['date'], str(file) + '/native date')
                    rows = {self.ids[r['id']]: {'daily': number(r.get('in_person_votes_on_date')),
                            'cumulative': number(r.get('total_in_person_votes_for_election')),
                            'mail': number(r.get('total_mail_votes_for_election'))}
                            for r in native['turnout_by_county']}
                else:
                    parser = Table()
                    parser.feed(raw.decode())
                    header = next(r for r in parser.rows if r and r[0] == 'County')
                    eq(header[5], 'Cumulative By Mail Voters', str(file) + '/mail header')
                    eq(header[6], 'Cumulative In-Person And Mail Voters', str(file) + '/combined header')
                    rows = {}
                    for r in parser.rows:
                        if len(r) != 9 or canonical(r[0]) not in self.names:
                            continue
                        eq(number(r[6]), number(r[3]) + number(r[5]), (file.name, r[0], 'published combined'))
                        rows[self.names[canonical(r[0])]] = {'daily': number(r[2]), 'cumulative': number(r[3]), 'mail': number(r[5])}
                    published = next(r for r in parser.rows if r and r[0] == 'TOTAL')
                    eq(sum(r['mail'] for r in rows.values()), number(published[5]), (file.name, 'published mail TOTAL'))
                eq(len(rows), 254, str(file) + '/counties')
                for r in cache['rows']:
                    eq(r['mail_cumulative'], rows[self.ids[r['state_id']]]['mail'], (file.name, r['name'], 'retained mail'))
                self.native[year, cache['date']] = rows
        passed('Immutable official bytes and all cached mail values reconcile', reports=len(self.native), counties=254)
        self.verify_harris_native_scope()

    def verify_harris_native_scope(self):
        """Independently reconcile the native PDF, without importing its parser."""
        pdf = ROOT / 'sources/completeness/harris.pdf'
        raw = pdf.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        text = subprocess.check_output(['pdftotext', '-layout', '-', '-'], input=raw).decode()
        assert 'November 3, 2026' in text
        date_row = next(line for line in text.splitlines() if 'LOCATIONS' in line and '19-Oct' in line)
        eq(re.findall(r'(\d+)-Oct', date_row), [str(n) for n in range(19, 31)], 'Harris PDF columns')
        records = {}
        for label in ('Early In-Person Voters:', 'Mail Ballots Received:', 'Total Early Voters:', 'Ballots Mailed:'):
            line = next(line for line in text.splitlines() if label in line)
            cells = [number(v) for v in line.split(label, 1)[1].split()]
            eq(len(cells), 13, label + '/columns')
            eq(sum(cells[:12]), cells[12], label + '/sum')
            records[label] = cells
        early, received, combined = (records[k] for k in ('Early In-Person Voters:', 'Mail Ballots Received:', 'Total Early Voters:'))
        for i in range(13):
            eq(early[i] + received[i], combined[i], ('Harris PDF', i, 'method sum'))
        for i in range(self.observed):
            stamp = (dt.date(2026, 10, 19) + dt.timedelta(days=i)).isoformat()
            control = self.controls['harris', stamp]
            eq(control['sha256'], digest, 'Harris IP control provenance')
            eq(control['daily'], early[i], 'Harris PDF independently parsed daily IP')
            eq(control['cumulative'], sum(early[:i + 1]), 'Harris PDF independently parsed cumulative IP')
        latest = self.source('harris', self.through)
        received_to_date = sum(received[:self.observed])
        assert received_to_date != latest['mail'], 'Exercise the native received/SOS mail discrepancy'
        REPORT['scope_crosscheck'] = {
            'harris_native_pdf_sha256': digest,
            'native_received_mail_2026': received_to_date,
            'sos_mail_2026': latest['mail'],
            'native_outgoing_mailed_total': records['Ballots Mailed:'][12],
            'decision': 'Use SOS by-mail consistently in both cycles; do not substitute unmatched native received-mail totals. Native full-county in-person controls remain independently reconciled.',
        }
        passed('Native Harris PDF independently validates IP controls and keeps incompatible received-mail scope separate', **REPORT['scope_crosscheck'])

    def source(self, county, date):
        return self.native.get((int(date[:4]), date), {}).get(county)

    def raw_ip(self, county, date, measure):
        row = self.source(county, date)
        if row is None or (date.startswith('2026') and date > self.through):
            return None
        value = row[measure]
        if date.startswith('2026') and row['daily'] == 0:
            value = None if measure == 'daily' or not value else value
        control = self.controls.get((county, date))
        if control and control[measure] is not None:
            value = control[measure]
        return value

    def value(self, county, day, year, method, measure):
        date = dt.date(year, 10, 21 if year == 2024 else 19) + dt.timedelta(days=day - 1)
        stamp = date.isoformat()
        if year == 2026 and stamp > self.through:
            return None
        row = self.source(county, stamp)
        mail = None if row is None else row['mail']
        if measure == 'daily':
            previous = self.source(county, (date - dt.timedelta(days=1)).isoformat())
            before = None if previous is None else previous['mail']
            mail = mail - before if mail is not None and before is not None and mail >= before else None
        if method == 'mail':
            return mail
        person = self.raw_ip(county, stamp, measure)
        if day <= self.observed:
            other = dt.date(2026 if year == 2024 else 2024, 10, 19 if year == 2024 else 21) + dt.timedelta(days=day - 1)
            if self.raw_ip(county, other.isoformat(), measure) is None:
                person = None
        return person if method == 'in_person' else person + mail if person is not None and mail is not None else None

    def bucket(self, county, metric=None):
        ref = self.reference['counties'][county]
        if metric:
            share = 100 * ref['counts'][metric['numerator']] / ref['counts'][metric['denominator']]
            return sum(share >= cut for cut in metric['cuts'])
        margin = 100 * (ref['harris'] - ref['trump']) / (ref['harris'] + ref['trump'])
        if margin == 0:
            return None
        return 0 if margin >= 30 else 1 if margin >= 15 else 2 if margin > 0 else 3 if margin > -15 else 4 if margin > -30 else 5


def texas_api(source):
    for method in ('total', 'mail'):
        state = get('/api/statewide', {'method': method})
        eq(state['voting_method'], method, 'state method')
        eq(len(state['counties']), 254, 'full county universe')
        for county in state['counties']:
            for day in county['days']:
                for measure, key in [('daily', 'votes'), ('cumulative', 'cumulative')]:
                    for year in (2024, 2026):
                        eq(day[f'{key}_{year}'], source.value(county['id'], day['day'], year, method, measure),
                           (method, county['id'], day['day'], year, measure))
                        COUNTS['texas_county_cells'] += 1
                eq(day['coverage']['cumulative_scope'], 'county', (method, county['id'], 'geographic scope'))
        if method == 'total':
            sample = next(c for c in state['counties'] if c['id'] == 'harris')['days'][source.observed - 1]
            native = source.source('harris', sample['date_2026'])
            expected = source.controls['harris', sample['date_2026']]['cumulative'] + native['mail']
            eq(sample['cumulative_2026'], expected, 'Harris full-county control + mail')
            assert expected != native['cumulative'] + native['mail'], 'Must exercise an actually underfilled SOS report'
            passed('Combined API uses full county controls plus mail, independently of precinct matching', harris=sample)
    # Every method, classifier and date uses its own largest matching membership.
    for method in ('total', 'mail'):
        for metric in [None] + source.reference['metrics']:
            classification = 'demographic' if metric else 'partisan'
            name = metric['id'] if metric else 'presidential_margin'
            view = get('/api/county-buckets', {'day': source.observed, 'method': method, 'view': classification, 'metric': name})
            eq(view['voting_method'], method, (method, name, 'view method'))
            buckets = [source.bucket(c['id'], metric) for c in view['counties']]
            for index, bucket in enumerate(view['buckets'] + [view['totals']]):
                for point in bucket['days']:
                    day = point['day']
                    for measure, membership in [('daily', 'county_ids'), ('cumulative', 'cumulative_county_ids')]:
                        target = [c['id'] for c, band in zip(view['counties'], buckets)
                                  if band is not None and (index == len(view['buckets']) or band == index)]
                        matched = [county for county in target if source.value(county, day, 2024, method, measure) is not None
                                   and (day > source.observed or source.value(county, day, 2026, method, measure) is not None)]
                        eq(point[membership], matched, (method, name, index, day, measure, 'membership'))
                        for year in (2024, 2026):
                            expected = (sum(source.value(c, day, year, method, measure) for c in matched)
                                        if matched and (year == 2024 or day <= source.observed) else None)
                            eq(point[f'{measure}_{year}'], expected, (method, name, index, day, year, measure))
                            COUNTS['texas_bucket_cells'] += 1
            COUNTS['texas_bucket_views'] += 1
    negatives = []
    for county in source.names.values():
        for day in range(1, source.observed + 1):
            for year in (2024, 2026):
                stamp = dt.date(year, 10, 21 if year == 2024 else 19) + dt.timedelta(days=day - 1)
                a = source.source(county, stamp.isoformat())
                b = source.source(county, (stamp - dt.timedelta(days=1)).isoformat())
                if a and b and a['mail'] < b['mail']:
                    eq(source.value(county, day, year, 'mail', 'daily'), None, 'downward revision is not zero')
                    eq(source.value(county, day, year, 'mail', 'cumulative'), a['mail'], 'cumulative survives daily revision')
                    negatives.append({'county': county, 'year': year, 'day': day, 'before': b['mail'], 'after': a['mail']})
    assert negatives, 'Real downward revisions must be exercised'
    passed('County buckets match source sums and per-observation memberships; future 2024 benchmarks remain', views=COUNTS['texas_bucket_views'], negative_deltas=negatives)


def interstate_api():
    # Reuse the existing independent normalized-source harness, not Rust analyzers.
    from multistate_api import Sources, Check, check_series, combine

    class Components(Sources):
        @lru_cache(maxsize=None)
        def value(self, year, date, county, method, measure):
            if method != 'total':
                return super().value(year, date, county, method, measure)
            if year == 2026 and date > self.data['through']:
                return None
            early = super().value(year, date, county, 'in_person', measure)
            mail = super().value(year, date, county, 'mail', measure)
            start = self.data['start_dates'][str(year)]
            closing = dt.date(2026, 10, 31 if self.data['id'] in ('nc', 'va') else 30)
            if year == 2024:
                closing += dt.date(2024, 11, 5) - dt.date(2026, 11, 3)
            if early is None and mail is not None:
                zeros = {d: {k: 0 for k in groups} for d, groups in mail[1].items()}
                if date < start or (date > closing.isoformat() and measure == 'daily'):
                    early = 0, zeros
                elif date > closing.isoformat():
                    early = super().value(year, closing.isoformat(), county, 'in_person', 'cumulative')
            if early is None or mail is None:
                return None
            return early[0] + mail[0], combine(early[1], mail[1])

    checks = Check()
    virginia_extras = 0
    for state in ('ga', 'nc', 'va', 'nv'):
        source = Components(state)
        for method in ('total', 'mail', 'in_person'):
            view = get(f'/api/states/{state}', {'method': method, 'classification': 'partisan'})
            eq(view['method'], method, (state, 'selected method'))
            check_series(checks, source, view['series'], source.counties, method, f'{state}/{method}/all')
            for county in view['counties']:
                check_series(checks, source, county['series'], [county['id']], method, f"{state}/{method}/{county['id']}")
            if state == 'va' and method == 'total':
                for key, native in source.exact.items():
                    year, date, county, kind, measure = key
                    if kind == 'total':
                        components = source.value(year, date, county, kind, measure)
                        virginia_extras += int(components is not None and native[0] != components[0])
            COUNTS['interstate_views'] += 1
    assert not checks.failures, checks.failures[:10]
    assert virginia_extras > 0, 'Virginia must exercise actual COUNTABLE totals exceeding mail + in person'
    REPORT['interstate_source_checks'] = dict(checks.checks)
    passed('All four state APIs use matching method components; Virginia COUNTABLE extras excluded', views=COUNTS['interstate_views'], virginia_noncomponent_totals=virginia_extras)


def browser_audit():
    from PIL import Image
    from playwright.sync_api import sync_playwright, expect

    def download(page, selector, filename):
        with page.expect_download(timeout=60000) as result:
            page.locator(selector).click()
        path = OUT / filename
        result.value.save_as(str(path))
        return path

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path='/usr/bin/chromium')
        page = browser.new_page(viewport={'width': 1512, 'height': 1050}, reduced_motion='reduce')
        page.add_init_script('''
          window.__mailTimers=[]; window.__mailText=[];
          const interval=window.setInterval;
          window.setInterval=function(fn,delay,...args){window.__mailTimers.push({delay,source:String(fn),stack:new Error().stack});return interval(fn,delay,...args);};
          const fill=CanvasRenderingContext2D.prototype.fillText;
          CanvasRenderingContext2D.prototype.fillText=function(text,...args){window.__mailText.push(String(text));return fill.call(this,text,...args);};
        ''')
        page.on('pageerror', lambda error: REPORT['javascript_errors'].append(str(error)))
        publication_requests, manifest_requests, server_requests = [], [], []
        def requests(request):
            if '/publication.json' in request.url:
                publication_requests.append(request.url)
            elif '/api-manifest.json' in request.url:
                manifest_requests.append(request.url)
            elif '/api/' in request.url:
                server_requests.append(request.url)
        page.on('request', requests)
        page.goto(BASE, wait_until='networkidle')
        page.wait_for_function('CountyView.ready()&&Tracking.stateReady()&&!CountyView.pending', timeout=120000)
        page.locator('[data-panels="expand"]').click()
        expect(page.locator('#county-method')).to_have_value('total')
        eq(page.evaluate('Tracking.state.voting_method'), 'total', 'headline default combined')
        timers = page.evaluate('window.__mailTimers.filter(t=>/app\\.js|states\\.js/.test(t.stack))')
        assert len(timers) >= 2, timers
        assert all(t['delay'] == 3600000 for t in timers), timers
        passed('Automatic browser source checks use hourly timers, with no minute or five-second interval', timers=timers)

        for classification in ('partisan', 'demographic'):
            page.locator('#county-' + classification).click()
            if classification == 'demographic':
                page.locator('#county-metric').select_option('non_white_vap')
            for method, label in [('total', 'Mail + in person'), ('in_person', 'In person'), ('mail', 'Mail')]:
                page.locator('#county-method').select_option(method)
                page.wait_for_function('(m)=>CountyView.ready()&&!CountyView.pending&&CountyView.view.voting_method===m&&Tracking.stateReady()&&Tracking.state.voting_method===m', arg=method, timeout=120000)
                desc = page.evaluate('Visuals.descriptor("county-daily")')
                assert label in desc['scope'], desc
                assert method != 'total' or 'mail + in person' in desc['source'].lower(), desc
                path = download(page, '#county-bucket-download', f'texas-{classification}-{method}.csv')
                rows = list(csv.DictReader(io.StringIO(path.read_text())))
                assert rows and all(r['method'] == method for r in rows)
                assert any(r['daily_2026'] == '' and r['daily_2024'] != '' for r in rows if int(r['day']) > page.evaluate('data.days'))
                page.evaluate('window.__mailText=[]')
                path = download(page, '[data-image="county-daily"]', f'texas-{classification}-{method}.png')
                with Image.open(path) as image:
                    eq(image.size, (1600, 1000), path.name + '/dimensions')
                    eq(image.format, 'PNG', path.name + '/format')
                text = page.evaluate('window.__mailText')
                assert any(label in line for line in text), (path.name, text)
                REPORT['images'].append(str(path.relative_to(ROOT)))
                COUNTS['png_exports'] += 1
                COUNTS['csv_exports'] += 1
        passed('Both county classifications switch all three methods with matching CSV and actual PNG captions', csvs=COUNTS['csv_exports'], pngs=COUNTS['png_exports'])

        # Deliver a slower old method after the newer selection has completed.
        payloads = {m: page.evaluate('async m=>{const r=await fetch("/api/county-buckets?"+new URLSearchParams({view:"demographic",metric:"non_white_vap",day,method:m}));return r.json();}', m) for m in ('mail', 'total')}
        page.locator('#county-method').select_option('in_person')
        page.wait_for_function('CountyView.ready()&&!CountyView.pending&&CountyView.votingMethod==="in_person"')
        page.evaluate('''()=>{
            window.__mailRealFetch=window.fetch.bind(window);window.__mailHeld=[];
            window.fetch=(input,init)=>{
                const u=new URL(typeof input==='string'?input:input.url,location.href);
                if(u.pathname.endsWith('/api/county-buckets'))return new Promise(resolve=>window.__mailHeld.push({url:u.href,resolve}));
                return window.__mailRealFetch(input,init);
            };
        }''')
        page.locator('#county-method').select_option('mail')
        page.wait_for_function('CountyView.pending&&!CountyView.view')
        expect(page.locator('[data-image="county-daily"]')).to_be_disabled()
        assert page.locator('#county-bucket-download').get_attribute('href') is None
        page.locator('#county-method').select_option('total')
        page.wait_for_function('CountyView.pending.includes("|total")')
        page.wait_for_function('window.__mailHeld.length===2')
        page.evaluate('''payloads=>{
            for(const held of window.__mailHeld.reverse()){
                const method=new URL(held.url).searchParams.get('method');
                held.resolve(new Response(JSON.stringify(payloads[method]),{headers:{'Content-Type':'application/json'}}));
            }
            window.fetch=window.__mailRealFetch;
        }''', payloads)
        page.wait_for_function('CountyView.ready()&&!CountyView.pending&&CountyView.view.voting_method==="total"&&Tracking.state.voting_method==="total"')
        expect(page.locator('#county-method')).to_have_value('total')
        passed('Rapid method changes reject delayed older responses and disable stale exports')

        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(OUT / 'texas-combined-desktop.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        page.wait_for_timeout(250)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.screenshot(path=str(OUT / 'texas-combined-mobile.png'), full_page=True)
        page.set_viewport_size({'width': 1512, 'height': 1050})

        page.locator('#precincts-tab').click()
        expect(page.locator('#precinct-method-label')).to_have_text('In person')
        page.locator('#counties-tab').click()
        passed('Precinct workspace explicitly retains its validated in-person scope')

        for state in ('ga', 'nc', 'va', 'nv'):
            page.locator('#state-select').select_option(state)
            page.wait_for_function('(s)=>States.view?.id===s&&!States.busy', arg=state, timeout=120000)
            for method in ('total', 'in_person', 'mail'):
                page.locator('#state-method').select_option(method)
                page.wait_for_function('(m)=>!States.busy&&States.view?.method===m', arg=method, timeout=120000)
                eq(page.evaluate('States.method'), method, (state, method, 'visible state method'))
                path = download(page, '[data-state-csv="turnout"]', f'{state}-{method}.csv')
                rows = list(csv.DictReader(io.StringIO(path.read_text())))
                assert rows and all(row['method'] == method for row in rows)
                assert all(row['cumulative_2026'] == '' for row in rows if row['future'] == 'true')
                COUNTS['csv_exports'] += 1
            page.locator('#state-method').select_option('total')
            page.wait_for_function('!States.busy&&States.view.method==="total"', timeout=120000)
            if page.locator('#state-panel-precincts').is_visible():
                page.wait_for_function('States.precinctView?.method==="total"&&!document.querySelector("#state-precinct-count").textContent.includes("Loading")', timeout=120000)
            if state in ('ga', 'va'):
                page.evaluate('window.__mailText=[]')
                path = download(page, '[data-state-image="turnout"]', f'{state}-combined-turnout.png')
                with Image.open(path) as image:
                    eq(image.size, (1600, 1000), path.name + '/dimensions')
                texts = page.evaluate('window.__mailText')
                assert any('Mail + in person' in line for line in texts), (path.name, texts)
                REPORT['images'].append(str(path.relative_to(ROOT)))
                COUNTS['png_exports'] += 1
            page.screenshot(path=str(OUT / f'{state}-combined-desktop.png'), full_page=True)
            page.set_viewport_size({'width': 390, 'height': 844})
            page.wait_for_timeout(200)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'), state
            page.screenshot(path=str(OUT / f'{state}-combined-mobile.png'), full_page=True)
            page.set_viewport_size({'width': 1512, 'height': 1050})
        passed('All added states switch methods with scoped CSVs and combined PNG captions; desktop/mobile fit')
        page.locator('#state-select').select_option('tx')
        page.wait_for_function('States.id==="tx"&&CountyView.ready()&&Tracking.stateReady()')

        if page.locator('script[src*="pages-api.js"]').count():
            before = (len(publication_requests), len(manifest_requests))
            selected = page.evaluate('({method:CountyView.votingMethod,mode:CountyView.mode,day})')
            page.locator('#refresh').click()
            expect(page.locator('#refresh')).to_have_text('Check updates')
            expect(page.locator('#refresh')).to_be_enabled()
            page.wait_for_function('CountyView.ready()&&Tracking.stateReady()&&!CountyView.pending')
            eq(len(publication_requests), before[0] + 1, 'Pages manual publication check')
            eq(len(manifest_requests), before[1], 'unchanged revision reuses Pages manifest')
            eq(page.evaluate('({method:CountyView.votingMethod,mode:CountyView.mode,day})'), selected, 'Pages retained selection')
            now = (len(publication_requests), len(manifest_requests))
            page.evaluate('''async()=>{
                window.__mailRealNow=Date.now;window.__mailClock=0;
                Date.now=()=>window.__mailRealNow()+window.__mailClock;
                for(let i=0;i<20;i++)await fetch('/api/status');
                window.__mailClock=1800000;await fetch('/api/status');
            }''')
            eq((len(publication_requests), len(manifest_requests)), now, 'no repeated or half-hour publication fetch')
            page.evaluate('async()=>{window.__mailClock=3601000;await fetch("/api/status");Date.now=window.__mailRealNow;}')
            eq(len(publication_requests), now[0] + 1, 'Pages hourly cache expiry requests publication')
            eq(len(manifest_requests), now[1], 'Pages hourly unchanged revision reuses manifest')
            eq(server_requests, [], 'Pages performs no backend API requests')
            passed('Pages manual update checks the revision and preserves selections; publication TTL is hourly', publication_checks=len(publication_requests), manifest_fetches=len(manifest_requests))
        else:
            # Local manual refresh alone may poll completion at five seconds.
            # Mock it so QA never starts an extra official scrape.
            statuses = {'requests': 0}
            generation = page.evaluate('data.generated_at')
            page.route('**/api/refresh', lambda route: route.fulfill(content_type='application/json', body='{}'))
            def status(route):
                statuses['requests'] += 1
                route.fulfill(content_type='application/json', body=json.dumps({'updating': statuses['requests'] == 1, 'generated_at': generation}))
            page.route('**/api/status', status)
            page.locator('#refresh').click()
            expect(page.locator('#refresh')).to_be_disabled()
            page.wait_for_function('!document.querySelector("#refresh").disabled', timeout=15000)
            eq(statuses['requests'], 2, 'manual refresh completion polls')
            passed('Explicit local refresh polls until completion without initiating an actual QA scrape')
        assert not REPORT['javascript_errors'], REPORT['javascript_errors']
        browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-only', action='store_true')
    parser.add_argument('--browser-only', action='store_true')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        if not args.browser_only:
            texas_api(TexasSources())
            interstate_api()
        if not args.api_only:
            browser_audit()
        REPORT['passed'] = True
    except BaseException:
        REPORT['passed'] = False
        REPORT['failure'] = traceback.format_exc()
        raise
    finally:
        REPORT['counts'] = dict(COUNTS)
        tag = 'api' if args.api_only else 'browser' if args.browser_only else 'full'
        path = OUT / f'{tag}-verification.json'
        path.write_text(json.dumps(REPORT, indent=2) + '\n')


if __name__ == '__main__':
    main()
