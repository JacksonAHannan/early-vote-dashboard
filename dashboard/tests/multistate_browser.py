"""Exercise the multistate UI against an already-running QA service.

TURNOUT_TEST_URL=http://127.0.0.1:8743 uv run --with playwright --with pillow \
    python dashboard/tests/multistate_browser.py
"""
import csv
import io
import json
import os
import sys
from pathlib import Path
import traceback

from PIL import Image
from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("TURNOUT_TEST_URL", "http://127.0.0.1:8743")
OUT = Path(__file__).resolve().parents[2] / "analysis/multistate/qa"
OUT.mkdir(parents=True, exist_ok=True)
REPORT = {"base": BASE, "checks": [], "screenshots": [], "images": [], "csvs": [], "javascript_errors": []}


def passed(name, **evidence):
    REPORT["checks"].append({"check": name, "passed": True, **evidence})
    print(name, flush=True)


def record_error(error):
    REPORT["javascript_errors"].append(str(error))
    evidence = {"message": str(error), "stack": error.stack, "after_check": REPORT["checks"][-1]["check"] if REPORT["checks"] else "initialization"}
    REPORT.setdefault("javascript_error_stacks", []).append(evidence)
    print("JAVASCRIPT ERROR: " + json.dumps(evidence), flush=True)


def ready(page, state=None, classification=None, method=None, date=None, map_ready=False):
    page.wait_for_function("""(expected)=>{
        const a=window.States;if(!a||a.busy||!a.view)return false;
        if(expected.state&&(a.id!==expected.state||a.view.id!==expected.state))return false;
        if(expected.classification&&(a.classification!==expected.classification||a.view.classification!==expected.classification))return false;
        if(expected.method&&(a.method!==expected.method||a.view.method!==expected.method))return false;
        if(expected.date&&(a.date!==expected.date||a.view.date!==expected.date))return false;
        return !expected.map_ready||a.layer?.state===a.id;
    }""", arg={"state": state, "classification": classification, "method": method, "date": date, "map_ready": map_ready}, timeout=180000)
    expect(page.locator("#state-error")).to_be_hidden()


def classification(page, value):
    page.locator("#state-classification").select_option(value)
    ready(page, classification=value)


def choose_state(page, state):
    page.locator("#state-select").select_option(state)
    ready(page, state=state, map_ready=True)
    if page.locator('[data-state-bulk="expand"]').is_visible():
        page.locator('[data-state-bulk="expand"]').click()


def csv_file(page, key, name):
    selector = f'[data-state-csv="{key}"]'
    assert page.locator(selector).get_attribute("href", timeout=45000)
    with page.expect_download(timeout=45000) as event:
        page.locator(selector).click()
    path = OUT / ("csv-evidence-" + name + ".csv")
    event.value.save_as(path)
    rows = list(csv.DictReader(io.StringIO(path.read_text())))
    assert rows, (key, "empty exported CSV")
    REPORT["csvs"].append({"key": key, "file": path.name, "rows": len(rows), "filename": event.value.suggested_filename})
    return rows


def png_file(page, key, name):
    button = page.locator(f'[data-state-image="{key}"]')
    expect(button).to_be_enabled(timeout=45000)
    with page.expect_download(timeout=60000) as event:
        button.click()
    path = OUT / ("export-" + name + ".png")
    event.value.save_as(path)
    with Image.open(path) as img:
        assert img.size == (1600, 1000), (key, img.size)
        rgb = img.convert("RGB")
        assert len(rgb.getcolors(1600001)) > 30, (key, "blank image")
        if "A" in img.getbands():
            assert img.getchannel("A").getextrema() == (255, 255)
        if key in ("table", "precincts"):
            # A browser scrollbar creates a long dark neutral run; table
            # rules are pale and text cannot form a 200-pixel solid bar.
            pixels = rgb.load()
            for y in range(210, 900):
                run = 0
                for x in range(48, 1552):
                    r, g, b = pixels[x, y]
                    run = run + 1 if 70 <= r <= 180 and abs(r - g) < 3 and abs(g - b) < 3 else 0
                    assert run <= 200, (key, "scrollbar clipped exported table", x, y)
    REPORT["images"].append({"key": key, "file": path.name, "size": [1600, 1000], "filename": event.value.suggested_filename})
    return path


