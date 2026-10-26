"""Content-driven social framing: actual narrow/wide exports and plot integrity.

TURNOUT_TEST_URL=http://127.0.0.1:8743 uv run --with playwright --with pillow \
  python dashboard/tests/export_framing.py
TURNOUT_FRAMING_PREVIEW=1 overlays only the working visuals.js on a native server.
"""
from pathlib import Path
import json
import os
from PIL import Image
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
BASE = os.environ.get('TURNOUT_TEST_URL', 'http://127.0.0.1:8743').rstrip('/')
TAG = os.environ.get('TURNOUT_TEST_TAG', 'local')
OUT = ROOT / 'analysis/adaptive-framing' / TAG
OUT.mkdir(parents=True, exist_ok=True)
REPORT = {'url': BASE, 'images': [], 'errors': []}


def export(page, selector, name, narrow=False):
    expect(page.locator(selector)).to_be_enabled(timeout=120000)
    # Export changes presentation only: preserve every coordinate, fit, label,
    # clip, point, color and selected range in the displayed SVG.
    before = page.locator('#regression-chart svg, #state-scatter svg').evaluate_all(
        'nodes=>nodes.filter(n=>n.getBoundingClientRect().width).map(n=>n.outerHTML)')
    with page.expect_download(timeout=120000) as event:
        page.locator(selector).click()
    path = OUT / (name + '.png')
    event.value.save_as(path)
    layout = page.evaluate('Visuals.lastLayout')
    with Image.open(path) as image:
        size = image.size
        assert image.format == 'PNG' and image.width == 1600 and 800 <= image.height <= 2000
        assert image.convert('RGBA').getchannel('A').getextrema() == (255, 255)
        image.resize((390, round(390 * image.height / image.width))).save(OUT / (name + '-feed.png'))
    assert path.stat().st_size <= 5_000_000
    assert layout['footerTop'] + 86 == size[1], (size, layout)
    plot, capture = layout['plot'], layout['capture']
    assert capture['x'] >= plot['x'] and capture['y'] >= plot['y']
    assert capture['x'] + capture['width'] <= plot['x'] + plot['width'] + .1
    assert capture['y'] + capture['height'] <= plot['y'] + plot['height'] + .1
    assert capture['y'] + capture['height'] < layout['noteTop']
    source = page.evaluate('window.__framingSource')
    assert abs(capture['width'] / capture['height'] - source['width'] / source['height']) < 1e-8, 'Export stretched the chart'
    ratio = capture['width'] / plot['width']
    if narrow:
        assert ratio >= .94, f'{name}: chart fills only {ratio:.1%} of frame width; expected >=94%'
    if 800 < size[1] < 2000:
        assert ratio >= .94 and capture['height'] / plot['height'] >= .94, layout
    after = page.locator('#regression-chart svg, #state-scatter svg').evaluate_all(
        'nodes=>nodes.filter(n=>n.getBoundingClientRect().width).map(n=>n.outerHTML)')
    assert before == after, 'Export mutated the displayed chart'
    REPORT['images'].append({'file': path.name, 'size': size, 'bytes': path.stat().st_size,
                             'width_fill': ratio, 'layout': layout})
    print(name, size, f'{ratio:.1%} frame width', flush=True)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path='/usr/bin/chromium')
    page = browser.new_page(viewport={'width': 1512, 'height': 1080},
                            reduced_motion='reduce', accept_downloads=True)
    page.on('pageerror', lambda e: REPORT['errors'].append(str(e)))
    if os.environ.get('TURNOUT_FRAMING_PREVIEW') == '1':
        page.route('**/visuals.js', lambda route: route.fulfill(path=ROOT / 'dashboard/static/visuals.js',
                                                              content_type='text/javascript'))
    try:
        page.goto(BASE + '/#precinct-explore', wait_until='networkidle', timeout=180000)
        page.wait_for_function('data&&Tracking.view&&Atlas.layer&&Visuals', timeout=180000)
        page.evaluate("""() => {
          const compose=Visuals.compose;
          Visuals.compose=function(capture,desc){
            window.__framingSource={width:capture.width,height:capture.height};
            return compose.call(this,capture,desc);
          };
        }""")
        page.locator('#precincts-tab').click()
        page.locator('#precinct-explore-tab').click()
        page.locator('#county').select_option('all')
        page.wait_for_function('county==="all"&&Atlas.county==="all"&&document.getElementById("map-loading").hidden')
        export(page, '[data-image="regression"]', 'texas-partisan', narrow=True)
        page.locator('#demographic-mode').click()
        page.wait_for_function('demoReady()', timeout=180000)
        export(page, '[data-image="regression"]', 'texas-demographic', narrow=True)
        page.set_viewport_size({'width': 390, 'height': 1080})
        page.wait_for_timeout(100)
        export(page, '[data-image="regression"]', 'texas-mobile')
        page.set_viewport_size({'width': 1512, 'height': 1080})
        page.locator('#precinct-trends-tab').click()
        page.wait_for_function('Tracking.view&&Tracking.key===Tracking.signature()', timeout=180000)
        export(page, '[data-image="daily-0"]', 'texas-wide-timeline')
        export(page, '[data-image="matrix"]', 'texas-matrix')
        page.locator('#state-select').select_option('nc')
        page.wait_for_function('States.id==="nc"&&States.view?.id==="nc"&&!States.busy', timeout=180000)
        export(page, '[data-state-image="regression"]', 'nc-regression', narrow=True)
        assert not REPORT['errors'], REPORT['errors']
        REPORT['passed'] = True
    except BaseException:
        REPORT['passed'] = False
        page.screenshot(path=str(OUT / 'failure.png'), full_page=True)
        raise
    finally:
        (OUT / 'verification.json').write_text(json.dumps(REPORT, indent=2) + '\n')
        browser.close()
