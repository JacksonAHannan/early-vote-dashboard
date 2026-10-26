"""Independent county-bucket arithmetic and real-browser analytical navigation QA.

Run with ``uv run --with playwright --with pillow python tests/county_buckets.py``.
The reference is county-level Census/presidential counts; turnout comes directly
from the official statewide aggregate API, independently of precinct cohorts.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("TURNOUT_TEST_URL", "http://127.0.0.1:8741")
OUT = ROOT.parent / "analysis/county-buckets/qa"


def get(path):
    with urlopen(BASE + path, timeout=60) as response:
        return json.load(response)


def classification(record, metric):
    """Use native counts and direct comparisons, with no analyzer reuse."""
    if metric is None:
        harris, trump = record.get("harris"), record.get("trump")
        if harris is None or trump is None or harris == trump or harris + trump <= 0:
            return None
        margin = 100 * (harris - trump) / (harris + trump)
        if margin >= 30:
            return 0
        if margin >= 15:
            return 1
        if margin >= 0:
            return 2
        if margin > -15:
            return 3
        if margin > -30:
            return 4
        return 5
    counts = record.get("counts", {})
    numerator = counts.get(metric["numerator"])
    denominator = counts.get(metric["denominator"])
    if (
        numerator is None
        or denominator is None
        or not math.isfinite(numerator)
        or not math.isfinite(denominator)
        or denominator <= 0
        or not 0 <= numerator <= denominator
    ):
        return None
    share = 100 * numerator / denominator
    return sum(share >= cut for cut in metric["cuts"])


def audit_reference(reference, statewide):
    native = {c["id"]: c for c in statewide["counties"]}
    records = reference["counties"]
    assert len(native) == len(records) == 254
    assert set(records) == set(native), "Reference and official county universes differ"
    assert len({record["fips"] for record in records.values()}) == 254
    assert {m["id"] for m in reference["metrics"]} == {
        "non_white_vap", "hispanic_vap", "black_vap", "asian_vap", "white_nh_vap", "under18"
    }
    for county_id, record in records.items():
        assert len(record["fips"]) == 5 and record["fips"].startswith("48")
        assert record["name"].casefold() == native[county_id]["name"].casefold()
        counts = record["counts"]
        assert counts["non_white"] == counts["population"] - counts["white_nh"]
        assert counts["non_white_vap"] == counts["vap"] - counts["white_nh_vap"]
        assert counts["under18"] == counts["population"] - counts["vap"]
        assert all(classification(record, metric) is not None for metric in reference["metrics"])
    assert reference["sources"], "County classifiers require provenance"


def expected_ids(statewide, reference, metric, measure, selected_day, observed):
    classified = {
        c["id"]: classification(reference["counties"].get(c["id"], {}), metric)
        for c in statewide["counties"]
    }
    prefix = "votes" if measure == "daily" else "cumulative"
    included = [
        c["id"] for c in statewide["counties"]
        if classified[c["id"]] is not None
        and c["days"][selected_day-1][f"{prefix}_2024"] is not None
        and (selected_day > observed or c["days"][selected_day-1][f"{prefix}_2026"] is not None)
    ]
    return classified, included


def expected_value(native, ids, day_index, year, measure, observed):
    if not ids or (year == 2026 and day_index >= observed):
        return None
    key = f'{"votes" if measure == "daily" else "cumulative"}_{year}'
    values = [native[county_id]["days"][day_index][key] for county_id in ids]
    return None if any(v is None for v in values) else sum(values)


def inspect_png(path):
    from PIL import Image

    with Image.open(path) as image:
        assert image.format == "PNG" and (image.width == 1600 and 800 <= image.height <= 2000)
        assert image.convert("RGBA").getpixel((0, 0))[3] == 255
        colors = Counter(image.convert("RGB").get_flattened_data())
        assert sum(n for color, n in colors.items() if max(color) - min(color) > 35) > 100


def api_audit(reference, statewide):
    native = {c["id"]: c for c in statewide["counties"]}
    observed = (date.fromisoformat(statewide["through"]) - date(2026, 10, 19)).days + 1
    assert 1 <= observed <= 12
    views = cells = county_rows = 0
    metrics = [("partisan", None)] + [("demographic", m) for m in reference["metrics"]]
    for kind, metric in metrics:
        metric_id = "presidential_margin" if metric is None else metric["id"]
        classified, _ = expected_ids(statewide, reference, metric, "daily", 1, observed)
        membership = {n:{m:expected_ids(statewide, reference, metric, m, n, observed)[1] for m in ("daily","cumulative")} for n in range(1,13)}
        for selected_day in range(1, observed + 1):
            daily_ids=membership[selected_day]["daily"]
            cumulative_ids=membership[selected_day]["cumulative"]
            query = urlencode({"view": kind, "metric": metric_id, "day": selected_day})
            view = get("/api/county-buckets?" + query)
            context = (kind, metric_id, selected_day)
            assert view["generated_at"] == statewide["generated_at"], (context, "source changed during audit")
            assert view["through"] == statewide["through"]
            assert view["day"] == selected_day and view["observed_days"] == observed
            assert view["view"] == kind and view["metric"] == metric_id
            assert len(view["buckets"]) == (6 if metric is None else 5)
            assert len(view["counties"]) == 254
            coverage = view["coverage"]
            assert coverage["total_counties"] == 254
            assert coverage["classified_counties"] == sum(b is not None for b in classified.values())
            assert coverage["included_counties"] == daily_ids, (context, "daily coverage")
            assert coverage["cumulative_included_counties"] == cumulative_ids, (context, "cumulative coverage")
            assert coverage["groups"] == len(daily_ids)
            assert coverage["cumulative_groups"] == len(cumulative_ids)
            assert view["reference_sources"] and view["turnout_sources"]
            for index, bucket in enumerate(view["buckets"] + [view["totals"]]):
                target = None if index == len(view["buckets"]) else index
                members = {
                    "daily": [county_id for county_id in daily_ids if target is None or classified[county_id] == target],
                    "cumulative": [county_id for county_id in cumulative_ids if target is None or classified[county_id] == target],
                }
                assert bucket["county_ids"] == members["daily"]
                assert bucket["cumulative_county_ids"] == members["cumulative"]
                assert bucket["groups"] == len(members["daily"])
                assert bucket["cumulative_groups"] == len(members["cumulative"])
                assert len(bucket["days"]) == 12
                for day_index, row in enumerate(bucket["days"]):
                    assert row["day"] == day_index + 1
                    for year, start_day in ((2024, 21), (2026, 19)):
                        stamp = date(year, 10, start_day) + timedelta(days=day_index)
                        assert row[f"date_{year}"] == stamp.isoformat()
                        for measure in ("daily", "cumulative"):
                            point_members=[id for id in membership[day_index+1][measure] if target is None or classified[id]==target]
                            field="county_ids" if measure=="daily" else "cumulative_county_ids"
                            assert row[field]==point_members,(context,index,day_index+1,measure,"date-specific membership")
                            expected = expected_value(native, point_members, day_index, year, measure, observed)
                            actual = row[f"{measure}_{year}"]
                            assert actual == expected, (context, index, day_index + 1, year, measure, actual, expected)
                            cells += 1
            for row in view["counties"]:
                county_id = row["id"]
                record = reference["counties"][county_id]
                raw = native[county_id]["days"][selected_day - 1]
                assert row["bucket"] == classified[county_id], (context, county_id, "classification")
                assert row["daily_included"] == (county_id in daily_ids)
                assert row["cumulative_included"] == (county_id in cumulative_ids)
                assert row["fips"] == record["fips"]
                for year in (2024, 2026):
                    assert row[f"votes_{year}"] == raw[f"cumulative_{year}"]
                    assert row[f"daily_{year}"] == raw[f"votes_{year}"]
                    assert row[f"registered_{year}"] == raw[f"registered_{year}"]
                old, new = raw["cumulative_2024"], raw["cumulative_2026"]
                ratio = new / old if old and new is not None else None
                assert row["ratio"] == ratio
                if classified[county_id] is not None:
                    share = (
                        record["harris"] / (record["harris"] + record["trump"]) * 100
                        if metric is None
                        else record["counts"][metric["numerator"]] / record["counts"][metric["denominator"]] * 100
                    )
                    assert math.isclose(row["share"], share, rel_tol=1e-12, abs_tol=1e-10)
                county_rows += 1
            views += 1
    return {
        "views": views,
        "daily_cumulative_cells": cells,
        "county_rows": county_rows,
        "observed_days": observed,
        "daily_counties": len(daily_ids),
        "cumulative_counties": len(cumulative_ids),
    }


def browser_audit(reference):
    from playwright.sync_api import expect, sync_playwright

    javascript_errors = []
    exported = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path="/usr/bin/chromium"
        )
        page = browser.new_page(
            viewport={"width": 1512, "height": 1050}, reduced_motion="reduce"
        )
        page.on("pageerror", lambda error: javascript_errors.append(str(error)))
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_function("window.CountyView?.view&&Tracking.state&&window.Navigation")
        expect(page.locator("#county-daily-charts")).to_be_visible()
        expect(page.locator("#daily-charts")).to_be_hidden()
        expect(page.locator(".county-daily-panel")).to_have_count(6)
        expect(page.locator("#statewide-table tbody tr")).to_have_count(254)
        observed = page.evaluate("CountyView.view.observed_days")

        # Grain navigation owns scope; precinct and county filters stay independent.
        page.locator("#precincts-tab").click()
        page.wait_for_function("Navigation.level==='precincts'&&Tracking.view")
        expect(page.locator("#daily-charts")).to_be_visible()
        expect(page.locator("#county-daily-charts")).to_be_hidden()
        page.locator("#precinct-explore-tab").click()
        page.wait_for_function("Navigation.section==='explore'&&Atlas.layer")
        expect(page.locator("#county-map")).to_be_visible()
        expect(page.locator("#daily-charts")).to_be_hidden()
        dot = page.locator('.regression-point[tabindex="0"]').first
        selected = dot.get_attribute("data-id")
        dot.focus()
        dot.press("Enter")
        page.wait_for_function(
            "(id)=>Atlas.active&&`${Atlas.active.county}:${Atlas.active.group_index}`===id",
            arg=selected,
        )
        page.locator("#demographic-mode").click()
        page.locator("#metric").select_option("black_vap")
        page.wait_for_function("demoReady()&&mode==='demographic'")
        page.locator("#precinct-trends-tab").click()
        expect(page.locator("#daily-charts")).to_be_visible()
        expect(page.locator("#county-map")).to_be_hidden()
        page.locator("#counties-tab").click()
        page.wait_for_function("Navigation.level==='counties'&&CountyView.view")
        assert page.evaluate("CountyView.mode") == "partisan"

        # A county bucket filters true county records, including counties without precincts.
        page.locator('#county-bucket-summary [data-county-bucket="0"]').click()
        expect(page.locator("#county-bucket-clear")).to_be_visible()
        ids = page.locator("#statewide-table tbody [data-state-county]").evaluate_all(
            "els=>els.map(e=>e.dataset.stateCounty)"
        )
        assert ids and all(classification(reference["counties"][county_id], None) == 0 for county_id in ids)
        for measure in ("daily", "cumulative"):
            page.locator("#statewide-measure").select_option(measure)
            bucket = page.evaluate("CountyView.view.buckets[0]")
            for row in bucket["days"]:
                hit = page.locator(f'#statewide-chart .timeline-hit[data-day="{row["day"]}"]')
                if row[f"{measure}_2024"] is None and row[f"{measure}_2026"] is None:
                    expect(hit).to_have_count(0)
                    continue
                label = hit.get_attribute("aria-label")
                for year in (2024, 2026):
                    value = row[f"{measure}_{year}"]
                    stamp = date.fromisoformat(row[f"date_{year}"]).strftime("%b %-d")
                    expected = "—" if value is None else f"{value:,}"
                    assert f"{year} {stamp}: {expected}" in label, (measure, row["day"], year, label, expected)
        page.locator("#county-bucket-clear").click()
        expect(page.locator("#statewide-table tbody tr")).to_have_count(254)
        expect(page.locator("#statewide-county-title")).to_contain_text("Texas")
        page.locator("#statewide-search").fill("Harris")
        page.locator('[data-state-county="harris"]').click()
        expect(page.locator("#statewide-county-title")).to_contain_text("Harris")
        expect(page.locator("#statewide-precincts")).to_be_visible()
        expect(page.locator('#statewide-chart .timeline-dot[data-year="2024"]')).to_have_count(12)
        county_only=page.evaluate('Tracking.state.counties.find(c=>!data.counties.some(p=>p.id===c.id))')
        assert county_only, "County-only detail fixture"
        page.locator("#statewide-search").fill(county_only["name"])
        page.locator(f'[data-state-county="{county_only["id"]}"]').click()
        expect(page.locator("#statewide-precincts")).to_be_hidden()
        page.locator("#statewide-search").fill("Travis")
        page.locator('[data-state-county="travis"]').click()
        expect(page.locator("#statewide-precincts")).to_be_visible()
        page.locator("#statewide-precincts").click()
        page.wait_for_function("Navigation.level==='precincts'&&Navigation.section==='explore'&&county==='travis'&&Atlas.county==='travis'")
        expect(page.locator("#county-map")).to_be_visible()
        expect(page.locator("#county")).to_have_value("travis")
        page.locator("#counties-tab").click()
        page.locator("#statewide-reset").click()
        page.locator("#statewide-search").fill("")

        # Daily versus cumulative changes the comparison cohort and future years stay blank.
        page.locator("#county-bucket-measure").select_option("cumulative")
        page.wait_for_function("CountyView.measure==='cumulative'")
        cumulative_counties = page.evaluate("CountyView.view.coverage.cumulative_groups")
        expect(page.locator("#county-summary-cutoff")).to_contain_text(f"{cumulative_counties} counties")
        for panel in page.locator(".county-daily-panel").all():
            if panel.locator("svg").count():
                assert panel.locator('.timeline-dot[data-year="2026"]').count() <= observed
                assert panel.locator('.timeline-dot[data-year="2024"]').count() == 12
        page.locator("#county-demographic").click()
        expect(page.locator("#county-metric option")).to_have_count(6)
        page.locator("#county-metric").select_option("non_white_vap")
        page.wait_for_function("CountyView.view?.metric==='non_white_vap'")
        expect(page.locator(".county-daily-panel")).to_have_count(6)
        assert page.evaluate("metricId") == "black_vap", "County metric leaked into precinct controls"
        with page.expect_download() as download:
            page.locator("#county-bucket-download").click()
        csv_path = OUT / "county-buckets-non-white.csv"
        download.value.save_as(str(csv_path))
        rows = list(csv.DictReader(csv_path.open()))
        assert len(rows) == 72
        exported_view = page.evaluate("CountyView.view")
        exported_buckets = {b["label"]: b for b in exported_view["buckets"] + [exported_view["totals"]]}
        for row in rows:
            assert row["geography"] == "county"
            assert row["view"] == "demographic" and row["metric"] == "non_white_vap"
            bucket = exported_buckets[row["bucket"]]
            expected = bucket["days"][int(row["day"]) - 1]
            assert int(row["daily_counties"]) == expected["groups"]
            assert int(row["cumulative_counties"]) == expected["cumulative_groups"]
            assert row["daily_county_ids"].split(";") == expected["county_ids"] or not row["daily_county_ids"] and not expected["county_ids"]
            assert row["cumulative_county_ids"].split(";") == expected["cumulative_county_ids"] or not row["cumulative_county_ids"] and not expected["cumulative_county_ids"]
            for key in ("daily_2024", "daily_2026", "cumulative_2024", "cumulative_2026"):
                assert row[key] == ("" if expected[key] is None else str(expected[key]))
        page.screenshot(path=str(OUT / "counties-demographic-desktop.png"), full_page=True)

        # Every new county visual exports its real rendered data as an opaque social image.
        keys = ["county-daily", "county-summary", "county-table", "county-trend"]
        keys += page.locator('.county-daily-panel [data-image]').evaluate_all(
            "els=>els.map(e=>e.dataset.image)"
        )
        assert len(keys) == len(set(keys))
        for key in keys:
            with page.expect_download(timeout=45000) as download:
                page.locator(f'[data-image="{key}"]').click()
            path = OUT / f"export-{key}.png"
            download.value.save_as(str(path))
            inspect_png(path)
            if key == "county-summary":
                text = subprocess.run(["tesseract", str(path), "stdout"], capture_output=True, text=True, check=True).stdout.replace(",", "")
                for item in exported_view["buckets"]:
                    cutoff = item["days"][exported_view["day"] - 1]
                    for field in ("cumulative_2024", "cumulative_2026"):
                        if cutoff[field] is not None:
                            assert str(cutoff[field]) in text, ("clipped summary value", item["label"], field, cutoff[field], text)
            exported.append(key)

        # Keyboard fold state survives grain navigation, with no hidden-tab map jump.
        panel = page.locator("#county-daily-charts").locator(
            "xpath=ancestor::*[@data-collapsible][1]"
        )
        toggle = panel.locator("[data-panel]")
        toggle.focus()
        toggle.press("Enter")
        expect(page.locator("#county-daily-charts")).to_be_hidden()
        page.locator("#precincts-tab").click()
        page.locator("#counties-tab").click()
        expect(page.locator("#county-daily-charts")).to_be_hidden()
        toggle.click()
        expect(page.locator("#county-daily-charts")).to_be_visible()

        for width in (1512, 768, 390):
            page.set_viewport_size({"width": width, "height": 1000})
            page.wait_for_timeout(300)
            page.evaluate("window.scrollTo(0,0)")
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth"), width
            page.screenshot(path=str(OUT / f"counties-{width}.png"), full_page=True)
            page.screenshot(path=str(OUT / f"counties-viewport-{width}.png"))
            page.locator("#precincts-tab").click()
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth"), ("precinct", width)
            page.locator("#counties-tab").click()
        assert not javascript_errors, javascript_errors
        browser.close()
    return {
        "javascript_errors": javascript_errors,
        "visual_downloads": exported,
        "checks": [
            "county and precinct workspace navigation with independent filters",
            "precinct Trends and Explore retain linked regression/map selection",
            "county bucket filters table and exact daily/cumulative aggregate timeline",
            "data-derived county-only detail and Harris/Travis precinct shortcuts",
            "six demographic choices including total non-white",
            "date-specific cumulative cohort count and future 2026 gaps",
            "72 exported CSV rows match rendered engine values",
            "ten PNG downloads have 1600px width, adaptive height and opaque colored data",
            "keyboard collapse state survives workspace navigation",
            "1512, 768 and 390 pixel layouts do not overflow",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-only", action="store_true", help="Audit official counts without launching Chromium")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    reference = json.loads((ROOT / "data/county-reference.json").read_text())
    statewide = get("/api/statewide")
    audit_reference(reference, statewide)
    report = {"status": "passed", "api": api_audit(reference, statewide)}
    if not args.api_only:
        report["browser"] = browser_audit(reference)
    report["checks"] = [
        "all 254 county identities, FIPS and Census complements",
        "six partisan and six demographic metric classifications from native counts",
        "independent maximum daily and cumulative reporting cohorts at each date",
        "all twelve aligned calendar days and future 2026 nulls",
        "official cumulative totals kept separate from native daily counts",
        "all selected-day county records retained outside analytical cohorts",
    ]
    (OUT / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