def assert_no_overflow(page, width, state):
    page.set_viewport_size({"width": width, "height": 1050})
    page.wait_for_timeout(200)
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1"), page.evaluate("({width:innerWidth,scroll:document.documentElement.scrollWidth})")
    map_width, body_width = page.evaluate("[document.querySelector('#state-map').clientWidth,document.querySelector('#state-body-map').clientWidth]")
    assert map_width > 100 and map_width <= body_width, (width, map_width, body_width)
    path = OUT / f"browser-{state}-{width}.png"
    page.screenshot(path=path, full_page=True)
    REPORT["screenshots"].append(path.name)


def export_blocked(page):
    assert page.evaluate("States.busy")
    assert page.locator('[data-state-image]:not(:disabled)').count() == 0
    assert page.locator('[data-state-csv][href]').count() == 0
    for item in page.locator('[data-state-csv]').all():
        expect(item).to_have_attribute("aria-disabled", "true")


def run():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path="/usr/bin/chromium")
        page = browser.new_page(viewport={"width": 1512, "height": 1050}, reduced_motion="reduce", accept_downloads=True)
        page.set_default_timeout(45000)
        page.on("pageerror", record_error)
        try:
            page.goto(BASE + "/#state=ga", wait_until="networkidle", timeout=180000)
            ready(page, state="ga", map_ready=True)
            page.locator('[data-state-bulk="expand"]').click()

            for state, count in (("ga", 159), ("nc", 100), ("va", 133), ("nv", 17)):
                if "--resume" in sys.argv and any(check.get("check") == "state capabilities and selection" and check.get("state") == state for check in REPORT["checks"]):
                    continue
                if page.evaluate("States.id") != state:
                    choose_state(page, state)
                classification(page, "partisan")
                county_count = page.evaluate("States.view.counties.length") if state == "nv" else count
                assert page.locator("#state-body-table .state-data-table tbody tr").count() == county_count
                assert page.evaluate("States.layer.getLayers().length") == count
                expect(page.locator("#state-summary")).not_to_contain_text("NaN")
                point_count = page.locator(".state-dot").count()
                assert point_count == page.evaluate("States.view.points.length")
                assert point_count > 0
                # Inspect every available group type, without requiring a
                # state to publish demographics it does not collect.
                supported = page.evaluate("States.view.breakdowns")
                views = ["demographic"] + [value for value in ("race", "age", "sex", "white_nonwhite", "party", "ethnicity") if value in supported]
                for value in views:
                    classification(page, value)
                    page.wait_for_function("States.map.getSize().x===document.querySelector('#state-map').clientWidth")
                    if value == "demographic":
                        page.locator("#state-metric").select_option("non_white_vap")
                        ready(page, classification=value)
                        assert page.locator("#state-panel-regression").is_visible()
                        assert page.locator(".state-dot").evaluate_all("dots=>dots.every(dot=>{const p=States.view.points.find(p=>p.id===dot.dataset.stateCounty);const color=p.harris_share===null||p.harris_share===50?'#969da8':p.harris_share>50?'#285b91':'#a84236';return dot.getAttribute('fill')===color;})")
                    else:
                        assert page.locator("#state-panel-regression").is_hidden()
                    if page.locator("#state-buckets .state-bucket").count() == 0:
                        expect(page.locator("#state-buckets .state-empty")).to_have_text("No same-date comparison published for this breakdown")
                        expect(page.locator('[data-state-image="buckets"]')).to_be_disabled()
                classification(page, "partisan")
                methods = page.evaluate("States.view.methods")
                for value in methods:
                    page.locator("#state-method").select_option(value)
                    ready(page, state=state, method=value)
                    assert page.locator("#state-method").input_value() == value
                if "in_person" in methods:
                    page.locator("#state-method").select_option("in_person")
                    ready(page, method="in_person")
                page.locator("#state-measure").select_option("daily")
                assert page.evaluate("States.measure") == "daily"
                assert page.locator("#state-turnout-chart svg").count() == 1
                page.locator("#state-measure").select_option("cumulative")
                png_file(page, "turnout", state + "-turnout")
                assert_no_overflow(page, 1512, state)
                passed("state capabilities and selection", state=state, counties=county_count, map_counties=count, point_count=point_count, views=views, methods=methods)

            # Return to the mature NC feed for detailed interaction/export QA.
            choose_state(page, "nc")
            classification(page, "partisan")
            page.locator("#state-method").select_option("in_person")
            ready(page, state="nc", method="in_person")
            observed = page.evaluate("States.date")
            future = page.evaluate("States.view.series.find(p=>p.future&&p.cumulative_2024!==null)?.date_2026")
            assert future
            assert page.locator(f'#state-turnout-chart circle[data-year="2024"][data-date="{future}"]').count() == 1
            assert page.locator(f'#state-turnout-chart circle[data-year="2026"][data-date="{future}"]').count() == 0
            page.locator("#state-date").fill(future)
            page.locator("#state-date").dispatch_event("change")
            ready(page, date=future)
            assert page.evaluate("States.view.series.find(p=>p.date_2026===States.date).cumulative_2026===null")
            expect(page.locator("#state-summary dd").nth(1)).to_contain_text("—")
            expect(page.locator("#state-summary dd").nth(2)).not_to_contain_text("—")
            page.locator("#state-date").fill(observed)
            page.locator("#state-date").dispatch_event("change")
            ready(page, date=observed)
            passed("future benchmark remains historical-only", observed=observed, future=future)

            # Keyboard activation exercises the same linked selection as a
            # pointer click, including dots hidden by the default focus band.
            before_zoom = page.evaluate("States.map.getZoom()")
            visible = page.locator('.state-dot[aria-hidden="false"]').first
            if not visible.count():
                page.locator("#state-full-range").check()
                visible = page.locator('.state-dot[aria-hidden="false"]').first
            county_id = visible.get_attribute("data-state-county")
            county_name = page.evaluate("id=>States.view.counties.find(c=>c.id===id).name", county_id)
            visible.focus()
            visible.press("Enter")
            assert page.evaluate("States.county") == county_id
            expect(page.locator("#state-panel-county h2")).to_have_text(county_name)
            assert page.locator(f'#state-body-table .state-data-table tr.selected[data-state-county="{county_id}"]').count() == 1
            assert page.evaluate("States.map.getZoom()") > before_zoom
            passed("scatter selection links map and county detail", county=county_name)

            for key in ("turnout", "buckets", "map", "regression", "county", "table"):
                png_file(page, key, "nc-" + key)
                if key != "map":
                    rows = csv_file(page, key, "nc-" + key)
                    if key in ("turnout", "buckets", "county"):
                        for row in rows:
                            if row["future"] == "true":
                                assert row["daily_2026"] == row["cumulative_2026"] == ""
                            else:
                                for prefix in ("daily", "cumulative"):
                                    assert (row[prefix + "_2024"] == "") == (row[prefix + "_2026"] == "")
            png_file(page, "bucket-0", "nc-single-bucket")
            passed("all visuals export actual opaque social PNGs and CSVs")

            # Persist panel state, exercise state-local restoration and bulk
            # actions before resuming the rest of the checks.
            page.locator('[data-state-collapse="buckets"]').click()
            expect(page.locator("#state-body-buckets")).to_be_hidden()
            choose_state(page, "ga")
            page.locator("#state-select").select_option("nc")
            ready(page, state="nc", map_ready=True)
            expect(page.locator("#state-body-buckets")).to_be_hidden()
            page.locator('[data-state-bulk="expand"]').click()
            page.locator('[data-state-bulk="collapse"]').click()
            for key in ("turnout", "buckets", "map", "regression", "county", "table"):
                expect(page.locator("#state-body-" + key)).to_be_hidden()
            page.locator('[data-state-bulk="expand"]').click()
            passed("state-local collapse persists and bulk controls work")

            # Keep two source requests pending, then deliver the newer one
            # first. Neither exports nor the final view may use the old scope.
            held = []
            def hold(route):
                held.append(route)
            page.route("**/api/states/nc?**", hold)
            page.locator("#state-method").select_option("mail")
            page.wait_for_function("States.busy")
            page.wait_for_timeout(100)
            export_blocked(page)
            page.locator("#state-method").select_option("total")
            page.wait_for_timeout(100)
            assert len(held) == 2
            export_blocked(page)
            held[1].continue_()
            ready(page, method="total")
            held[0].continue_()
            page.wait_for_timeout(250)
            ready(page, method="total")
            page.unroute("**/api/states/nc?**", hold)
            rows = csv_file(page, "turnout", "nc-race-latest-method")
            assert all(row["method"] == "total" for row in rows)
            passed("pending method exports blocked and stale response ignored")

            held.clear()
            page.route("**/api/states/nc?**", hold)
            page.locator("#state-classification").select_option("race")
            page.wait_for_function("States.busy")
            page.wait_for_timeout(100)
            export_blocked(page)
            choose_state(page, "ga")
            for route in held:
                route.continue_()
            page.unroute("**/api/states/nc?**", hold)
            page.wait_for_timeout(250)
            ready(page, state="ga")
            passed("pending classification exports blocked and old state response ignored")

            choose_state(page, "nc")
            classification(page, "partisan")
            held.clear()
            page.route("**/api/states/nc?**", hold)
            earlier = page.evaluate("States.view.series.filter(p=>!p.future).at(-2).date_2026")
            page.locator("#state-date").fill(earlier)
            page.locator("#state-date").dispatch_event("change")
            page.wait_for_function("States.busy")
            page.wait_for_timeout(100)
            export_blocked(page)
            for route in held:
                route.continue_()
            page.unroute("**/api/states/nc?**", hold)
            ready(page, date=earlier)
            passed("pending date exports blocked until new date arrives")

            choose_state(page, "ga")
            classification(page, "age")
            assert page.evaluate("States.view.buckets.length") > 9
            page.locator("#state-bucket-next").click()
            assert page.evaluate("States.bucketPage") == 1
            assert page.locator("#state-buckets .state-bucket").count() > 0
            png_file(page, "buckets", "ga-age-buckets-page-2")
            first_key = page.locator("#state-buckets [data-state-image]").first.get_attribute("data-state-image")
            png_file(page, first_key, "ga-age-bucket-page-2-single")
            passed("bucket page two and individual chart exports", state="ga", classification="age", published_page_two=True)
            # Restore official data before screenshots and final assertions.
            choose_state(page, "nc")
            classification(page, "demographic")
            page.locator("#state-metric").select_option("non_white_vap")
            ready(page, classification="demographic")
            for width in (1512, 768, 390):
                assert_no_overflow(page, width, "nc-nonwhite")
            passed("desktop tablet mobile layouts stay within viewport", widths=[1512, 768, 390])

            page.locator('[data-state-collapse="map"]').click()
            for width in (768, 390, 1512):
                page.set_viewport_size({"width": width, "height": 1050})
                page.wait_for_timeout(100)
            page.locator('[data-state-collapse="map"]').click()
            page.wait_for_timeout(200)
            assert page.evaluate("Number.isFinite(States.map.getCenter().lat)&&Number.isFinite(States.map.getCenter().lng)")
            passed("collapsed map survives zero-size resizing and reopens with finite coordinates")

            page.set_viewport_size({"width": 1512, "height": 1050})
            page.locator("#state-select").select_option("tx")
            expect(page.locator("#texas-dashboard")).to_be_visible()
            expect(page.locator("#states-workspace")).to_be_hidden()
            page.wait_for_function("window.CountyView?.view&&window.Tracking?.view", timeout=180000)
            choose_state(page, "nv")
            assert page.locator("#texas-dashboard").is_hidden()
            assert page.locator("#state-body-table .state-data-table tbody tr").count() == page.evaluate("States.view.counties.length")
            passed("Texas roundtrip preserves Texas and new-state workspaces")
            assert not REPORT["javascript_errors"], REPORT["javascript_errors"]
            REPORT["passed"] = True
            REPORT["core_passed"] = True
        finally:
            if not REPORT.get("passed"):
                try:
                    page.screenshot(path=OUT / "browser-failure.png", full_page=True)
                    REPORT["failure_view"] = page.evaluate("({id:States.id,busy:States.busy,method:States.method,classification:States.classification,date:States.date,view_id:States.view?.id,view_method:States.view?.method,view_classification:States.view?.classification})")
                except Exception:
                    pass
            browser.close()


