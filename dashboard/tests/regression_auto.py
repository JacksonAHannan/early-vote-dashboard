"""Automatic viewport acceptance against a running offline dashboard.

TURNOUT_TEST_URL=http://127.0.0.1:8743 uv run --with playwright --with pillow \
    python dashboard/tests/regression_auto.py
"""
import csv
import io
import json
import os
import time
from pathlib import Path

from PIL import Image
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "analysis/regression-auto/qa"
OUT.mkdir(parents=True, exist_ok=True)
BASE = os.environ.get("TURNOUT_TEST_URL", "http://127.0.0.1:8743")
REPORT = {"base": BASE, "checks": [], "javascript_errors": []}


def record(name, **evidence):
    REPORT["checks"].append({"check": name, **evidence})
    print(name, evidence, flush=True)


def bounds(page, state=False):
    root = "#state-scatter" if state else "#regression-chart"
    selector = ".state-dot" if state else ".regression-point"
    data = page.locator(root).evaluate("""(root,selector)=>{
        const svg=root.querySelector('svg'),dots=[...root.querySelectorAll(selector)];
        return {min:+svg.dataset.yMin,max:+svg.dataset.yMax,mode:svg.dataset.scale,
            points:dots.map(d=>[+d.dataset.x,+d.dataset.y,d.getAttribute('fill')]),
            hidden:dots.filter(d=>d.getAttribute('aria-hidden')==='true').length,
            hidden_tabbable:dots.filter(d=>d.getAttribute('aria-hidden')==='true'&&d.tabIndex>=0).length,
            fit:root.querySelector('[data-slope]')?.getAttribute('data-slope')||null,
            negative_rects:[...root.querySelectorAll('rect')].filter(r=>+r.getAttribute('height')<0).length};
    }""", selector)
    assert 0 <= data["min"] < data["max"]
    assert data["hidden"] == sum(y < data["min"] or y > data["max"] for _, y, _ in data["points"])
    assert data["hidden_tabbable"] == data["negative_rects"] == 0
    return data


def png(page, selector, name):
    started=time.monotonic()
    with page.expect_download(timeout=60000) as event:
        page.locator(selector).click()
    path = OUT / (name + ".png")
    event.value.save_as(path)
    with Image.open(path) as image:
        assert (image.width == 1600 and 800 <= image.height <= 2000)
        assert image.convert("RGB").getextrema() != ((255, 255),) * 3
    record("actual regression PNG downloaded", image=name, seconds=round(time.monotonic()-started,2))


def csv_rows(page, selector):
    with page.expect_download(timeout=45000) as event:
        page.locator(selector).click()
    path = OUT / "points.csv"
    event.value.save_as(path)
    return list(csv.DictReader(io.StringIO(path.read_text())))


