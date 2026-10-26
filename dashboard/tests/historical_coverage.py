"""Independent county/day coverage, recovered series and real browser/export QA.

TURNOUT_TEST_URL=http://127.0.0.1:8743 uv run --with playwright --with pillow python dashboard/tests/historical_coverage.py
Set TURNOUT_JOINT_STATIC=1 for Pages. Voter records are never requested.
"""
import importlib.util
import json
import os
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


t = module("matrix_transport", Path(__file__).with_name("joint_matrix.py"))
oracle = module("coverage_oracle", ROOT / "dashboard/scripts/audit_precinct_coverage.py")
OUT = ROOT / "analysis/historical-coverage" / os.environ.get("TURNOUT_TEST_TAG", "local")
OUT.mkdir(parents=True, exist_ok=True)
snapshot = t.api("/api/data")
audit = oracle.audit(snapshot)
(OUT / "snapshot.json").write_text(json.dumps(snapshot))
(OUT / "coverage.json").write_text(json.dumps(audit, indent=2) + "\n")
by_county = {c["id"]: c for c in snapshot["counties"]}

# The immutable, reviewed source must replace the conflicting archive as a whole.
edition = json.loads((ROOT / "dashboard/recovery/texas-20261025.json").read_text())
for item in edition["observations"]:
    expected = item["source"]
    sources = by_county[expected["county"]]["sources"]
    actual = next(s for s in sources if (s["date"], s.get("cumulative", False)) == (expected["date"], False))
    assert actual["sha256"] not in item["supersedes_sha256"]
    if actual["sha256"] == expected["sha256"]:
        assert actual["counts"] == expected["counts"]
        if expected["county"] == "harris":
            assert actual["complete"]
        elif expected["county"] in ("houston", "leon"):
            assert not actual["complete"]

# Daily history must use the same source recovery as the snapshot and tables.
# Independently sum eligible geographic groups from the snapshot, then compare
# both the demographic view and the separately cached cumulative timeline.
census = t.api("/api/demographics")
primary = t.api("/api/primary")
cases = [("demographic", "hispanic_vap", census), ("primary", "primary_dem_share", primary)]
series_cases = 0
daily_cases = 0


def dated_daily_snapshot(day):
    """The four recovered counties publish actual daily residence reports.

    Unlike cumulative availability, a daily pair needs only this date. Do not
    restrict it to the cumulative snapshot's eligible groups.
    """
    counties = []
    for county in ("harris", "ellis", "houston", "leon"):
        c = by_county[county]
        counts = {}
        for year, member in [(2024, "old"), (2026, "new")]:
            source = oracle.exact(c["sources"], year, day, False)
            counts[year] = dict(source["counts"]) if source else {}
            if source and source.get("complete"):
                for g in c["reference_groups"]:
                    for precinct in g[member]:
                        counts[year].setdefault(precinct, 0)
        groups = []
        for g in c["reference_groups"]:
            available = all(p in counts[2024] for p in g["old"]) and all(p in counts[2026] for p in g["new"])
            groups.append(dict(g, available=available,
                               votes_2024=sum(counts[2024].get(p, 0) for p in g["old"]),
                               votes_2026=sum(counts[2026].get(p, 0) for p in g["new"])))
        counties.append({"id": county, "periods": [{"day": day, "groups": groups}]})
    return {"counties": counties}


for view, metric_id, reference in cases:
    metric = next(m for m in reference["metrics"] if m["id"] == metric_id)
    scopes = ["all", "harris", "ellis", "houston", "leon"]
    timelines = {county: t.api(f"/api/trends?county={county}&cohort=matched&view={view}&metric={metric_id}") for county in scopes}
    for day in range(1, 6):
        expected = t.oracle(snapshot, reference, metric, day, "matched")
        daily = t.oracle(dated_daily_snapshot(day), reference, metric, day, "matched")
        actual = t.api(f"/api/demographic-view?day={day}&cohort=matched&view={view}&metric={metric_id}")
        for county in scopes:
            bins = actual["views"][county]["bins"]
            for i, row in enumerate(expected[county]):
                counts = [sum(cell[k] for cell in row) for k in range(3)]
                assert [bins[i][k] for k in ["groups", "votes_2024", "votes_2026"]] == counts
                point = next(p for p in timelines[county]["buckets"][i]["days"] if p["day"] == day)
                assert point["cumulative_groups"] == counts[0], (county, day, view, i)
                if counts[0]:
                    assert [point["cumulative_2024"], point["cumulative_2026"]] == counts[1:]
                else:
                    assert point["cumulative_2026"] is None
                series_cases += 1
                if county != "all":
                    daily_counts = [sum(cell[k] for cell in daily[county][i]) for k in range(3)]
                    assert point["daily_groups"] == daily_counts[0], (county, day, view, i, "daily")
                    if daily_counts[0]:
                        assert [point["daily_2024"], point["daily_2026"]] == daily_counts[1:]
                    else:
                        assert point["daily_2026"] is None
                    daily_cases += 1
            for bucket in timelines[county]["buckets"]:
                assert all(p["cumulative_2026"] is None for p in bucket["days"] if p["day"] > snapshot["days"])

errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
    try:
        page = browser.new_page(viewport={"width": 1512, "height": 1100}, reduced_motion="reduce", accept_downloads=True)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(t.BASE + "#precinct-trends", wait_until="networkidle", timeout=120000)
        page.wait_for_function("data&&data.counties.length>200", timeout=120000)
        page.locator("#county").select_option("harris")
        for day in range(1, 6):
            page.get_by_role("button", name=f"Day {day}", exact=True).click()
            expect(page.locator("#matrix tfoot")).to_contain_text("1,224 / 1,224")
            summary = audit["summaries"][day - 1]
            expect(page.locator("#matrix tfoot .matrix-total").last).to_have_text(f'{summary["available_precincts"]:,} / {summary["total_precincts"]:,}')
        page.get_by_role("button", name="Day 3", exact=True).click()
        page.locator("#matrix").screenshot(path=str(OUT / "harris-day3-table.png"))
        with page.expect_download(timeout=120000) as download:
            page.locator('[data-image="matrix"]').click()
        image = OUT / "harris-day3-table-export.png"
        download.value.save_as(image)
        with Image.open(image) as value:
            assert value.width >= 1200 and value.height >= 600
        page.screenshot(path=str(OUT / "desktop.png"), full_page=True)
        assert not errors, errors
    finally:
        browser.close()

report = {"url": t.BASE, "static": t.STATIC, "county_days": len(audit["counties"]), "series_cases": series_cases,
          "daily_cases": daily_cases, "coverage": audit["summaries"], "javascript_errors": errors, "passed": True}
(OUT / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({k: v for k, v in report.items() if k != "coverage"}))
