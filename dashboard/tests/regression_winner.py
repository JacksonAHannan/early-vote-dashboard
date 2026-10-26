"""Browser checks for winner cohorts; run against Rust or a Pages subpath.

TURNOUT_TEST_URL=http://127.0.0.1:8743 uv run --with playwright --with pillow \
    python dashboard/tests/regression_winner.py
"""
import csv
import io
import json
import math
import os
from pathlib import Path
import traceback

from PIL import Image
from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("TURNOUT_TEST_URL", "http://127.0.0.1:8743").rstrip("/")
TAG = os.environ.get("TURNOUT_TEST_TAG", "static" if "turnout-pages" in BASE else "live")
OUT = Path(__file__).resolve().parents[2] / "analysis/regression-winner/qa"
OUT.mkdir(parents=True, exist_ok=True)
REPORT = {"base": BASE, "checks": [], "images": [], "csvs": [], "javascript_errors": []}


def passed(name, **evidence):
    REPORT["checks"].append({"name": name, "passed": True, **evidence})
    print(name, flush=True)


def ols(points):
    if len(points) < 2 or min(p["x"] for p in points) == max(p["x"] for p in points):
        return None
    mx = math.fsum(p["x"] for p in points) / len(points)
    my = math.fsum(p["y"] for p in points) / len(points)
    xx = math.fsum((p["x"] - mx) ** 2 for p in points)
    slope = math.fsum((p["x"] - mx) * (p["y"] - my) for p in points) / xx
    intercept = my - slope * mx
    ss = math.fsum((p["y"] - my) ** 2 for p in points)
    residual = math.fsum((p["y"] - intercept - slope * p["x"]) ** 2 for p in points)
    return {"slope": slope, "intercept": intercept, "r_squared": max(0, min(1, 1 - residual / ss)) if ss else None}


def cohort(points, winner):
    return [p for p in points if winner == "all" or (p["share"] is not None and (p["share"] > 50 if winner == "harris" else p["share"] < 50))]


def tx_points(page):
    return page.locator("#regression-chart .regression-point").evaluate_all("""els=>els.map(e=>({id:e.dataset.id,x:+e.dataset.x,y:+e.dataset.y,share:e.dataset.harrisShare===''?null:+e.dataset.harrisShare,fill:e.getAttribute('fill'),visible:e.getAttribute('aria-hidden')!=='true'}))""")


def state_points(page):
    return page.evaluate("States.regression.points.map(p=>({id:p.id,x:p.x,y:p.y,share:p.harris_share}))")


def check_fit(page, points, state=False):
    expected = ols(points)
    line = page.locator(".state-regression-fit" if state else "#regression-chart .regression-fit")
    stats = page.locator("#state-fit" if state else "#regression-stats").inner_text()
    assert f"n = {len(points):,}" in stats, stats
    if expected is None:
        assert line.count() == 0
    else:
        assert line.count() == 1
        for key in ("slope", "intercept"):
            actual = float(line.get_attribute("data-" + key))
            assert math.isclose(actual, expected[key], rel_tol=1e-9, abs_tol=1e-9), (key, actual, expected)
        if expected["r_squared"] is not None:
            assert f'R² = {expected["r_squared"]:.3f}' in stats, (stats, expected)
    return expected


def check_scale(page, points, state=False, full=False):
    selector = "#state-scatter svg" if state else "#regression-chart svg"
    actual = page.locator(selector).evaluate("e=>({min:+e.dataset.yMin,max:+e.dataset.yMax,mode:e.dataset.scale})")
    expected = page.evaluate("v=>RegressionScale.calculate(v.values,v.mode)", {"values": [p["y"] for p in points], "mode": "full" if full else "auto"})
    assert actual == {"min": expected["min"], "max": expected["max"], "mode": expected["mode"]}, (actual, expected)
    return actual


def csv_download(page, selector, name, count, winner):
    with page.expect_download(timeout=45000) as event:
        page.locator(selector).click()
    path = OUT / f"{TAG}-{name}.csv"
    event.value.save_as(path)
    rows = list(csv.DictReader(io.StringIO(path.read_text())))
    assert len(rows) == count, (count, len(rows))
    assert winner in event.value.suggested_filename
    REPORT["csvs"].append({"file": path.name, "filename": event.value.suggested_filename, "rows": len(rows)})
    return rows