def run_precincts():
    """Inspect dated current precincts without implying a historic match."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path="/usr/bin/chromium")
        page = browser.new_page(viewport={"width": 1512, "height": 1050}, reduced_motion="reduce", accept_downloads=True)
        page.set_default_timeout(45000)
        page.on("pageerror", record_error)
        try:
            page.goto(BASE + "/#state=nc", wait_until="networkidle", timeout=180000)
            ready(page, state="nc", map_ready=True)
            page.locator('[data-state-bulk="expand"]').click()
            for measure in ("daily", "cumulative"):
                page.locator("#state-measure").select_option(measure)
                values = page.evaluate("()=>{const p=States.view.counties.find(c=>c.id===States.county).selected;return [p[States.measure+'_2026'],p[States.measure+'_2024']];}")
                profile_values = page.locator("#state-county-profile .state-selection-stats strong").all_text_contents()
                assert profile_values[:2] == [f"{value:,}" if value is not None else "—" for value in values]
                tooltip = page.evaluate("()=>{const c=States.view.counties.find(c=>c.id===States.county);return States.layer.getLayers().find(l=>l.feature.properties.GEOID===c.fips).getTooltip().getContent();}")
                for year, value in zip((2026, 2024), values):
                    assert f"{year} {measure} {value:,}" in tooltip

            downloads = []
            page.on("download", lambda download: downloads.append(download.suggested_filename))
            page.evaluate("""()=>{window.__qaCapture=Visuals.capture;Visuals.capture=function(desc){return new Promise((resolve,reject)=>{window.__qaReleaseCapture=()=>window.__qaCapture.call(Visuals,desc).then(resolve,reject);});};}""")
            page.locator('[data-state-image="county"]').click()
            page.wait_for_function("typeof window.__qaReleaseCapture==='function'")
            page.locator("#state-measure").select_option("daily")
            page.evaluate("window.__qaReleaseCapture();undefined")
            expect(page.locator("#state-status")).to_contain_text("Selection changed", timeout=45000)
            assert not downloads, downloads
            page.evaluate("()=>{Visuals.capture=window.__qaCapture;}")
            png_file(page, "county", "nc-daily-county")
            assert "-daily-" in REPORT["images"][-1]["filename"]
            passed("measure change during delayed image capture aborts stale export; fresh export succeeds")
            page.locator("#state-measure").select_option("daily")
            page.evaluate("""()=>{window.__qaCanvasText=[];window.__qaFill=CanvasRenderingContext2D.prototype.fillText;CanvasRenderingContext2D.prototype.fillText=function(text,...args){window.__qaCanvasText.push(String(text));return window.__qaFill.call(this,text,...args);};}""")
            png_file(page, "regression", "nc-daily-selection-regression-cumulative")
            texts = page.evaluate("window.__qaCanvasText")
            page.evaluate("()=>{CanvasRenderingContext2D.prototype.fillText=window.__qaFill;}")
            assert "-cumulative-" in REPORT["images"][-1]["filename"]
            assert any("North Carolina" in text and text.endswith("cumulative") for text in texts), texts
            assert not any(text.endswith("· daily") for text in texts), texts
            assert any("R²" in text and "n =" in text for text in texts), texts
            assert not any("2024 dashed gray" in text for text in texts), texts
            page.locator("#state-measure").select_option("cumulative")
            passed("daily profile and map tooltip follow selected measure; regression export remains cumulative")
            page.wait_for_function("States.precinctView?.rows.length>0&&!States.precinctPending", timeout=120000)
            assert page.locator("#state-precinct-table thead th").all_text_contents() == ["Precinct", "2026 reported votes"]
            rows = csv_file(page, "precincts", "nc-current-precincts")
            assert all(row["cross_cycle_comparison"] == "false" for row in rows)
            assert not any("2024" in key for key in rows[0])
            date = page.evaluate("States.date")
            assert all(row["date_2026"] == date for row in rows)
            page.evaluate("""()=>{window.__qaCanvasText=[];window.__qaFill=CanvasRenderingContext2D.prototype.fillText;CanvasRenderingContext2D.prototype.fillText=function(text,...args){window.__qaCanvasText.push(String(text));return window.__qaFill.call(this,text,...args);};}""")
            png_file(page, "precincts", "nc-current-precincts")
            texts = page.evaluate("window.__qaCanvasText")
            page.evaluate("()=>{CanvasRenderingContext2D.prototype.fillText=window.__qaFill;}")
            assert date in texts, texts
            assert not any("2024-" in text for text in texts), texts
            assert any("First 12" in text for text in texts), texts
            passed("NC precincts export reported current counts without historical ratios", rows=len(rows))

            held = []
            def hold(route):
                held.append(route)
            page.route("**/api/states/nc/precincts?**", hold)
            current = page.evaluate("States.county")
            target = page.locator(f'#state-body-table tr[data-state-county]:not([data-state-county="{current}"])').first
            next_county = target.get_attribute("data-state-county")
            target.click()
            page.wait_for_function("!!States.precinctPending")
            page.wait_for_timeout(100)
            assert page.locator('[data-state-csv="precincts"]').get_attribute("href") is None
            expect(page.locator('[data-state-image="precincts"]')).to_be_disabled()
            assert page.locator("#state-precinct-table tbody tr").count() == 0
            for route in held:
                route.continue_()
            page.unroute("**/api/states/nc/precincts?**", hold)
            page.wait_for_function("id=>!States.precinctPending&&States.precinctView?.county===id", arg=next_county, timeout=120000)
            passed("pending county precinct request clears stale counts and exports")

            choose_state(page, "nv")
            page.wait_for_function("States.precinctView?.rows.length>0&&!States.precinctPending", timeout=120000)
            rows = csv_file(page, "precincts", "nv-current-precincts")
            assert all(row["cross_cycle_comparison"] == "false" for row in rows)
            png_file(page, "precincts", "nv-current-precincts")
            passed("Nevada current precincts remain separate from county comparisons", rows=len(rows))

            choose_state(page, "va")
            page.wait_for_function("States.precinctView&&!States.precinctPending", timeout=120000)
            assert page.evaluate("States.precinctView.rows.length") == 0
            expect(page.locator("#state-precinct-table tbody")).to_have_text("No reported mail + in person precinct observations")
            expect(page.locator('[data-state-image="precincts"]')).to_be_disabled()
            classification(page, "demographic")
            page.wait_for_function("States.precinctView&&!States.precinctPending", timeout=120000)
            expect(page.locator('[data-state-image="precincts"]')).to_be_disabled()
            latest = page.evaluate("States.precinctView.latest_reported")
            assert latest == "2026-09-23"
            page.locator("#state-date").fill(latest)
            page.locator("#state-date").dispatch_event("change")
            ready(page, state="va", date=latest)
            page.locator('#state-body-table tr[data-state-county="51059"]').click()
            page.wait_for_function("States.precinctView?.rows.length>0&&!States.precinctPending", timeout=120000)
            rows = csv_file(page, "precincts", "va-september-23-precincts")
            assert all(row["date_2026"] == latest and row["cross_cycle_comparison"] == "false" for row in rows)
            passed("Virginia dated September precinct report is not carried into October", available=latest, rows=len(rows))
            choose_state(page, "nc")
            classification(page, "demographic")
            page.wait_for_function("!States.precinctPending", timeout=120000)
            for width in (1512, 768, 390):
                assert_no_overflow(page, width, "nc-nonwhite-final")
            passed("final desktop and mobile screenshots include loaded precinct panel")
            page.set_viewport_size({"width": 1512, "height": 1050})
            choose_state(page, "ga")
            page.locator("#state-select").select_option("tx")
            expect(page.locator("#texas-dashboard")).to_be_visible()
            page.set_viewport_size({"width": 390, "height": 1050})
            choose_state(page, "ga")
            page.wait_for_function("States.map.getSize().x===document.querySelector('#state-map').clientWidth")
            box = page.evaluate("""()=>{const b=States.layer.getBounds(),a=States.map.latLngToContainerPoint(b.getNorthWest()),z=States.map.latLngToContainerPoint(b.getSouthEast()),s=States.map.getSize();return {northwest:[a.x,a.y],southeast:[z.x,z.y],size:[s.x,s.y]};}""")
            assert all(value >= -1 for value in box["northwest"]), box
            assert all(value <= limit + 1 for value, limit in zip(box["southeast"], box["size"])), box
            page.screenshot(path=OUT / "browser-ga-mobile-after-texas.png", full_page=True)
            REPORT["screenshots"].append("browser-ga-mobile-after-texas.png")
            passed("Georgia map refits whole state after Texas and mobile resize", bounds=box)
            assert not REPORT["javascript_errors"], REPORT["javascript_errors"]
        finally:
            browser.close()


def run_tables():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path="/usr/bin/chromium")
        page = browser.new_page(viewport={"width": 1512, "height": 1050}, reduced_motion="reduce", accept_downloads=True)
        page.set_default_timeout(45000)
        page.on("pageerror", record_error)
        try:
            page.goto(BASE + "/#state=nc", wait_until="networkidle", timeout=180000)
            ready(page, state="nc", map_ready=True)
            page.locator('[data-state-bulk="expand"]').click()
            page.wait_for_function("States.precinctView?.rows.length>0&&!States.precinctPending", timeout=120000)
            page.evaluate("""()=>{
                window.__qaCapture=Visuals.capture;
                Visuals.capture=async function(desc){
                    const result=await window.__qaCapture.call(Visuals,desc),text=decodeURIComponent(result.img.src.slice(result.img.src.indexOf(',')+1)),doc=new DOMParser().parseFromString(text,'image/svg+xml'),table=doc.querySelector('table');
                    const rows=[...table.querySelectorAll('tbody tr')],clipping=[];
                    for(let node=table;node&&node.parentElement?.localName!=='foreignObject';node=node.parentElement){if(['auto','scroll','hidden'].includes(node.style.overflow))clipping.push(node.localName+':'+node.style.overflow);}
                    window.__qaTable={source_rows:desc.nodes[0].querySelectorAll('tbody tr').length,captured_rows:rows.length,right_cells:rows.map(row=>row.lastElementChild.textContent.trim()),clipping,width:result.width,height:result.height};
                    return result;
                };
            }""")
            for key, name in (("table", "nc-table"), ("precincts", "nc-current-precincts")):
                png_file(page, key, name)
                capture = page.evaluate("window.__qaTable")
                assert capture["captured_rows"] == min(12, capture["source_rows"]), capture
                assert not capture["clipping"], capture
                assert all(capture["right_cells"]), capture
                passed("table PNG captures all twelve rows and right-hand values without scrollbars", key=key, capture=capture)
            page.evaluate("()=>{Visuals.capture=window.__qaCapture;}")
            assert not REPORT["javascript_errors"], REPORT["javascript_errors"]
        finally:
            browser.close()


if __name__ == "__main__":
    try:
        if "--tables-only" in sys.argv:
            REPORT = json.loads((OUT / "browser-verification.json").read_text())
            assert REPORT.get("core_passed"), "Run the core suite successfully before table checks"
            run_tables()
            REPORT["passed"] = True
        elif "--precinct-only" in sys.argv:
            REPORT = json.loads((OUT / "browser-verification.json").read_text())
            assert REPORT.get("core_passed", REPORT.get("passed")), "Run the core suite successfully before precinct checks"
            run_precincts()
            REPORT["passed"] = True
        else:
            if "--resume" in sys.argv:
                REPORT = json.loads((OUT / "browser-verification.json").read_text())
                REPORT.setdefault("previous_attempts", []).append({"failure": REPORT.get("failure"), "javascript_errors": REPORT["javascript_errors"], "javascript_error_stacks": REPORT.get("javascript_error_stacks", []), "retained_checks": len(REPORT["checks"])})
                REPORT["javascript_errors"] = []
                REPORT["javascript_error_stacks"] = []
                for field in ("failure", "traceback", "failure_view"):
                    REPORT.pop(field, None)
            run()
    except Exception as error:
        REPORT["passed"] = False
        REPORT["failure"] = str(error)
        REPORT["traceback"] = traceback.format_exc()
        raise
    finally:
        (OUT / "browser-verification.json").write_text(json.dumps(REPORT, indent=2) + "\n")
