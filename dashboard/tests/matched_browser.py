"""Per-day reported matched-precinct rendering, coverage, exports and races.

Run against the rebuilt offline QA service with TURNOUT_TEST_URL set.
"""
from pathlib import Path
import csv
import io
import json
import os
from urllib.request import urlopen
from PIL import Image
from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get('TURNOUT_TEST_URL', 'http://127.0.0.1:8743')
OUT = Path(__file__).resolve().parents[2] / 'analysis/matched-comparison/qa'
OUT.mkdir(parents=True, exist_ok=True)


def get(path):
    with urlopen(BASE + path, timeout=120) as response:
        return json.load(response)


def csv_download(page, selector, name):
    with page.expect_download(timeout=45000) as download:
        page.locator(selector).click()
    path = OUT / name
    download.value.save_as(str(path))
    return list(csv.DictReader(io.StringIO(path.read_text())))


def assert_pairs(rows, observed, label):
    for row in rows:
        for prefix in ['daily', 'cumulative']:
            a, b = row[prefix + '_2024'], row[prefix + '_2026']
            if int(row['day']) <= observed:
                assert (a == '') == (b == ''), (label, row)
            else:
                assert b == '', (label, 'future current value', row)


snapshot = get('/api/data')
observed = snapshot['days']
# Only observed reported intersections contribute. Stable unavailable indices
# carry placeholder zeros in the API and must never become plotted observations.
assert any('available' in g for c in snapshot['counties'] for p in c['periods'] for g in p['groups']), 'New matched-availability schema is required'
for county in snapshot['counties']:
    for period in county['periods']:
        matched = [g for g in period['groups'] if g.get('available', True)]
        assert period['county_2024'] == sum(g['votes_2024'] for g in matched), (county['id'], period['day'], '2024 scope')
        assert period['county_2026'] == sum(g['votes_2026'] for g in matched), (county['id'], period['day'], '2026 scope')
        if 'coverage' in period:
            assert period['coverage']['available_groups'] == len(matched)
            assert period['coverage']['available_precincts'] == sum(len(g['new']) for g in matched)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path='/usr/bin/chromium')
    page = browser.new_page(viewport={'width': 1512, 'height': 1050}, reduced_motion='reduce')
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(BASE, wait_until='networkidle')
    page.wait_for_function('Tracking.state&&Tracking.view&&CountyView.view&&Atlas.layer&&window.Visuals')
    page.locator('[data-panels="expand"]').click()

    # Every bucket and county CSV applies the same paired-observation mask.
    for view in ['partisan', 'demographic']:
        page.locator('#county-' + view).click()
        if view == 'demographic':
            page.locator('#county-metric').select_option('non_white_vap')
        page.wait_for_function('(v)=>CountyView.mode===v&&CountyView.key.includes("|"+v+"|")&&!CountyView.pending', arg=view)
        rows = csv_download(page, '#county-bucket-download', 'county-' + view + '.csv')
        assert_pairs(rows, observed, 'county ' + view)
        empty_charts = page.locator('#county-daily-charts svg').evaluate_all('(els)=>els.filter(svg=>!svg.querySelector(".timeline-dot")).map(svg=>svg.textContent)')
        assert all('No matched comparison' in text for text in empty_charts), empty_charts
        for measure in ['daily', 'cumulative']:
            page.locator('#county-bucket-measure').select_option(measure)
            assert page.evaluate('''()=>[...document.querySelectorAll('#county-daily-charts svg')].every(svg=>{
                const a=[...svg.querySelectorAll('[data-year="2024"]')].map(d=>+d.dataset.day).filter(d=>d<=data.days),
                b=[...svg.querySelectorAll('[data-year="2026"]')].map(d=>+d.dataset.day);return JSON.stringify(a)===JSON.stringify(b);
            })''')
    assert_pairs(csv_download(page, '#statewide-download', 'all-counties.csv'), observed, 'county table')

    # Delayed replacements must never expose a prior cutoff under a new label.
    delayed = []
    def hold(route):
        delayed.append(route)
    page.route('**/api/county-buckets?**', hold)
    page.get_by_role('button', name='Day 2', exact=True).click()
    page.wait_for_function('CountyView.pending&&!CountyView.view')
    expect(page.locator('#county-daily-charts')).to_contain_text('Loading matched comparisons')
    assert page.locator('#county-bucket-summary').inner_text() == ''
    for selector in ['#county-bucket-download', '#statewide-download']:
        assert page.locator(selector).get_attribute('href') is None
        expect(page.locator(selector)).to_have_attribute('aria-disabled', 'true')
    expect(page.locator('[data-image="county-daily"]')).to_be_disabled()
    expect(page.locator('[data-image="county-trend"]')).to_be_disabled()
    assert page.evaluate('''()=>{try{Visuals.descriptor('county-daily');return false;}catch(e){return e.message.includes('loading');}}''')
    for route in delayed:
        route.continue_()
    page.unroute('**/api/county-buckets?**', hold)
    page.wait_for_function('CountyView.ready()&&!CountyView.pending')
    page.get_by_role('button', name=f'Day {observed}', exact=True).click()
    page.wait_for_function('CountyView.ready()&&!CountyView.pending')

    delayed = []
    page.route('**/api/trends?**', hold)
    page.locator('#precincts-tab').click()
    page.locator('#precinct-trends-tab').click()
    page.locator('#county').select_option('bexar')
    page.wait_for_function('Tracking.pending&&!Tracking.view')
    assert page.locator('#tracking-download').get_attribute('href') is None
    expect(page.locator('[data-image="daily"]')).to_be_disabled()
    assert page.evaluate('''()=>{try{Visuals.descriptor('daily');return false;}catch(e){return e.message.includes('loading');}}''')
    for route in delayed:
        route.continue_()
    page.unroute('**/api/trends?**', hold)
    page.wait_for_function('Tracking.view?.county==="bexar"&&!Tracking.pending')

    delayed = []
    page.route('**/api/demographic-view?**', hold)
    page.locator('#demographic-mode').click()
    page.wait_for_function('demoPending&&!demoReady()')
    for selector in ['#download', '#regression-download']:
        assert page.locator(selector).get_attribute('href') is None
    expect(page.locator('[data-image="regression"]')).to_be_disabled()
    for route in delayed:
        route.continue_()
    page.unroute('**/api/demographic-view?**', hold)
    page.wait_for_function('demoReady()&&!demoPending')

    # Partial counties remain useful. Every rendered regression observation has
    # the same reported geographic group in both years, in every classification.
    for county in ['tarrant', 'harris', 'bexar', 'fortbend']:
        record = next(c for c in snapshot['counties'] if c['id'] == county)
        latest = next(p for p in record['periods'] if p['day'] == observed)
        available = {i for i, g in enumerate(latest['groups']) if g.get('available', True)}
        page.locator('#precincts-tab').click()
        page.locator('#county').select_option(county)
        for view in ['partisan', 'demographic', 'primary']:
            page.locator('#' + view + '-mode').click()
            page.wait_for_function('(v)=>mode===v&&(v==="partisan"||demoReady())&&Tracking.view?.county===county&&!Tracking.pending', arg=view)
            page.locator('#precinct-trends-tab').click()
            rows = csv_download(page, '#tracking-download', county + '-' + view + '.csv')
            assert_pairs(rows, observed, county + ' ' + view)
            assert all('daily_groups' in row and 'cumulative_groups' in row for row in rows)
            page.locator('#precinct-explore-tab').click()
            plotted = page.locator('#regression-chart .regression-point').evaluate_all('(els)=>els.map(e=>+e.dataset.id.split(":")[1])')
            assert set(plotted) <= available, (county, view, 'unreported group plotted as zero')
            points = csv_download(page, '#regression-download', county + '-' + view + '-points.csv')
            assert len(points) == len(plotted)
            for row in points:
                assert any(g.get('available', True) and ';'.join(g['new']) == row['precincts_2026'] and g['votes_2024'] == int(row['votes_2024']) and g['votes_2026'] == int(row['votes_2026']) for g in latest['groups']), (county, view, row)
            if not available:
                expect(page.locator('#regression-chart .regression-point')).to_have_count(0)
                expect(page.locator('#detail-totals')).to_contain_text('No matched turnout')
                assert page.evaluate('Atlas.counts()===null')
            page.locator('#map-layer').select_option('turnout')
            assert page.evaluate('[...Atlas.layers.values()].every(l=>Atlas.group(l.feature.properties.county,l.feature.properties.group)?.available!==false||Atlas.featureValue(l.feature)===null)')
            page.locator('#map-layer').select_option('share')
            if county == 'tarrant' and view == 'partisan':
                assert len(available) > 100 and len(plotted) > 100, 'Tarrant reported precincts must remain available'
                with page.expect_download(timeout=45000) as download:
                    page.locator('[data-image="regression"]').click()
                image_path = OUT / 'tarrant-matched-regression.png'
                download.value.save_as(str(image_path))
                with Image.open(image_path) as image:
                    assert image.size == (1600, 1000) and image.format == 'PNG'
        page.locator('#demographic-mode').click()
        page.locator('#metric').select_option('non_white_vap')
        page.wait_for_function('demoReady()&&Tracking.view?.metric==="non_white_vap"&&!Tracking.pending')
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(OUT / (county + '-matched-view.png')), full_page=True)

    # Native Census inspection still works for a group without a reported pair.
    unsupported = next(((c, i, g) for c in snapshot['counties'] for p in c['periods'] if p['day'] == observed for i, g in enumerate(p['groups']) if g.get('available') is False), None)
    if unsupported:
        c, i, group = unsupported
        page.locator('#county').select_option(c['id'])
        page.locator('#demographic-mode').click()
        page.wait_for_function('demoReady()&&Atlas.county===county')
        page.evaluate('(args)=>selectPoint(args[0],args[1],args[2],false)', [c['id'], i, group['new'][0]])
        expect(page.locator('#selection-title')).to_contain_text('Precinct')
        expect(page.locator('#selection-stats dd').nth(0)).to_have_text('—')
        expect(page.locator('#selection-stats dd').nth(1)).to_have_text('—')
        assert page.locator(f'#turnout-trend circle[data-day="{observed}"]').count() == 0

    page.locator('#counties-tab').click()
    page.wait_for_function('CountyView.ready()&&!CountyView.pending')
    with page.expect_download(timeout=45000) as download:
        page.locator('[data-image="county-daily"]').click()
    real_png = OUT / 'qualified-county-buckets.png'
    download.value.save_as(str(real_png))
    with Image.open(real_png) as image:
        assert image.size == (1600, 1000) and image.format == 'PNG'

    # Deliberately asymmetric anonymous fixture proves masking at the UI boundary.
    # A valid daily zero survives; valid cumulative-only points remain independent.
    page.locator('#counties-tab').click()
    fixture = page.evaluate('''()=>{
        const c=Tracking.state.counties.find(c=>c.id==='bexar');window.savedState=structuredClone(Tracking.state);
        for(const d of c.days){d.votes_2024=d.votes_2026=d.cumulative_2024=d.cumulative_2026=null;}
        Object.assign(c.days[0],{votes_2024:100,votes_2026:110,cumulative_2024:100,cumulative_2026:110});
        Object.assign(c.days[1],{votes_2024:200,votes_2026:null,cumulative_2024:300,cumulative_2026:null});
        Object.assign(c.days[2],{votes_2024:null,votes_2026:80,cumulative_2024:400,cumulative_2026:390});
        Object.assign(c.days[3],{votes_2024:0,votes_2026:0,cumulative_2024:400,cumulative_2026:390});
        Object.assign(c.days[4],{votes_2024:900000,votes_2026:null,cumulative_2024:900400,cumulative_2026:null,status_2026:'incomplete'});
        Object.assign(c.days[5],{votes_2024:300,cumulative_2024:900700});
        Tracking.stateCounty='bexar';Tracking.renderState();return {observed:data.days};
    }''')
    assert fixture['observed'] == 5, 'Update fixture when the completed election calendar changes'
    page.locator('#statewide-measure').select_option('daily')
    assert page.locator('#statewide-chart [data-year="2024"]').evaluate_all('(els)=>els.map(e=>+e.dataset.day)') == [1, 4, 6]
    assert page.locator('#statewide-chart [data-year="2026"]').evaluate_all('(els)=>els.map(e=>+e.dataset.day)') == [1, 4]
    expect(page.locator('#statewide-county-title')).to_contain_text('Bexar')
    page.locator('#statewide-search').fill('Bexar')
    cells = page.locator('#statewide-table tbody tr').inner_text()
    assert '900,400' not in cells and cells.count('—') >= 3, cells
    path = page.locator('#statewide-chart .year-2024').get_attribute('d')
    assert path.count('M') == 3, path  # No invented connecting line across day 2/3/5.
    page.locator('#statewide-measure').select_option('cumulative')
    assert page.locator('#statewide-chart [data-year="2024"]').evaluate_all('(els)=>els.map(e=>+e.dataset.day)') == [1, 3, 4, 6]
    rows = csv_download(page, '#statewide-download', 'asymmetric-counties.csv')
    assert_pairs(rows, observed, 'asymmetric fixture')
    bad = next(r for r in rows if r['county'] == 'Bexar' and r['day'] == '5')
    assert bad['daily_2024'] == bad['daily_2026'] == bad['cumulative_2024'] == bad['cumulative_2026'] == ''
    with page.expect_download(timeout=45000) as download:
        page.locator('[data-image="county-trend"]').click()
    png = OUT / 'incomplete-county.png'
    download.value.save_as(str(png))
    with Image.open(png) as image:
        assert image.size == (1600, 1000) and image.format == 'PNG'
    captured = page.evaluate('''async()=>{const c=await Visuals.capture(Visuals.descriptor('county-trend'));return decodeURIComponent(c.img.src.split(',').slice(1).join(','));}''')
    assert 'data-day="5"' not in captured and 'data-day="6"' in captured
    page.evaluate('Tracking.state=window.savedState;Tracking.renderState()')

    for width in [1512, 768, 390]:
        page.set_viewport_size({'width': width, 'height': 1000})
        page.wait_for_timeout(250)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), width
        page.screenshot(path=str(OUT / f'completed-{width}.png'))
    assert not errors, errors
    report = {'status': 'passed', 'generated_at': snapshot['generated_at'], 'observed_days': observed,
              'checks': ['Largest available reported precinct intersections retained independently by day', 'Paired county and precinct CSVs in all classifications',
                         'Unavailable placeholder zeros excluded from every plotted observation', 'Observed missing-day pairs hidden', 'Delayed requests cannot export stale cutoff, scope or classification',
                         'Independent daily/cumulative qualification', 'Census inspection retained for unreported groups', 'Confirmed zero retained', 'Future historical benchmark retained',
                         'No line across missing observations', 'PNG preserves missing-day gaps', 'Desktop/tablet/mobile layout'],
              'javascript_errors': errors}
    (OUT / 'matched-browser-verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    browser.close()
