"""Verify Georgia's statewide voter-demographic headline and actual exports.

TURNOUT_TEST_URL=http://127.0.0.1:8743 uv run --with playwright --with pillow \
    python dashboard/tests/georgia_headline.py
"""
import csv
import io
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request

from PIL import Image
from playwright.sync_api import expect, sync_playwright

from multistate_api import Sources, historical

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "analysis/georgia-headline/qa"
BASE = os.environ.get("TURNOUT_TEST_URL", "http://127.0.0.1:8743")
OUT.mkdir(parents=True, exist_ok=True)
REPORT = {"base": BASE, "checks": [], "javascript_errors": []}


def record(name, **evidence):
    REPORT["checks"].append({"check": name, **evidence})
    print(name, flush=True)


def api(query):
    with urllib.request.urlopen(BASE + "/api/states/ga?" + urllib.parse.urlencode(query), timeout=90) as response:
        return json.load(response)


def ready(page, axis="race", method=None, date=None):
    page.wait_for_function("""e=>States.id==='ga'&&!States.busy&&States.view?.classification===e.axis
        &&States.classification===e.axis&&(!e.method||States.view.method===e.method)
        &&(!e.date||States.date===e.date)""", arg={"axis": axis, "method": method, "date": date}, timeout=120000)
    expect(page.locator("#state-error")).to_be_hidden()


def image(page, key, name):
    with page.expect_download(timeout=60000) as event:
        page.locator(f'[data-state-image="{key}"]').click()
    path = OUT / name
    event.value.save_as(path)
    with Image.open(path) as picture:
        assert (picture.width == 1600 and 800 <= picture.height <= 2000)
        assert picture.convert("RGB").getextrema() != ((255, 255),) * 3
    return event.value.suggested_filename