def run():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path="/usr/bin/chromium")
        page = browser.new_page(viewport={"width": 1512, "height": 1050}, accept_downloads=True, reduced_motion="reduce")
        page.set_default_timeout(60000)
        page.on("pageerror", lambda e: REPORT["javascript_errors"].append(str(e)))
        try:
            page.goto(BASE + "/#precinct-explore", wait_until="networkidle", timeout=180000)
            page.wait_for_function("data&&Atlas.layer&&document.querySelector('.regression-point')", timeout=180000)
            auto = bounds(page)
            assert auto["mode"] == "auto" and auto["hidden"] > 0
            points_before = csv_rows(page, "#regression-download")
            assert len(points_before) == len(auto["points"])
            page.locator("#regression").screenshot(path=OUT / "texas-auto.png")
            png(page, '[data-image="regression"]', "texas-export")
            page.locator("#regression-scale").select_option("full")
            full = bounds(page)
            assert full["min"] == 0 and full["hidden"] == 0
            assert full["fit"] == auto["fit"] and full["points"] == auto["points"]
            assert points_before == csv_rows(page, "#regression-download")
            assert auto["max"] - auto["min"] < full["max"] - full["min"]
            record("Texas automatic range retains OLS and complete CSV", auto=[auto["min"], auto["max"]], full=[full["min"], full["max"]], points=len(auto["points"]), outside=auto["hidden"])
            page.locator("#regression-scale").select_option("focus")
            fixed = bounds(page)
            assert [fixed["min"], fixed["max"]] == [60, 150]
            page.locator("#regression-scale").select_option("auto")
            first = page.locator('.regression-point[tabindex="0"]')
            first.focus()
            first.press("ArrowRight")
            assert page.locator('.regression-point[aria-hidden="false"]:focus').count() == 1
            record("fixed band, full range and visible-only keyboard navigation")

            # Exercise valid auto domains on either side of the reference.
            # The pure policy tests separately generate these from clusters.
            page.evaluate("()=>{window.__range=RegressionScale.calculate;}")
            for low, high in ((10, 30), (160, 180)):
                page.evaluate("""([min,max])=>{RegressionScale.calculate=values=>({mode:'auto',min,max,step:5,ticks:Array.from({length:5},(_,i)=>min+5*i),below:values.filter(v=>v<min).length,above:values.filter(v=>v>max).length});}""", [low, high])
                page.locator("#regression-scale").select_option("auto")
                probe = bounds(page)
                assert [probe["min"], probe["max"]] == [low, high]
                expect(page.locator(".regression-reference")).to_have_count(0)
            page.evaluate("()=>{RegressionScale.calculate=window.__range;}")
            page.locator("#regression-scale").select_option("auto")
            record("quadrants remain valid when the reference is outside the viewport")

            page.locator("#county").select_option("tarrant")
            county = bounds(page)
            assert len(county["points"]) < len(auto["points"])
            for button, mode in (("demographic-mode", "demographic"), ("primary-mode", "primary")):
                if mode == "primary":
                    available=page.evaluate("data.counties.find(c=>Object.keys(primary?.counties?.[c.id]?.precincts||{}).length)?.id")
                    assert available, "No published primary classification available"
                    page.locator("#county").select_option(available)
                page.locator("#" + button).click()
                page.wait_for_function("m=>mode===m&&demoReady()&&document.querySelector('.regression-point')", arg=mode, timeout=180000)
                result = bounds(page)
                assert result["mode"] == "auto"
                assert {color for _, _, color in result["points"]} <= {"#285b91", "#a84236", "#77818e"}
                page.locator("#regression").screenshot(path=OUT / f"texas-{mode}.png")
                record("Texas classification recalculates range and preserves partisan colors", mode=mode, range=[result["min"], result["max"]])
            page.set_viewport_size({"width": 390, "height": 900})
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
            page.locator("#regression").screenshot(path=OUT / "texas-mobile.png")
            page.set_viewport_size({"width": 1512, "height": 1050})

            for state in ("ga", "nc", "va", "nv"):
                page.goto(BASE + f"/#state={state}&view=partisan", wait_until="networkidle", timeout=180000)
                page.wait_for_function("s=>States.id===s&&!States.busy&&States.view?.classification==='partisan'", arg=state, timeout=180000)
                page.locator("#state-full-range").uncheck()
                auto = bounds(page, True)
                assert auto["mode"] == "auto"
                page.locator("#state-panel-regression").screenshot(path=OUT / f"{state}-auto.png")
                page.locator("#state-full-range").check()
                full = bounds(page, True)
                assert full["hidden"] == 0 and full["min"] == 0
                assert full["fit"] == auto["fit"] and full["points"] == auto["points"]
                page.locator("#state-full-range").uncheck()
                record("state county regression shares automatic policy and full-range access", state=state, auto=[auto["min"], auto["max"]], full=[full["min"], full["max"]], points=len(auto["points"]), outside=auto["hidden"])
                if state == "nc":
                    page.locator("#state-classification").select_option("demographic")
                    page.wait_for_function("!States.busy&&States.view?.classification==='demographic'", timeout=180000)
                    demo = bounds(page, True)
                    assert {color for _, _, color in demo["points"]} <= {"#285b91", "#a84236", "#969da8"}
                    png(page, '[data-state-image="regression"]', "nc-demographic-export")
                    page.set_viewport_size({"width": 390, "height": 900})
                    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
                    page.locator("#state-panel-regression").screenshot(path=OUT / "nc-mobile.png")
                    page.set_viewport_size({"width": 1512, "height": 1050})
                    record("county demographic export and mobile layout preserve automatic domain")
            assert not REPORT["javascript_errors"], REPORT["javascript_errors"]
        finally:
            browser.close()


if __name__ == "__main__":
    try:
        run()
        REPORT["passed"] = True
    except Exception as error:
        REPORT["passed"] = False
        REPORT["error"] = str(error)
        raise
    finally:
        (OUT / "verification.json").write_text(json.dumps(REPORT, indent=2) + "\n")
