"""Regression basis remains explicit when adjacent views switch to same-day turnout."""
import csv
import io
import json
import math
import os
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
BASE = os.environ.get('TURNOUT_TEST_URL', 'http://127.0.0.1:8743').rstrip('/')
OUT = ROOT / 'analysis/regression-basis' / os.environ.get('TURNOUT_TEST_TAG', 'native')
OUT.mkdir(parents=True, exist_ok=True)
REPORT = {'url': BASE, 'checks': [], 'errors': [], 'images': []}


def csv_rows(page, selector):
    with page.expect_download(timeout=60000) as event:
        page.locator(selector).click()
    assert 'cumulative' in event.value.suggested_filename
    rows = list(csv.DictReader(io.StringIO(event.value.path().read_text())))
    assert rows and all(row['measure'] == 'cumulative' for row in rows)
    for row in rows:
        old, new = float(row['votes_2024']), float(row['votes_2026'])
        ratio = float(row.get('turnout_2026_as_pct_2024', row.get('turnout_pct_2024')))
        assert old > 0 and math.isclose(ratio, 100 * new / old, rel_tol=1e-10)
    return rows


def png(page, selector, name):
    page.evaluate('window.__basisText=[]')
    with page.expect_download(timeout=120000) as event:
        page.locator(selector).click()
    path = OUT / (name + '.png')
    event.value.save_as(path)
    text = page.evaluate('window.__basisText')
    assert any('Cumulative turnout vs.' in item for item in text), text
    assert not any('Cumulative turnout vs. Cumulative' in item for item in text)
    with Image.open(path) as im:
        assert im.width == 1600 and 800 <= im.height <= 2400
        im.resize((800, round(im.height / 2))).save(OUT / (name + '-preview.png'))
    REPORT['images'].append({'name': name, 'canvas_text': text})


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/usr/bin/chromium', headless=True)
    page = browser.new_page(viewport={'width': 1512, 'height': 1100}, accept_downloads=True, reduced_motion='reduce')
    page.on('pageerror', lambda error: REPORT['errors'].append(str(error)))
    try:
        page.goto(BASE + '/#precinct-explore', wait_until='networkidle', timeout=180000)
        page.wait_for_function('data&&Visuals&&Atlas.layer', timeout=120000)
        expect(page.locator('#regression-title')).to_contain_text('Cumulative turnout vs.')
        page.evaluate('''()=>{const fill=CanvasRenderingContext2D.prototype.fillText;CanvasRenderingContext2D.prototype.fillText=function(text,...args){(window.__basisText||=[]).push(String(text));return fill.call(this,text,...args);};}''')
        page.locator('#county').select_option('dallas')
        for mode in ['partisan', 'demographic', 'primary', 'place']:
            page.locator('#' + mode + '-mode').click()
            if mode == 'demographic':
                page.locator('#metric').select_option('non_white_vap')
            page.wait_for_function("mode==='partisan'||demoReady()", timeout=120000)
            expect(page.locator('#regression-title')).to_contain_text('Cumulative turnout vs.')
            expect(page.locator('#regression-chart svg')).to_have_attribute('data-measure', 'cumulative')
            expect(page.locator('#regression-period')).to_have_text(page.evaluate('dates(comparisonPeriod())'))
            rows = csv_rows(page, '#regression-download')
            period = page.evaluate('comparisonPeriod()')
            assert all(row['start_2026'] == '2026-10-19' and row['start_2024'] == '2024-10-21'
                       and row['through_2026'] == period['through_2026'] and row['through_2024'] == period['through_2024'] for row in rows)
        REPORT['checks'].append('All four Texas classifications: cumulative heading, exact ranges, accessible chart basis and CSV measure/date/arithmetic')
        before = page.locator('#regression-chart .regression-point').evaluate_all('(els)=>els.map(e=>[e.dataset.id,e.dataset.y])')
        page.locator('#precinct-trends-tab').click()
        page.locator('#matrix-measure').select_option('daily')
        page.locator('#tracking-measure').select_option('daily')
        page.wait_for_function('matrixReady()', timeout=120000)
        expect(page.locator('#bucket-unit')).to_contain_text('Same-day')
        page.locator('#precinct-explore-tab').click()
        assert page.locator('#regression-chart .regression-point').evaluate_all('(els)=>els.map(e=>[e.dataset.id,e.dataset.y])') == before
        expect(page.locator('#regression-title')).to_contain_text('Cumulative turnout vs.')
        page.locator('#partisan-mode').click()
        page.get_by_role('button', name='Day 3', exact=True).click()
        expect(page.locator('#regression-period')).to_have_text('Oct 19–21, 2026 / Oct 21–23, 2024')
        png(page, '[data-image="regression"]', 'texas-cumulative')
        for width in [390, 768, 1512]:
            page.set_viewport_size({'width': width, 'height': 1100})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.locator('#regression').screenshot(path=str(OUT / f'texas-{width}.png'))
        REPORT['checks'].append('Same-day matrix/timeline controls preserve cumulative scatter values; changing day updates ranges; readable desktop/tablet/mobile and PNG')
        for state in ['ga', 'nc', 'va', 'nv']:
            page.locator('#state-select').select_option(state)
            page.wait_for_function('(id)=>States.id===id&&!States.busy&&!!States.view', arg=state, timeout=180000)
            page.locator('#state-classification').select_option('partisan')
            page.wait_for_function("!States.busy&&States.view.classification==='partisan'", timeout=180000)
            page.locator('#state-measure').select_option('daily')
            expect(page.locator('#state-panel-turnout h2')).to_contain_text('Same-day')
            expect(page.locator('#state-panel-regression h2')).to_contain_text('Cumulative turnout vs.')
            expect(page.locator('#state-scatter svg')).to_have_attribute('data-measure', 'cumulative')
            aligned = page.evaluate('States.view.series.find(p=>p.date_2026===States.date).date_2024')
            expect(page.locator('#state-regression-period')).to_have_text('Cumulative through ' + page.evaluate('States.date') + ' / ' + aligned)
            rows = csv_rows(page, '[data-state-csv="regression"]')
            assert all(row['date_2024'] == aligned for row in rows)
            assert 'cumulative' in page.locator('#state-scatter .state-dot').first.get_attribute('aria-label')
            if state == 'nc':
                png(page, '[data-state-image="regression"]', 'north-carolina-cumulative-under-daily')
                assert any(item.startswith('Through ') for item in REPORT['images'][-1]['canvas_text'])
        REPORT['checks'].append('Georgia, North Carolina, Virginia and Nevada: daily timelines retain truthful cumulative scatter headings, cutoffs, accessible points and CSVs; NC PNG says Through')
        assert not REPORT['errors'], REPORT['errors']
    finally:
        (OUT / 'verification.json').write_text(json.dumps(REPORT, indent=2) + '\n')
        browser.close()
print(json.dumps(REPORT, indent=2))