def run():
    source = Sources("ga")
    through = source.data["through"]
    # Every published category is a voter count, summed across matched counties;
    # no Census share or county bucket membership enters this oracle.
    assertions = 0
    for method in ("in_person", "mail", "total"):
        for axis in ("race", "age", "sex"):
            view = api({"method": method, "classification": axis, "date": through})
            assert view["classification"] == axis
            for bucket in view["buckets"]:
                for point in bucket["series"]:
                    for measure in ("daily", "cumulative"):
                        old = new = 0
                        members = []
                        for county in source.counties:
                            a = source.value(2024, historical(point["date_2026"]), county, method, measure)
                            b = source.value(2026, point["date_2026"], county, method, measure)
                            a = a[1].get(axis, {}).get(bucket["label"]) if a else None
                            b = b[1].get(axis, {}).get(bucket["label"]) if b else None
                            if a is not None and (b is not None or point["future"]):
                                members.append(county)
                                old += a
                                new += b or 0
                        assert point[measure + "_members"] == members
                        assert point[measure + "_2024"] == (old if members else None)
                        assert point[measure + "_2026"] == (new if members and not point["future"] else None)
                        assertions += 3
            for i, point in enumerate(view["series"]):
                for measure in ("daily", "cumulative"):
                    for year in (2024, 2026):
                        values = [b["series"][i][f"{measure}_{year}"] for b in view["buckets"]]
                        assert (sum(values) if all(v is not None for v in values) else None) == point[f"{measure}_{year}"]
                        assertions += 1
            record("statewide source demographic reconciliation", axis=axis, method=method)
    assert api({"date": through})["classification"] == "race"
    record("Georgia API defaults to actual voter race", assertions=assertions)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path="/usr/bin/chromium")
        page = browser.new_page(viewport={"width": 1512, "height": 1050}, accept_downloads=True, reduced_motion="reduce")
        page.set_default_timeout(45000)
        page.on("pageerror", lambda error: REPORT["javascript_errors"].append(str(error)))
        try:
            page.goto(BASE + "/#state=ga", wait_until="networkidle", timeout=180000)
            ready(page)
            assert page.locator("#states-workspace > .state-panel").first.get_attribute("id") == "state-panel-buckets"
            expect(page.locator("#state-panel-buckets h2")).to_have_text("Statewide voter race")
            expect(page.locator('[data-state-voter="race"]')).to_have_attribute("aria-pressed", "true")
            assert page.locator("#state-classification option").first.get_attribute("value") == "race"
            expect(page.locator("#state-panel-regression")).to_be_hidden()
            assert page.locator("#state-buckets h3").all_text_contents()[:3] == ["White", "Black", "Hispanic/Latino"]
            record("statewide race is the opening Georgia result")

            for axis in ("race", "age", "sex"):
                page.locator(f'[data-state-voter="{axis}"]').click()
                ready(page, axis)
                expect(page.locator(f'[data-state-voter="{axis}"]')).to_have_attribute("aria-pressed", "true")
                if axis == "age":
                    assert page.locator("#state-buckets h3").first.text_content() == "18-24"
                    assert page.locator("#state-buckets h3").all_text_contents()[-1] == "60-64"
                    page.locator("#state-bucket-next").click()
                    assert page.locator("#state-buckets h3").all_text_contents()[-1] == "Unknown"
                for width in (1512, 768, 390):
                    page.set_viewport_size({"width": width, "height": 1050})
                    page.wait_for_timeout(150)
                    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
                    page.screenshot(path=OUT / f"{axis}-{width}.png", full_page=True)
                page.set_viewport_size({"width": 1512, "height": 1050})
                name = image(page, "buckets", axis + ".png")
                assert axis in name
                record("headline demographic controls, image and responsive layouts", axis=axis)

            page.locator('[data-state-voter="race"]').click()
            page.locator('[data-state-voter="age"]').click()
            page.locator('[data-state-voter="sex"]').click()
            ready(page, "sex")
            expect(page.locator("#state-panel-buckets h2")).to_have_text("Statewide voter sex")
            record("rapid demographic changes retain the newest selection")
            page.locator("#state-method").select_option("total")
            ready(page, "sex", "total")
            page.locator("#state-measure").select_option("daily")
            assert page.evaluate("States.measure") == "daily"
            with page.expect_download() as event:
                page.locator('[data-state-csv="buckets"]').click()
            event.value.save_as(OUT / "sex-total.csv")
            rows = list(csv.DictReader(io.StringIO((OUT / "sex-total.csv").read_text())))
            assert {r["classification"] for r in rows} == {"sex"}
            assert {r["method"] for r in rows} == {"total"}
            assert {r["group"] for r in rows} == {"Female", "Male", "Other", "Unknown"}
            image(page, "buckets", "sex-total-daily.png")
            record("daily and all-ballot controls propagate to statewide exports", csv_rows=len(rows))
            page.locator("#state-measure").select_option("cumulative")
            future = page.evaluate("States.view.series.find(p=>p.future&&p.cumulative_2024!==null).date_2026")
            page.locator("#state-date").fill(future)
            page.locator("#state-date").dispatch_event("change")
            ready(page, "sex", "total", future)
            assert page.locator('#state-buckets circle[data-year="2026"]').count() > 0  # earlier observed days remain
            assert page.locator(f'#state-buckets circle[data-year="2026"][data-date="{future}"]').count() == 0
            assert page.locator(f'#state-buckets circle[data-year="2024"][data-date="{future}"]').count() > 0
            record("future demographic points remain historical-only")

            page.goto(BASE + f"/#state=ga&view=demographic&metric=non_white_vap&date={through}", wait_until="networkidle")
            ready(page, "demographic")
            assert page.locator("#states-workspace > .state-panel").first.get_attribute("id") == "state-panel-turnout"
            expect(page.locator("#state-panel-buckets h2")).to_have_text("Total non-white · age 18+")
            expect(page.locator("#state-voter-tabs")).to_be_hidden()
            record("explicit county composition deep links remain separate and usable")
            page.goto(BASE + f"/#state=ga&view=age&method=mail&measure=daily&date={through}", wait_until="networkidle")
            ready(page, "age", "mail", through)
            assert page.evaluate("States.measure") == "daily"
            page.reload(wait_until="networkidle")
            ready(page, "age", "mail", through)
            record("explicit demographic deep links survive reload")
            page.locator("#state-select").select_option("nc")
            page.wait_for_function("States.id==='nc'&&!States.busy&&States.view?.id==='nc'", timeout=120000)
            assert page.locator("#states-workspace > .state-panel").first.get_attribute("id") == "state-panel-turnout"
            page.locator("#state-select").select_option("ga")
            ready(page, "race")
            record("state picker returns to Georgia's statewide race headline")
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
