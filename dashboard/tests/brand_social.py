"""Real branded PNGs and frozen, copyable social descriptions.

TURNOUT_TEST_URL=http://127.0.0.1:8743 TURNOUT_TEST_TAG=native \
  uv run --with playwright --with pillow python dashboard/tests/brand_social.py
Also runs directly against a Pages subpath; existing broader export suites retain
full branch/numerical coverage. Requires system Chromium and Tesseract.
"""
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import traceback

from PIL import Image
from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get('TURNOUT_TEST_URL', 'http://127.0.0.1:8743').rstrip('/') + '/'
TAG = os.environ.get('TURNOUT_TEST_TAG', 'local')
OUT = Path(__file__).resolve().parents[2] / 'analysis/brand-refresh/qa' / TAG
OUT.mkdir(parents=True, exist_ok=True)
REPORT = {'url': BASE, 'checks': [], 'images': [], 'javascript_errors': []}
X = '@electionsjack'
LINKEDIN = 'linkedin.com/in/jackson-hannan'

INSTRUMENT = r"""(() => {
 const text=CanvasRenderingContext2D.prototype.fillText;
 window.__brandText=[];
 CanvasRenderingContext2D.prototype.fillText=function(value,x,y,...rest){
  if(this.canvas.width===1600&&this.canvas.height>=800&&this.canvas.height<=2000){
   const m=this.measureText(String(value)),t=this.getTransform();
   window.__brandText.push({text:String(value),left:x-m.actualBoundingBoxLeft,
    right:x+m.actualBoundingBoxRight,top:y-m.actualBoundingBoxAscent,
    bottom:y+m.actualBoundingBoxDescent,canvasHeight:this.canvas.height,identity:t.a===1&&t.b===0&&t.c===0&&t.d===1});
  }
  return text.call(this,value,x,y,...rest);
 };
})();"""


def passed(name, **details):
    REPORT['checks'].append({'name': name, **details})
    print(name, flush=True)


def compact(value):
    return re.sub('[^a-z0-9]', '', value.lower())


def inspect_png(path, text_calls):
    assert path.stat().st_size < 5_000_000, (path, 'over platform organic image limit')
    with Image.open(path) as image:
        assert image.format == 'PNG' and (image.width == 1600 and 800 <= image.height <= 2000)
        assert image.convert('RGBA').getchannel('A').getextrema() == (255, 255)
        assert len(image.convert('RGB').getcolors(1_600_001)) > 30, 'blank image'
        image.resize((390, round(390 * image.height / image.width))).save(path.with_name(path.stem + '-feed.png'))
    ocr = subprocess.run(['tesseract', str(path), 'stdout'], capture_output=True,
                         text=True, check=True).stdout
    # Dense tables can confuse whole-page layout detection. Read the permanent
    # footer separately while retaining exact identity strings and pixel proof.
    with Image.open(path) as image:
        footer_path = path.with_name(path.stem + '-footer.png')
        image.crop((0, image.height - 86, image.width, image.height)).save(footer_path)
    footer = subprocess.run(['tesseract', str(footer_path), 'stdout', '--psm', '6'],
                            capture_output=True, text=True, check=True).stdout
    assert compact(X) in compact(footer), ('X attribution missing from pixels', footer)
    assert compact(LINKEDIN) in compact(footer), ('LinkedIn attribution missing from pixels', footer)
    joined = ' '.join(row['text'] for row in text_calls)
    assert X in joined and LINKEDIN in joined, joined
    for row in text_calls:
        if row['identity']:
            assert row['left'] >= -1 and row['right'] <= 1601, ('horizontal text clipping', row)
            assert row['top'] >= -1 and row['bottom'] <= row['canvasHeight'] + 1, ('vertical text clipping', row)
    return ocr


def install_compositor_spy(page):
    page.evaluate("""() => {
      if(window.__brandComposeInstalled)return;
      window.__brandComposeInstalled=true;window.__brandCompositions=[];
      const compose=Visuals.compose;
      Visuals.compose=async function(capture,desc){
        window.__brandCompositions.push(JSON.parse(JSON.stringify(desc)));
        return compose.call(this,capture,desc);
      };
    }""")


