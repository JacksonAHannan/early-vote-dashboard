"""Verify Rust fits independently and exercise regression controls in a real browser."""
import csv
import io
import json
import math
import os
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[2]
BASE=os.environ.get('TURNOUT_TEST_URL','http://127.0.0.1:8741')
OUT=ROOT/'analysis/updated-through-2026-10-22/qa'
OUT.mkdir(parents=True,exist_ok=True)
with urlopen(BASE+'/api/data') as r:data=json.load(r)

def points(county,day,cohort):
    result=[]
    for c in data['counties']:
        if county!='all' and c['id']!=county:continue
        period=next((p for p in c['periods'] if p['day']==day),None)
        if not period:continue
        for g in period['groups']:
            if not (g['unchanged'] if cohort=='unchanged' else g['bucket'] is not None):continue
            if g['votes_2024']<=0 or g['harris']+g['trump']<=0:continue
            result.append((100*g['harris']/(g['harris']+g['trump']),100*g['votes_2026']/g['votes_2024']))
    return result

for summary in data['regressions']:
    xy=points(summary['county'],summary['day'],summary['cohort'])
    assert len(xy)==summary['n']
    if len(xy)<2 or len({x for x,y in xy})<2:
        assert summary['fit'] is None
        continue
    # Independent centered covariance calculation, using compensated Python sums.
    mx=math.fsum(x for x,y in xy)/len(xy);my=math.fsum(y for x,y in xy)/len(xy)
    slope=math.fsum((x-mx)*(y-my) for x,y in xy)/math.fsum((x-mx)**2 for x,y in xy)
    intercept=my-slope*mx
    sst=math.fsum((y-my)**2 for x,y in xy)
    r2=1-math.fsum((y-intercept-slope*x)**2 for x,y in xy)/sst if sst else None
    fit=summary['fit']
    assert math.isclose(fit['slope'],slope,rel_tol=1e-10,abs_tol=1e-10)
    assert math.isclose(fit['intercept'],intercept,rel_tol=1e-10,abs_tol=1e-10)
    assert fit['r_squared'] is None if r2 is None else math.isclose(fit['r_squared'],r2,abs_tol=1e-10)
    assert fit['x_min']==min(x for x,y in xy) and fit['x_max']==max(x for x,y in xy)

with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
    page=browser.new_page(viewport={'width':1512,'height':1100});errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(BASE,wait_until='networkidle')
    expect(page.locator('#county-workspace')).to_be_visible()
    page.locator('#precincts-tab').click()
    expect(page.locator('#precinct-trends')).to_be_visible()
    page.locator('#precinct-explore-tab').click()
    expect(page.locator('#precinct-explore')).to_be_visible()
    expect(page.locator('#regression')).to_be_visible()
    initial=points('all',data['days'],'matched')
    expect(page.locator('.regression-point')).to_have_count(len(initial))
    expect(page.locator('.regression-fit')).to_have_count(1)
    assert 'Cumulative turnout (% of 2024)' in page.locator('#regression-chart').inner_text()
    assert '2024 Harris vote share (%)' in page.locator('#regression-chart').inner_text()
    assert max(float(v) for v in page.locator('.regression-point').evaluate_all('(els)=>els.map(e=>e.dataset.y)'))==max(y for x,y in initial)
    expect(page.locator('.regression-quadrant')).to_have_count(4)
    expect(page.locator('.regression-share-reference')).to_have_count(1)
    boundaries=page.locator('.regression-share-reference').evaluate('(el)=>[el.getAttribute("x1"),el.getAttribute("x2")]')
    assert boundaries[0]==boundaries[1]
    palette={'trump-above':'#a84236','trump-below':'#96641b','harris-above':'#285b91','harris-below':'#007f99'}
    rendered=page.locator('.regression-point').evaluate_all('(els)=>els.map(e=>({x:+e.dataset.x,y:+e.dataset.y,q:e.dataset.quadrant,color:e.getAttribute("fill")}))')
    for dot in rendered:
        expected=('harris' if dot['x']>=50 else 'trump')+('-above' if dot['y']>=100 else '-below')
        assert dot['q']==expected and dot['color']==palette[expected]
    assert set(dot['q'] for dot in rendered)==set(palette)
    svg=page.locator('#regression-chart svg')
    expect(svg).to_have_attribute('data-scale','auto')
    ymin=float(svg.get_attribute('data-y-min'));ymax=float(svg.get_attribute('data-y-max'))
    assert 0<=ymin<ymax and ymax<max(y for x,y in initial)
    outside=sum(y<ymin or y>ymax for x,y in initial)
    expect(page.locator('.regression-outside')).to_have_text(f'{outside:,} outside view')
    hidden=page.locator('.regression-point[aria-hidden="true"]')
    assert hidden.count()==outside and page.locator('.regression-point[aria-hidden="true"][tabindex="0"]').count()==0
    fit_before=page.locator('.regression-fit').get_attribute('data-slope')
    page.locator('#regression').screenshot(path=str(OUT/'regression-desktop.png'))
    page.locator('#regression-scale').select_option('full')
    expect(svg).to_have_attribute('data-y-min','0')
    assert float(svg.get_attribute('data-y-max'))>max(y for x,y in initial)
    expect(page.locator('.regression-point[aria-hidden="true"]')).to_have_count(0)
    assert page.locator('.regression-fit').get_attribute('data-slope')==fit_before
    page.locator('#regression-scale').select_option('focus')
    expect(svg).to_have_attribute('data-y-min','60')
    # Arrow navigation visits visible observations in the focused band.
    first=page.locator('.regression-point[tabindex="0"]');first.focus();first.press('ArrowRight')
    assert page.locator('.regression-point[aria-hidden="false"]:focus').count()==1
    page.locator('#county').select_option('travis')
    expect(page.locator('.regression-point')).to_have_count(len(points('travis',data['days'],'matched')))
    page.locator('#cohort').select_option('unchanged')
    expect(page.locator('.regression-point')).to_have_count(len(points('travis',data['days'],'unchanged')))
    page.get_by_role('button',name='Day 1',exact=True).click()
    expect(page.locator('.regression-point')).to_have_count(len(points('travis',1,'unchanged')))
    with page.expect_download() as info:page.locator('#regression-download').click()
    info.value.save_as(str(OUT/'regression-points.csv'))
    with (OUT/'regression-points.csv').open() as f:rows=list(csv.DictReader(f))
    assert len(rows)==len(points('travis',1,'unchanged')) and {r['county'] for r in rows}=={'Travis'}
    page.locator('#county').select_option('ellis')
    expect(page.locator('.regression-point')).to_have_count(0)
    expect(page.locator('#regression-chart')).to_contain_text('No comparable precinct groups')
    page.get_by_role('button',name=f"Day {data['days']}",exact=True).click()
    page.locator('#county').select_option('all');page.locator('#cohort').select_option('matched')
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    expect(page.locator('.regression-point')).to_have_count(len(initial))
    page.locator('#regression').screenshot(path=str(OUT/'regression-mobile.png'))
    assert not errors,errors
    browser.close()
report={'status':'passed','rust_fit_summaries_independently_verified':len(data['regressions']),'plotted_points':len(initial),'checks':['all point counts','OLS slope/intercept/R²','observed fit domain','outliers retained','automatic range, fixed60–150band and full-range toggle','hidden points excluded from keyboard navigation','OLS unchanged by scale','county/day/cohort selectors','empty earlier Ellis cutoff','points CSV','mobile overflow','desktop/mobile screenshots','four quadrant regions','50% and 100% dividers','all point quadrant colors'],'javascript_errors':errors}
(OUT/'regression-verification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
