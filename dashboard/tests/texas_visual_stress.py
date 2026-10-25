#!/usr/bin/env python3
"""Adversarial Texas display checks, including independent source cutoffs.

TURNOUT_TEST_URL=http://127.0.0.1:8743 uv run --with playwright --with pillow \
  python dashboard/tests/texas_visual_stress.py
Set TURNOUT_TEST_LOCAL_ASSETS=1 to test current frontend over immutable Pages data.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import math
import os
from pathlib import Path
import traceback
from urllib.parse import urlparse

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
BASE = os.environ.get('TURNOUT_TEST_URL', 'http://127.0.0.1:8743').rstrip('/')
TAG = os.environ.get('TURNOUT_TEST_TAG', 'local')
OUT = ROOT / 'analysis/texas-stress'
OUT.mkdir(parents=True, exist_ok=True)
REPORT = {'url': BASE, 'local_assets': os.environ.get('TURNOUT_TEST_LOCAL_ASSETS') == '1', 'checks': [], 'javascript_errors': []}


def passed(name, **facts):
    REPORT['checks'].append({'name': name, **facts})
    print(name, flush=True)


def qualified(row, observed, measure, state=False):
    prefix = ('votes' if state else 'daily') if measure == 'daily' else 'cumulative'
    a, b = row.get(prefix + '_2024'), row.get(prefix + '_2026')
    if row['day'] <= observed and (a is None or b is None):
        return None, None
    return a, b if row['day'] <= observed else None


def verify_timeline(actual, rows, observed, measure, state=False):
    expected = []
    for row in rows:
        a, b = qualified(row, observed, measure, state)
        for year, value in ((2024, a), (2026, b)):
            if value is not None:
                expected.append((row['day'], year, value))
    dots = actual['dots']
    assert [(d['day'], d['year']) for d in dots] == [(d, y) for d, y, _ in expected]
    # Derive the scale independently, then check every rendered point position.
    maximum = max([1] + [v for _, _, v in expected])
    rough = maximum / 3
    power = 10 ** math.floor(math.log10(rough))
    step = next(v * power for v in (1, 2, 2.5, 5, 10) if v * power >= rough)
    top = math.ceil(maximum / step) * step
    large = actual['width'] == 640
    left, width, height = (58, 640, 300) if large else (45, 440, 206)
    pw, ph = width - left - 16, height - 16 - 33
    for dot, (day, year, value) in zip(dots, expected):
        assert math.isclose(dot['x'], left + (day - 1) * pw / 11, abs_tol=1e-7)
        assert math.isclose(dot['y'], 16 + ph - value / top * ph, abs_tol=1e-7), (dot, value, top)
    return len(dots)


SNAPSHOT = """selector=>[...document.querySelectorAll(selector)].map(svg=>({width:svg.viewBox.baseVal.width,dots:[...svg.querySelectorAll('.timeline-dot')].map(dot=>({day:+dot.dataset.day,year:+dot.dataset.year,x:+dot.getAttribute('cx'),y:+dot.getAttribute('cy')}))}))"""


def csv_rows(page, selector):
    text = page.locator(selector).evaluate('async e=>await(await fetch(e.href)).text()')
    return list(csv.DictReader(io.StringIO(text)))


def check_counties(page):
    checks, points = 0, 0
    selected = page.evaluate('day')
    for mode in ('partisan', 'demographic'):
        page.locator('#county-' + mode).click()
        if mode == 'demographic':
            page.locator('#county-metric').select_option('non_white_vap')
        for method in ('total', 'in_person', 'mail'):
            page.locator('#county-method').select_option(method)
            page.wait_for_function("e=>CountyView.ready()&&Tracking.stateReady()&&CountyView.votingMethod===e.method&&CountyView.mode===e.mode", arg={'method': method, 'mode': mode}, timeout=180000)
            payload = page.evaluate('CountyView.view')
            panels = payload['buckets'] + ([payload['totals']] if len(payload['buckets']) == 5 else [])
            for measure in ('daily', 'cumulative'):
                page.locator('#county-bucket-measure').select_option(measure)
                actual = page.evaluate(SNAPSHOT, '#county-daily-charts svg')
                assert len(actual) == len(panels)
                for svg, bucket in zip(actual, panels):
                    points += verify_timeline(svg, bucket['days'], payload['observed_days'], measure)
                checks += 1
            rows = csv_rows(page, '#county-bucket-download')
            assert len(rows) == sum(len(p['days']) for p in panels)
            for actual, expected in zip(rows, (d for p in panels for d in p['days'])):
                for measure in ('daily', 'cumulative'):
                    for year, value in zip((2024, 2026), qualified(expected, payload['observed_days'], measure)):
                        assert actual[f'{measure}_{year}'] == ('' if value is None else str(value))
                assert actual['method'] == method
            summaries = page.locator('#county-bucket-summary .county-summary-bucket').all()
            for actual, bucket in zip(summaries, payload['buckets']):
                row = next(d for d in bucket['days'] if d['day'] == selected)
                old, new = qualified(row, payload['observed_days'], 'cumulative')
                text = actual.inner_text()
                for value in (old, new):
                    assert ('—' if value is None else f'{value:,}') in text
                ratio = f'{100 * new / old:.1f}%' if old and new is not None else '—'
                assert ratio in text
    passed('County chart coordinates, all daily/cumulative source values, CSV and summary totals', combinations=checks, plotted_points=points)


def source_cutoffs(page):
    """Keep all publisher data intact; separate only the precinct snapshot cutoff."""
    result = page.evaluate("""()=>{
      const prior=data.days, observed=CountyView.view.observed_days;
      if(observed<2)throw Error('Need two observed county days');
      window.__stressOriginalDays=prior;window.__stressPeriods=data.counties.map(c=>c.periods);data.days=observed-1;data.counties.forEach(c=>c.periods=c.periods.filter(p=>p.day<=data.days));day=observed;render();CountyView.render();
      const county=Tracking.state.counties.find(c=>c.id==='harris'),raw=county.days.find(d=>d.day===day),shown=Tracking.stateRow(county);
      return {precinctDays:data.days,countyDays:observed,day,raw:[raw.cumulative_2024,raw.cumulative_2026],shown:[shown.old,shown.new],buttons:[...document.querySelectorAll('#days button')].map(b=>+b.dataset.day),countyDots:document.querySelectorAll('#county-daily-charts .timeline-dot[data-year="2026"][data-day="'+day+'"]').length,stateDots:document.querySelectorAll('#statewide-chart .timeline-dot[data-year="2026"][data-day="'+day+'"]').length};
    }""")
    assert result['raw'] == result['shown'], result
    assert result['countyDays'] in result['buttons'], result
    assert result['countyDots'] and result['stateDots'], result
    rows = csv_rows(page, '#statewide-download')
    harris = next(r for r in rows if r['county'] == 'Harris' and int(r['day']) == result['day'])
    assert [int(harris['cumulative_2024']), int(harris['cumulative_2026'])] == result['raw']
    # Historical future benchmarks must stay visible, without acquiring current zeros.
    page.evaluate('Tracking.stateMeasure="cumulative";Tracking.renderStateChart()')
    dot_days = page.locator('#statewide-chart .timeline-dot[data-year="2026"]').evaluate_all('els=>els.map(e=>+e.dataset.day)')
    assert max(dot_days) == result['countyDays']
    future = page.locator('#statewide-chart .timeline-dot[data-year="2024"]').evaluate_all('els=>els.map(e=>+e.dataset.day)')
    assert max(future) > result['countyDays']
    desc = page.evaluate('Visuals.descriptor("county-trend")')
    end_2026=dt.date(2026,10,19)+dt.timedelta(days=result['day']-1)
    end_2024=dt.date(2024,10,21)+dt.timedelta(days=result['day']-1)
    old_end=str(end_2024.day) if end_2024.month==10 else f'Nov {end_2024.day}'
    assert desc['period']==f'Oct 19–{end_2026.day}, 2026 / Oct 21–{old_end}, 2024'
    assert page.locator('#period').inner_text()==desc['period']
    page.screenshot(path=str(OUT / f'visual-{TAG}-county-cutoff.png'), full_page=True)
    # Navigating to precincts restores that source's shorter selectable cutoff.
    page.locator('#precincts-tab').click()
    page.wait_for_function('day<=data.days')
    assert max(page.locator('#days button').evaluate_all('els=>els.map(e=>+e.dataset.day)')) == result['precinctDays']
    page.evaluate('data.days=window.__stressOriginalDays;data.counties.forEach((c,i)=>c.periods=window.__stressPeriods[i]);day=data.days;updateView();Navigation.show("counties")')
    page.wait_for_function('CountyView.ready()&&Tracking.stateReady()', timeout=180000)
    passed('County source can advance independently: day controls, table, timeline, CSV and future benchmark', **result)



def precinct_trends(page):
    page.locator('#precincts-tab').click();page.locator('#precinct-trends-tab').click();page.locator('#county').select_option('all')
    points=0
    for mode_name in ('partisan','primary','demographic'):
        page.locator('#'+mode_name+'-mode').click()
        if mode_name=='demographic':
            page.locator('#metric').select_option('non_white_vap')
        page.wait_for_function("e=>Tracking.view&&Tracking.key===Tracking.signature()&&mode===e",arg=mode_name,timeout=180000)
        payload=page.evaluate('Tracking.view');observed=page.evaluate('data.days')
        panels=payload['buckets']+([payload['totals']] if len(payload['buckets'])==5 else [])
        for measure in ('daily','cumulative'):
            page.locator('#tracking-measure').select_option(measure)
            charts=page.evaluate(SNAPSHOT,'#daily-charts svg')
            assert len(charts)==len(panels)
            for actual,bucket in zip(charts,panels):
                points+=verify_timeline(actual,bucket['days'],observed,measure)
        rows=csv_rows(page,'#tracking-download')
        assert len(rows)==sum(len(p['days']) for p in panels)
        for actual,expected in zip(rows,(d for p in panels for d in p['days'])):
            for measure in ('daily','cumulative'):
                for year,value in zip((2024,2026),qualified(expected,observed,measure)):
                    assert actual[f'{measure}_{year}']==('' if value is None else str(value))
            assert actual['view']==mode_name
    passed('Precinct partisan, primary participation and demographic daily/cumulative chart coordinates and all CSV values',plotted_points=points)


def neutral_cohort(page):
    page.locator('#precincts-tab').click();page.locator('#precinct-explore-tab').click()
    page.locator('#county').select_option('tarrant');page.locator('#demographic-mode').click();page.locator('#metric').select_option('non_white_vap')
    page.wait_for_function("mode==='demographic'&&county==='tarrant'&&metricId==='non_white_vap'&&demoReady()",timeout=180000)
    # Unknown presidential returns must never acquire a winner from a 0/0 sum.
    page.evaluate("""()=>{const target=groupRows(data.counties.find(c=>c.id==='tarrant')).find(g=>g.votes_2024>0);window.__stressUnknown=target.group_index;const group=data.counties.find(c=>c.id==='tarrant').periods.find(p=>p.day===day).groups[target.group_index];window.__stressReturn={harris:group.harris,trump:group.trump};group.harris=0;group.trump=0;regressionWinner='all';regression();}""")
    target=page.evaluate("'tarrant:'+window.__stressUnknown")
    dot=page.locator(f'#regression-chart .regression-point[data-id="{target}"]')
    assert dot.count()==1 and dot.get_attribute('fill')=='#77818e'
    assert dot.get_attribute('data-harris-share')==''
    all_count=page.locator('#regression-chart .regression-point').count()
    for winner in ('trump','harris'):
        page.locator(f'[data-regression-winner="{winner}"]').click()
        assert page.locator(f'#regression-chart .regression-point[data-id="{target}"]').count()==0
        rows=csv_rows(page,'#regression-download')
        for row in rows:
            share=float(row['harris_share_2024_pct'])
            assert share<50 if winner=='trump' else share>50
    page.locator('[data-regression-winner="all"]').click()
    assert page.locator('#regression-chart .regression-point').count()==all_count
    # Every outlier remains in the fit and CSV even when clipped from the viewport.
    rows=csv_rows(page,'#regression-download')
    xy=[(float(r['non_white_vap_pct']),float(r['turnout_2026_as_pct_2024'])) for r in rows]
    mx=math.fsum(x for x,y in xy)/len(xy);my=math.fsum(y for x,y in xy)/len(xy)
    slope=math.fsum((x-mx)*(y-my) for x,y in xy)/math.fsum((x-mx)**2 for x,y in xy)
    fit=page.locator('#regression-chart .regression-fit')
    assert math.isclose(float(fit.get_attribute('data-slope')),slope,abs_tol=1e-9)
    page.locator('#regression-scale').select_option('focus')
    assert page.locator('#regression-chart .regression-point').count()==len(rows)
    assert math.isclose(float(page.locator('#regression-chart .regression-fit').get_attribute('data-slope')),slope,abs_tol=1e-9)
    assert any(float(r['turnout_2026_as_pct_2024'])<60 or float(r['turnout_2026_as_pct_2024'])>150 for r in rows)
    page.evaluate("""()=>{Object.assign(data.counties.find(c=>c.id==='tarrant').periods.find(p=>p.day===day).groups[window.__stressUnknown],window.__stressReturn);regression();}""")
    passed('Unknown presidential returns remain neutral and All-only; OLS retains clipped outliers', points=all_count)



def classification_race(page):
    page.locator('#counties-tab').click()
    page.wait_for_function('CountyView.ready()&&Tracking.stateReady()',timeout=180000)
    page.evaluate("""()=>{window.__stressFetch=window.fetch;window.__stressHeld=[];window.fetch=(input,init)=>{const url=new URL(typeof input==='string'?input:input.url,location.href);if(url.pathname.endsWith('/api/county-buckets'))return new Promise(resolve=>window.__stressHeld.push({input,init,resolve}));return window.__stressFetch(input,init);};CountyView.mode='partisan';CountyView.key='';CountyView.update();CountyView.mode='demographic';CountyView.metricId='black_vap';CountyView.update();CountyView.metricId='non_white_vap';CountyView.update();}""")
    page.wait_for_function('window.__stressHeld.length===3')
    page.evaluate('async()=>{const h=window.__stressHeld[2];h.resolve(await window.__stressFetch(h.input,h.init));}')
    page.wait_for_function('CountyView.ready()&&CountyView.metricId==="non_white_vap"&&Tracking.stateReady()',timeout=180000)
    latest=page.evaluate('CountyView.key')
    page.evaluate('async()=>{for(const h of window.__stressHeld.slice(0,2).reverse())h.resolve(await window.__stressFetch(h.input,h.init));window.fetch=window.__stressFetch;}')
    page.wait_for_timeout(300)
    assert page.evaluate('CountyView.key')==latest
    assert page.evaluate('CountyView.view.metric')=='non_white_vap'
    assert all(r['metric']=='non_white_vap' for r in csv_rows(page,'#county-bucket-download'))
    passed('Out-of-order partisan and demographic requests preserve latest metric, chart and CSV')


def actual_unknown_groups(page):
    page.locator('#precincts-tab').click();page.locator('#precinct-explore-tab').click()
    page.locator('#demographic-mode').click();page.locator('#metric').select_option('non_white_vap');page.locator('#county').select_option('all')
    page.wait_for_function("mode==='demographic'&&county==='all'&&metricId==='non_white_vap'&&demoReady()",timeout=180000)
    candidates=page.evaluate("""()=>data.counties.flatMap(c=>{const ref=referenceByCounty.get(c.id),p=c.periods.find(p=>p.day===day);return ref&&p?p.groups.flatMap((g,index)=>g.available!==false&&g.votes_2024>0&&g.old.some(id=>!Object.hasOwn(ref.presidential,id))?[{id:c.id+':'+index,harris:g.harris,trump:g.trump,county:c.name,precincts:g.new.join(';')}]:[]):[];})""")
    assert candidates,'Expected real groups with incomplete presidential returns'
    page.locator('[data-regression-winner="all"]').click()
    all_points={p['id']:p for p in page.locator('#regression-chart .regression-point').evaluate_all("els=>els.map(e=>({id:e.dataset.id,share:e.dataset.harrisShare,fill:e.getAttribute('fill')}))")}
    for group in candidates:
        assert group['harris']==group['trump']==0,group
        assert group['id'] in all_points,group
        assert all_points[group['id']]['share']=='' and all_points[group['id']]['fill']=='#77818e',group
    for winner in ('trump','harris'):
        page.locator(f'[data-regression-winner="{winner}"]').click()
        displayed=set(page.locator('#regression-chart .regression-point').evaluate_all('els=>els.map(e=>e.dataset.id)'))
        assert all(c['id'] not in displayed for c in candidates)
        exported={(r['county'],r['precincts_2026']) for r in csv_rows(page,'#regression-download')}
        assert all((c['county'],c['precincts']) not in exported for c in candidates)
    page.locator('[data-regression-winner="all"]').click()
    # Missing presidential returns must not prevent valid turnout/map exploration.
    chosen=candidates[0]
    page.locator(f'#regression-chart .regression-point[data-id="{chosen["id"]}"]').dispatch_event('click')
    county_id,index=chosen['id'].split(':')
    page.wait_for_function("e=>Atlas.county===e.county&&Atlas.active?.group_index===e.index&&Atlas.layer&&document.getElementById('map-loading').hidden",arg={'county':county_id,'index':int(index)},timeout=180000)
    assert page.locator('#selection-stats > div').nth(2).locator('dd').inner_text()=='—'
    page.screenshot(path=str(OUT/f'visual-{TAG}-unknown-map.png'),full_page=True)
    passed('Actual incomplete presidential groups remain neutral in All and absent from both winner charts/CSVs',groups=len(candidates),counties=len({c['county'] for c in candidates}),linked_map=chosen['id'])


def png_check(page):
    page.locator('#counties-tab').click();page.locator('#county-method').select_option('total')
    page.wait_for_function('CountyView.ready()&&Tracking.stateReady()&&CountyView.votingMethod==="total"',timeout=180000)
    page.evaluate("""()=>{window.__stressText=[];const fill=CanvasRenderingContext2D.prototype.fillText;CanvasRenderingContext2D.prototype.fillText=function(s,...args){window.__stressText.push(String(s));return fill.call(this,s,...args);};}""")
    with page.expect_download(timeout=60000) as event:
        page.locator('[data-image="county-summary"]').click()
    target=OUT/f'visual-{TAG}-combined.png';event.value.save_as(target)
    with Image.open(target) as image:
        assert image.size==(1600,1000)
    text=' '.join(page.evaluate('window.__stressText'))
    assert 'Mail + in person' in text
    passed('Actual combined-turnout PNG exports with explicit method', file=target.name, canvas_text=page.evaluate('window.__stressText'))


def main():
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
        page=browser.new_page(viewport={'width':1512,'height':1100},accept_downloads=True)
        page.on('pageerror',lambda e:REPORT['javascript_errors'].append(str(e)))
        if REPORT['local_assets']:
            def asset(route):
                name=Path(urlparse(route.request.url).path).name
                route.fulfill(path=str(ROOT/'dashboard/static'/name),content_type='application/javascript')
            for name in ('app.js','county-view.js','tracking.js','visuals.js','atlas.js','regression-cohort.js','regression-scale.js'):
                page.route('**/'+name,asset)
        try:
            page.goto(BASE+'/',wait_until='networkidle',timeout=180000)
            page.wait_for_function('data&&CountyView.ready()&&Tracking.stateReady()',timeout=180000)
            check_counties(page)
            source_cutoffs(page)
            precinct_trends(page)
            neutral_cohort(page)
            classification_race(page)
            actual_unknown_groups(page)
            png_check(page)
            page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(500)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(OUT/f'visual-{TAG}-mobile.png'),full_page=True)
            assert not REPORT['javascript_errors'],REPORT['javascript_errors']
            passed('390px display and zero JavaScript errors')
            REPORT['passed']=True
        finally:
            browser.close()


if __name__=='__main__':
    try:
        main()
    except Exception:
        REPORT['passed']=False;REPORT['failure']=traceback.format_exc();raise
    finally:
        (OUT/f'visual-{TAG}-verification.json').write_text(json.dumps(REPORT,indent=2)+'\n')