def export(page, selector, name, required=()):
    expect(page.locator(selector)).to_be_enabled(timeout=120000)
    page.evaluate('window.__brandText=[]')
    before = page.evaluate('window.__brandCompositions.length')
    with page.expect_download(timeout=120000) as event:
        page.locator(selector).click()
    path = OUT / (name + '.png')
    event.value.save_as(path)
    assert page.evaluate('window.__brandCompositions.length') == before + 1, 'shared compositor bypassed'
    rows = page.evaluate('window.__brandText')
    ocr = inspect_png(path, rows)
    share = page.evaluate('Visuals.lastShare')
    assert isinstance(share, dict) and share.get('caption') and share.get('alt'), share
    assert len(share['caption']) <= 280, ('Caption exceeds standard X limit', len(share['caption']))
    assert len(share['alt']) <= 1000, ('ALT exceeds X limit', len(share['alt']))
    assert X in share['caption'] and LINKEDIN in share['caption'], share
    assert 'https://www.linkedin.com/in/jackson-hannan' in share['caption'], share
    assert 'early-vote-dashboard' in share['caption'], share
    combined = ' '.join(row['text'] for row in rows) + ' ' + share['caption'] + ' ' + share['alt']
    for value in required:
        assert value.lower() in combined.lower(), (name, value, combined)
    for identity in ['#copy-image-caption', '#copy-image-alt']:
        expect(page.locator(identity)).to_be_visible()
        expect(page.locator(identity)).to_be_enabled()
        assert page.locator(identity).get_attribute('aria-label') or page.locator(identity).inner_text()
    REPORT['images'].append({'file': path.name, 'bytes': path.stat().st_size,
                             'filename': event.value.suggested_filename,
                             'canvas_text': rows, 'share': share, 'ocr': ocr})
    return share


def copy_checks(page, share):
    # Fulfilled and denied Clipboard API paths, without changing external clipboard.
    page.evaluate("""() => {
      window.__brandCopied=[];
      Object.defineProperty(navigator,'clipboard',{configurable:true,value:{
       writeText:async text=>{window.__brandCopied.push(text);}}});
    }""")
    for selector, field in [('#copy-image-caption', 'caption'), ('#copy-image-alt', 'alt')]:
        page.locator(selector).click()
        page.wait_for_function('window.__brandCopied.length>0')
        assert page.evaluate('window.__brandCopied.at(-1)') == share[field]
    page.evaluate("""() => {
      window.__brandFallback=[];
      Object.defineProperty(navigator,'clipboard',{configurable:true,value:{
       writeText:async()=>{throw Error('Clipboard denied for acceptance test');}}});
      const exec=document.execCommand.bind(document);
      document.execCommand=function(command,...args){
       if(command==='copy'){window.__brandFallback.push(document.activeElement?.value||getSelection().toString());return true;}
       return exec(command,...args);
      };
    }""")
    page.locator('#copy-image-alt').click()
    page.wait_for_function("""() => window.__brandFallback.length>0 ||
      [...document.querySelectorAll('textarea,input')].some(n=>n.value===Visuals.lastShare.alt&&n.getBoundingClientRect().width>0)""")
    fallback = page.evaluate("""() => window.__brandFallback.at(-1)||
      [...document.querySelectorAll('textarea,input')].find(n=>n.value===Visuals.lastShare.alt)?.value""")
    assert fallback == share['alt'], fallback
    passed('Caption and ALT controls copy frozen content; denied clipboard offers exact fallback')