def png_download(page, selector, name, winner, count, fit, state=False):
    page.evaluate("window.__canvasText=[];window.__captureDescs=[]")
    with page.expect_download(timeout=60000) as event:
        page.locator(selector).click()
    path = OUT / f"{TAG}-{name}.png"
    event.value.save_as(path)
    assert winner in event.value.suggested_filename, event.value.suggested_filename
    with Image.open(path) as image:
        assert (image.width == 1600 and 800 <= image.height <= 2000)
        assert len(image.convert("RGB").getcolors(1600001)) > 30
    texts = page.evaluate("window.__canvasText")
    captured = page.evaluate("window.__captureDescs")
    title = "Harris-won" if winner == "harris" else "Trump-won"
    assert title in " ".join(texts), texts
    contents = " ".join(texts) + " ".join(node for desc in captured for node in desc["nodes"])
    assert f"n = {count:,}" in contents, contents
    if fit and fit["r_squared"] is not None:
        assert f'R² = {fit["r_squared"]:.3f}' in contents, contents
    assert "Official" in contents and ("Census" in contents or state), contents
    REPORT["images"].append({"file": path.name, "filename": event.value.suggested_filename, "size": list(image.size), "texts": texts, "capture": captured})
    return path


def ready_state(page, state, classification=None):
    page.wait_for_function("""e=>!!window.States&&!States.busy&&States.id===e.state&&States.view?.id===e.state&&(!e.classification||States.classification===e.classification&&States.view.classification===e.classification)&&States.layer?.state===e.state""", arg={"state": state, "classification": classification}, timeout=180000)