def state_ready(page, state, classification=None):
    page.wait_for_function("""v=>window.States&&!States.busy&&States.id===v.state&&
      States.view?.id===v.state&&(!v.classification||States.classification===v.classification)""",
                           arg={'state': state, 'classification': classification}, timeout=180000)


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path='/usr/bin/chromium')
        context = browser.new_context(viewport={'width': 1512, 'height': 1100},
                                      accept_downloads=True, reduced_motion='reduce')
        context.add_init_script(INSTRUMENT)
        page = context.new_page()
        page.on('pageerror', lambda e: REPORT['javascript_errors'].append(str(e)))
        try:
            page.goto(BASE, wait_until='networkidle', timeout=180000)
            page.wait_for_function('data&&Tracking.view&&window.Visuals?.compose&&Atlas.layer', timeout=180000)
            expect(page.locator('#brand-x')).to_have_attribute('href', re.compile(r'^https://(?:www\.)?x\.com/electionsjack/?$'))
            expect(page.locator('#brand-linkedin')).to_have_attribute('href', re.compile(r'^https://www\.linkedin\.com/in/jackson-hannan/?$'))
            page.wait_for_function("document.getElementById('brand-portrait')?.complete&&document.getElementById('brand-portrait').naturalWidth>0")
            palette = page.evaluate("""() => [...document.querySelectorAll('body,header,header *,button')]
              .flatMap(n=>{const s=getComputedStyle(n);return [s.backgroundColor,s.color,s.borderTopColor];})""")
            assert 'rgb(219, 234, 242)' in palette, 'reference paper missing'
            assert 'rgb(116, 59, 66)' in palette, 'reference burgundy missing'
            assert 'Arial' in page.evaluate('getComputedStyle(document.body).fontFamily')
            social = page.evaluate('JSON.stringify(Visuals.social)')
            assert X in social and 'electionsjack' in social and LINKEDIN in social, social
            install_compositor_spy(page)
            passed('Measured Alabama palette, system typography, loaded portrait and genuine social links')

            page.locator('#precincts-tab').click()
            page.locator('#precinct-trends-tab').click()
            page.locator('#county').select_option('all')
            page.get_by_role('button', name='Day 3', exact=True).click()
            page.wait_for_function('day===3&&Tracking.view&&Tracking.key===Tracking.signature()')
            page.locator('#tracking-measure').select_option('daily')
            export(page, '[data-image="daily-0"]', 'texas-daily', ['Daily', '2024', '2026', 'Day 3', 'in-person'])

            # Freeze context before waiting for capture, as the existing contract requires.
            page.evaluate("""() => {window.__brandCapture=Visuals.capture;
              window.__brandCaptureGate=new Promise(r=>window.__brandRelease=r);
              Visuals.capture=async function(d){const value=await __brandCapture.call(this,d);
               window.__brandCaptureReady=true;await __brandCaptureGate;return value;};
            }""")
            with page.expect_download(timeout=120000) as event:
                page.locator('[data-image="daily-0"]').click()
                page.wait_for_function('window.__brandCaptureReady')
                page.get_by_role('button', name='Day 1', exact=True).click()
                page.evaluate('window.__brandRelease()')
            event.value.save_as(OUT / 'texas-frozen-day.png')
            inspect_png(OUT / 'texas-frozen-day.png', page.evaluate('window.__brandText'))
            frozen = page.evaluate('Visuals.lastShare')
            assert 'day-3' in event.value.suggested_filename
            assert 'Day 3' in frozen['caption'] + frozen['alt'], frozen
            page.evaluate('() => {Visuals.capture=window.__brandCapture;}')
            page.get_by_role('button', name='Day 3', exact=True).click()
            page.locator('#precinct-explore-tab').click()
            page.wait_for_function('Atlas.county==="all"&&document.getElementById("map-loading").hidden')
            page.locator('#map-layer').select_option('turnout')
            export(page, '[data-image="map"]', 'texas-map', ['Cumulative', '2024', 'matched precincts'])
            page.locator('#precinct-trends-tab').click()
            page.locator('[data-matrix-layout="joint"]').click()
            page.locator('#matrix-metric').select_option('hispanic_vap')
            page.wait_for_function('jointReady()&&jointViews.all?.metric.id==="hispanic_vap"', timeout=180000)
            export(page, '[data-image="matrix"]', 'texas-joint-matrix', ['Hispanic', '2024', 'in-person', 'unavailable'])
            page.locator('#counties-tab').click()
            page.locator('#county-method').select_option('total')
            page.wait_for_function('CountyView.ready()&&CountyView.votingMethod==="total"', timeout=180000)
            export(page, '[data-image="county-summary"]', 'texas-combined', ['Cumulative', 'Mail + in person', 'Through'])
            passed('Texas daily, cumulative, map, demographic matrix and combined-method cards retain scope and frozen dates')

            page.locator('#state-select').select_option('ga')
            state_ready(page, 'ga')
            page.locator('#state-classification').select_option('race')
            state_ready(page, 'ga', 'race')
            page.locator('#state-measure').select_option('daily')
            export(page, '[data-state-image="buckets"]', 'georgia-statewide', ['Georgia', 'statewide', 'voter race', 'daily'])
            page.locator('#state-select').select_option('nc')
            state_ready(page, 'nc')
            page.locator('#state-classification').select_option('demographic')
            state_ready(page, 'nc', 'demographic')
            page.locator('#state-measure').select_option('daily')
            export(page, '[data-state-image="regression"]', 'nc-regression', ['North Carolina', 'Cumulative', 'Unweighted OLS', 'Official'])
            share = export(page, '[data-state-image="table"]', 'nc-table', ['North Carolina', 'daily', 'First 12'])
            copy_checks(page, share)
            passed('Both export owners use the shared frame; Georgia voter groups and NC cumulative regression/daily table stay distinct')

            fixture = page.evaluate("""async()=>{
              window.__brandText=[];
              const source=document.createElement('canvas');source.width=1100;source.height=500;
              const ctx=source.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,1100,500);
              ctx.fillStyle='#285b91';ctx.fillRect(50,50,400,380);ctx.fillStyle='#a84236';ctx.fillRect(550,100,400,330);
              const desc={title:'Cumulative turnout across Hispanic precinct groups and presidential partisanship',
               scope:'All available Texas precinct counties, matched on the same geography in both years',
               classification:'Hispanic residents age 18+ · 2020 Census PL 94-171',cohortLabel:'Crosswalk matched precincts',
               period:'Oct 19–23, 2026 / Oct 21–25, 2024',day:5,mode:'demographic',key:'matrix',
               note:'Coverage changes by day. Unavailable reports are excluded from both years; missing observations are never counted as zero.',
               footer:'Cumulative in-person votes, not registered-voter turnout. Small cells have fewer than three groups or 100 baseline votes. Residents are not individual voters.',
               source:'Official county and Texas SOS in-person reports · 2020 Census PL 94-171 · 2024 presidential returns · documented geographic crosswalk'};
              const canvas=await Visuals.compose({img:source,width:1100,height:500},desc);
              return {url:canvas.toDataURL('image/png'),text:window.__brandText};
            }""")
            fixture_path = OUT / 'long-context.png'
            fixture_path.write_bytes(base64.b64decode(fixture['url'].split(',', 1)[1]))
            inspect_png(fixture_path, fixture['text'])
            joined = ' '.join(row['text'] for row in fixture['text'])
            for token in ['geographic crosswalk', 'never counted as zero', '100 baseline votes', '2024']:
                assert token in joined, ('long context lost', token, joined)
            passed('Long title, context, coverage and source wrap without clipped text in actual PNG')

            for width in [1512, 768, 390]:
                page.set_viewport_size({'width': width, 'height': 1100})
                page.evaluate('window.scrollTo(0,0)')
                page.wait_for_timeout(200)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'), width
                page.screenshot(path=str(OUT / f'nc-{width}.png'), full_page=True)
            page.locator('#state-select').select_option('tx')
            page.wait_for_function('States.id==="tx"&&document.getElementById("texas-dashboard").hidden===false')
            for width in [1512, 768, 390]:
                page.set_viewport_size({'width': width, 'height': 1100})
                page.evaluate('window.scrollTo(0,0)')
                page.wait_for_timeout(200)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'), width
                page.screenshot(path=str(OUT / f'texas-{width}.png'), full_page=True)
            denied = context.new_page()
            denied.on('pageerror', lambda e: REPORT['javascript_errors'].append(str(e)))
            denied.add_init_script("Object.defineProperty(window,'localStorage',{get(){throw Error('Storage denied')}})")
            denied.goto(BASE, wait_until='networkidle', timeout=180000)
            denied.wait_for_function('window.Visuals?.compose&&Tracking.view', timeout=180000)
            denied.locator('#precincts-tab').click()
            denied.locator('[data-panels="collapse"]').click()
            assert denied.locator('[data-collapsible].is-collapsed').count() > 0
            denied.locator('[data-panels="expand"]').click()
            assert denied.evaluate('matchMedia("(prefers-reduced-motion: reduce)").matches')
            denied.close()
            assert not REPORT['javascript_errors'], REPORT['javascript_errors']
            passed('1512/768/390 layouts fit; reduced-motion and denied-storage controls remain functional')
        except BaseException:
            page.screenshot(path=str(OUT / 'failure.png'), full_page=True)
            raise
        finally:
            browser.close()


if __name__ == '__main__':
    try:
        run()
        REPORT['passed'] = True
    except BaseException:
        REPORT['passed'] = False
        REPORT['failure'] = traceback.format_exc()
        raise
    finally:
        (OUT / 'verification.json').write_text(json.dumps(REPORT, indent=2) + '\n')
        print(json.dumps({'passed': REPORT.get('passed'), 'checks': len(REPORT['checks']),
                          'images': len(REPORT['images']), 'output': str(OUT)}), flush=True)