def overflow(page, name):
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(350)
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth"), page.evaluate("[document.documentElement.scrollWidth,innerWidth]")
    page.screenshot(path=str(OUT / f"{TAG}-{name}-mobile.png"), full_page=True)
    page.set_viewport_size({"width": 1512, "height": 1100})
    page.wait_for_timeout(350)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        page = browser.new_page(viewport={"width": 1512, "height": 1100}, accept_downloads=True)
        page.on("pageerror", lambda error: REPORT["javascript_errors"].append(str(error)))
        page.goto(BASE + "/", wait_until="networkidle", timeout=180000)
        page.wait_for_function("data&&window.Visuals&&window.States", timeout=180000)
        page.evaluate("""()=>{
          window.__canvasText=[];window.__captureDescs=[];
          const fill=CanvasRenderingContext2D.prototype.fillText;
          CanvasRenderingContext2D.prototype.fillText=function(text,...args){window.__canvasText.push(String(text));return fill.call(this,text,...args);};
          const capture=Visuals.capture;
          Visuals.capture=async function(desc){window.__captureDescs.push({title:desc.title||'',nodes:desc.nodes.map(n=>n.textContent||'')});return capture.call(this,desc);};
        }""")
        page.locator("#precincts-tab").click()
        page.locator("#precinct-explore-tab").click()
        page.locator("#county").select_option("tarrant")
        page.locator("#demographic-mode").click()
        page.locator("#metric").select_option("non_white_vap")
        page.wait_for_function("mode==='demographic'&&county==='tarrant'&&metricId==='non_white_vap'&&demoReady()", timeout=180000)
        expect(page.locator("#regression-winner")).to_be_visible()
        all_points = tx_points(page)
        assert all_points
        summaries = {}
        for winner in ("all", "trump", "harris"):
            page.locator(f'[data-regression-winner="{winner}"]').click()
            expect(page.locator(f'[data-regression-winner="{winner}"]')).to_have_attribute("aria-pressed", "true")
            expected = cohort(all_points, winner)
            actual = tx_points(page)
            assert [p["id"] for p in actual] == [p["id"] for p in expected]
            for point in actual:
                assert point["fill"] == ("#285b91" if point["share"] > 50 else "#a84236" if point["share"] < 50 else "#77818e")
            fit = check_fit(page, actual)
            scale = check_scale(page, actual)
            rows = csv_download(page, "#regression-download", "texas-" + winner, len(actual), winner)
            assert all((float(row["harris_share_2024_pct"]) > 50 if winner == "harris" else float(row["harris_share_2024_pct"]) < 50) for row in rows) if winner != "all" else True
            if winner != "all":
                png_download(page, '[data-image="regression"]', "texas-" + winner, winner, len(actual), fit)
            summaries[winner] = {"n": len(actual), "fit": fit, "scale": scale}
        passed("Texas demographic winner cohorts, independent OLS, scales, colors, CSV and PNG", county="tarrant", metric="non_white_vap", cohorts=summaries)
        page.locator("#regression-scale").select_option("full")
        check_scale(page, tx_points(page), full=True)
        check_fit(page, tx_points(page))
        assert len(tx_points(page)) == summaries["harris"]["n"]
        visible = page.locator('#regression-chart .regression-point[aria-hidden="false"]').first
        visible.focus()
        visible.press("ArrowRight")
        focused = page.locator("#regression-chart .regression-point:focus")
        assert focused.count() == 1 and focused.get_attribute("aria-hidden") == "false"
        point_id = focused.get_attribute("data-id")
        focused.press("Enter")
        page.wait_for_function("Atlas.county==='tarrant'&&Atlas.active?.county==='tarrant'&&Atlas.layer&&document.getElementById('map-loading').hidden", timeout=180000)
        assert page.evaluate("selection.county+':'+selection.group_index") == point_id
        center = page.evaluate("({lat:Atlas.map.getCenter().lat,lng:Atlas.map.getCenter().lng,zoom:Atlas.map.getZoom()})")
        assert all(math.isfinite(v) for v in center.values())
        assert center["zoom"] >= 10
        page.locator("#regression").screenshot(path=str(OUT / f"{TAG}-texas-desktop.png"))
        overflow(page, "texas")
        passed("Texas full range preserves cohort and fit; keyboard selects linked precinct map; 390px layout", map=center)
        page.locator("#partisan-mode").click()
        expect(page.locator("#regression-winner")).to_be_hidden()
        partisan_points = tx_points(page)
        partisan_count = len(partisan_points)
        page.evaluate("regressionWinner='trump';regression()")
        assert len(tx_points(page)) == partisan_count
        check_fit(page, tx_points(page))
        passed("Texas partisan view hides cohort controls and retains every eligible point", n=partisan_count)

        page.locator("#state-select").select_option("nc")
        ready_state(page, "nc")
        page.locator("#state-classification").select_option("demographic")
        ready_state(page, "nc", "demographic")
        page.locator("#state-metric").select_option("non_white_vap")
        ready_state(page, "nc", "demographic")
        page.locator('[data-state-bulk="expand"]').click()
        page.locator('[data-state-winner="all"]').click()
        all_counties = state_points(page)
        assert len(all_counties) == 100
        summaries = {}
        for winner in ("all", "trump", "harris"):
            page.locator(f'[data-state-winner="{winner}"]').click()
            expect(page.locator(f'[data-state-winner="{winner}"]')).to_have_attribute("aria-pressed", "true")
            expected = cohort(all_counties, winner)
            actual = state_points(page)
            assert [p["id"] for p in actual] == [p["id"] for p in expected]
            fills = page.locator("#state-scatter .state-dot").evaluate_all("els=>els.map(e=>e.getAttribute('fill'))")
            assert fills == ["#285b91" if p["share"] > 50 else "#a84236" if p["share"] < 50 else "#969da8" for p in actual]
            fit = check_fit(page, actual, state=True)
            scale = check_scale(page, actual, state=True)
            csv_download(page, '[data-state-csv="regression"]', "nc-" + winner, len(actual), winner)
            if winner != "all":
                png_download(page, '[data-state-image="regression"]', "nc-" + winner, winner, len(actual), fit, state=True)
            summaries[winner] = {"n": len(actual), "fit": fit, "scale": scale}
        passed("North Carolina county winner cohorts, independent OLS, scales, colors and exports", cohorts=summaries)
        page.locator("#state-full-range").check()
        check_scale(page, state_points(page), state=True, full=True)
        check_fit(page, state_points(page), state=True)
        dot = page.locator('#state-scatter .state-dot[aria-hidden="false"]').first
        target = dot.get_attribute("data-state-county")
        dot.focus()
        dot.press("Enter")
        page.wait_for_function("expected=>States.county===expected", arg=target)
        page.locator("#state-panel-regression").screenshot(path=str(OUT / f"{TAG}-nc-desktop.png"))
        overflow(page, "nc")
        passed("State full range preserves cohort fit; keyboard selects county; 390px layout", county=target)
        page.locator("#state-classification").select_option("partisan")
        ready_state(page, "nc", "partisan")
        assert page.locator("[data-state-winner]").count() == 0
        assert len(state_points(page)) == 100
        passed("State partisan view retains all counties and hides demographic winner filters")
        page.locator("#state-select").select_option("nv")
        ready_state(page, "nv")
        page.locator("#state-classification").select_option("demographic")
        ready_state(page, "nv", "demographic")
        page.locator('[data-state-winner="all"]').click()
        nevada_points = state_points(page)
        absent_winner = next(winner for winner in ("trump", "harris") if not cohort(nevada_points, winner))
        page.locator(f'[data-state-winner="{absent_winner}"]').click()
        assert state_points(page) == []
        expect(page.locator("#state-scatter")).to_contain_text("No same-date comparison")
        expect(page.locator('[data-state-image="regression"]')).to_be_disabled()
        csv_download(page, '[data-state-csv="regression"]', "nv-empty-" + absent_winner, 0, absent_winner)
        passed("Nevada empty winner cohort keeps header-only CSV and disables unavailable PNG", winner=absent_winner, all_points=nevada_points)
        assert not REPORT["javascript_errors"], REPORT["javascript_errors"]
        REPORT["status"] = "passed"
        browser.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        REPORT["status"] = "failed"
        REPORT["failure"] = traceback.format_exc()
        raise
    finally:
        (OUT / f"{TAG}-verification.json").write_text(json.dumps(REPORT, indent=2) + "\n")
