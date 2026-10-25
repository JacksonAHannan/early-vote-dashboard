"""Independent precinct-expansion data, API, linked-map and export acceptance.

Run: uv run --with playwright --with pillow python dashboard/tests/expansion.py
Use --offline for local source/geometry/count audits, or --api-only to omit UI.
TURNOUT_TEST_URL defaults to the production localhost service.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import date, datetime, timedelta
import hashlib
import io
import json
import math
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
BASE = os.environ.get("TURNOUT_TEST_URL", "http://127.0.0.1:8741")
OUT = PROJECT / "analysis/precinct-expansion/qa"
ORIGINAL = {"travis", "dallas", "montgomery", "bell", "hays", "ellis", "mclennan", "hockley", "madison"}


def read(path):
    return json.loads(Path(path).read_text())


def input_manifest(references):
    paths = {ROOT / f"data/{name}.json" for name in ["reference", "demographics", "latest", "history", "primary", "statewide", "county-reference"]}
    paths |= {PROJECT / "sources/precinct-expansion" / name for name in ["admission-candidates.json", "discovery/inventory.json", "discovery/nueces-native-2026-audit.json"]}
    for reference in references:
        county = reference["id"]
        paths.add(ROOT / f"data/maps/{county}.geojson")
        paths.add(PROJECT / reference["references"]["presidential"]["path"])
        paths.add(ROOT / f"data/history-cache/{county}/2024-series.json")
        paths |= {ROOT / f"data/cache/{county}/{year}-series.json" for year in [2024, 2026]}
    manifest = {}
    for path in sorted(paths):
        if path.exists():
            with path.open("rb") as file:
                manifest[str(path.relative_to(PROJECT))] = hashlib.file_digest(file, "sha256").hexdigest()
        else:
            manifest[str(path.relative_to(PROJECT))] = None
    return manifest


def get(path):
    with urlopen(BASE + path, timeout=120) as response:
        return json.load(response)


def beginning(year):
    return date(year, 10, 21 if year == 2024 else 19)


def cutoff(year, day):
    return str(beginning(year) + timedelta(days=day - 1))


def margin_bucket(harris, trump):
    if harris == trump:
        return None
    margin, total = abs(harris - trump) * 100, harris + trump
    band = 2 if margin >= total * 30 else 1 if margin >= total * 15 else 0
    return 2 - band if harris > trump else 3 + band


def total_sources(sources, year, day):
    """An exact cumulative cutoff wins; a partial daily prefix is unavailable."""
    through = cutoff(year, day)
    direct = [s for s in sources if s.get("cumulative", False) and s["date"] == through]
    assert len(direct) <= 1
    if direct:
        return direct[0]["counts"]
    daily = [s for s in sources if not s.get("cumulative", False) and cutoff(year, 1) <= s["date"] <= through]
    dates = [s["date"] for s in daily]
    assert len(dates) == len(set(dates)), "duplicate daily observation"
    if set(dates) != {cutoff(year, n) for n in range(1, day + 1)}:
        return None
    counts = Counter()
    for source in daily:
        counts.update(source["counts"])
    return dict(counts)


def close(a, b, context):
    assert a is not None and b is not None and math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-5), (context, a, b)


def check_cohort(actual, rows, context):
    old, new = sum(g["votes_2024"] for g in rows), sum(g["votes_2026"] for g in rows)
    assert (actual["groups"], actual["votes_2024"], actual["votes_2026"]) == (len(rows), old, new), context
    if old:
        close(actual["ratio"], new / old, context)
    else:
        assert actual["ratio"] is None, context


def audit_local(snapshot, references, census):
    assert snapshot["reference_sha256"] == hashlib.sha256((ROOT / "data/reference.json").read_bytes()).hexdigest(), "snapshot uses another geography reference"
    refs = {r["id"]: r for r in references}
    records = {c["id"]: c for c in snapshot["counties"]}
    admitted = set(read(PROJECT / "sources/precinct-expansion/admission-candidates.json"))
    inventory = {c["county"]: c for c in read(PROJECT / "sources/precinct-expansion/discovery/inventory.json")["candidates"]}
    assert {"tarrant", "harris", "collin"} <= admitted
    assert set(refs) == set(records) == ORIGINAL | admitted, "reference/snapshot/admission universes differ"
    assert set(census["counties"]) == set(refs), "expanded Census classifiers missing"
    assert len(refs) > len(ORIGINAL), "expansion has not been built"
    county_reference = read(ROOT / "data/county-reference.json")["counties"]
    source_rows = period_count = group_count = map_features = census_cells = presidential_cells = 0
    unavailable = []
    for county_id, reference in refs.items():
        county = records[county_id]
        old_universe = [p for g in reference["groups"] for p in g["old"]]
        new_universe = [p for g in reference["groups"] for p in g["new"]]
        assert len(old_universe) == len(set(old_universe)) and len(new_universe) == len(set(new_universe)), county_id
        assert all(g["old"] and g["new"] for g in reference["groups"]), county_id
        if county_id in admitted:
            path = PROJECT / f"sources/precinct-expansion/geography/{county_id}/precinct-universe.csv"
            universe = list(csv.DictReader(path.open()))
            assert set(old_universe) == {r["precinct"] for r in universe if r["year"] == "2024"}, county_id
            assert set(new_universe) == {r["precinct"] for r in universe if r["year"] == "2026"}, county_id
            assert set(reference["presidential"]) <= set(old_universe), (county_id, "foreign presidential geography")
            provenance = reference["references"]["presidential"]
            source_path = PROJECT / provenance["path"]
            assert hashlib.sha256(source_path.read_bytes()).hexdigest() == provenance["sha256"], (county_id, "presidential source hash")
            source_rows_pres = list(csv.DictReader(source_path.open()))
            source_returns = {row["precinct"]: {field: int(row[field]) for field in ["harris", "trump"]} for row in source_rows_pres}
            assert len(source_returns) == len(source_rows_pres), (county_id, "duplicate presidential source precinct")
            assert source_returns == reference["presidential"], (county_id, "presidential source / reference mismatch")
            assert provenance["qualification"], (county_id, "presidential availability qualification missing")
            presidential_cells += len(source_returns) * 2
        caches = []
        for year in (2024, 2026):
            path = ROOT / f"data/cache/{county_id}/{year}-series.json"
            if path.exists():
                caches.extend(read(path))
        cached = {(s["date"], s.get("cumulative", False)): s for s in caches}
        if county_id in admitted:
            observed_cache = {
                key for key in cached
                if any(cutoff(year, 1) <= key[0] <= cutoff(year, snapshot["days"]) for year in [2024, 2026])
            }
            snapshot_keys = {(s["date"], s.get("cumulative", False)) for s in county["sources"]}
            assert observed_cache <= snapshot_keys, (county_id, "available partial source observations discarded", observed_cache - snapshot_keys)
        for source in county["sources"]:
            assert source["county"] == county_id
            assert source["source"].startswith("https://") and len(source["sha256"]) == 64
            assert all(isinstance(v, int) and v >= 0 for v in source["counts"].values())
            counterpart = cached.get((source["date"], source.get("cumulative", False)))
            if county_id in admitted:
                assert counterpart is not None, (county_id, source["date"], "uncached snapshot source")
            if counterpart is not None:
                assert source["counts"] == counterpart["counts"], (county_id, source["date"], "snapshot/source count drift")
                assert source["sha256"] == counterpart["sha256"], (county_id, "source hash drift")
            source_rows += len(source["counts"])
        if county_id in inventory:
            reports = {r["date"]: r for y in inventory[county_id]["years"].values() for r in y.get("reports", [])}
            for source in caches:
                if source["date"] in reports and not source.get("cumulative", False):
                    report = reports[source["date"]]
                    assert sum(source["counts"].values()) == report["votes"], (county_id, source["date"], "discovery raw-scope control")
                    assert source["sha256"] == report["sha256"]
        periods = {p["day"]: p for p in county["periods"]}
        assert len(periods) == len(county["periods"])
        exact = {tuple(pair) for pair in reference["exact_pairs"]}
        for day in range(1, snapshot["days"] + 1):
            source_basis = caches if county_id in admitted else county["sources"]
            old = total_sources(source_basis, 2024, day)
            new = total_sources(source_basis, 2026, day)
            if old is None or new is None:
                assert day not in periods, (county_id, day, "partial reports became a complete cutoff")
                unavailable.append([county_id, day])
                continue
            assert day in periods, (county_id, day, "valid source cutoff omitted")
            period = periods[day]
            assert period["through_2024"] == cutoff(2024, day) and period["through_2026"] == cutoff(2026, day)
            assert period["county_2024"] == sum(old.values()) and period["county_2026"] == sum(new.values()), (county_id, day)
            assert len(period["groups"]) == len(reference["groups"])
            expected = []
            for group, actual in zip(reference["groups"], period["groups"]):
                assert actual["old"] == group["old"] and actual["new"] == group["new"]
                votes_old = sum(old.get(p, 0) for p in group["old"])
                votes_new = sum(new.get(p, 0) for p in group["new"])
                assert (actual["votes_2024"], actual["votes_2026"]) == (votes_old, votes_new), (county_id, day, group)
                returns = [reference["presidential"].get(p) for p in group["old"]]
                bands = [None if r is None else margin_bucket(r["harris"], r["trump"]) for r in returns]
                band = bands[0] if len(set(bands)) == 1 else None
                unchanged = band is not None and len(group["old"]) == len(group["new"]) == 1 and (group["old"][0], group["new"][0]) in exact
                assert actual["bucket"] == band and actual["unchanged"] == unchanged, (county_id, day, "partisan eligibility")
                assert actual["harris"] == sum(r["harris"] for r in returns if r is not None)
                assert actual["trump"] == sum(r["trump"] for r in returns if r is not None)
                if any(r is None for r in returns):
                    assert actual["reason"].startswith("Missing"), (county_id, "missing return fabricated")
                expected.append(actual)
                group_count += 1
            for year, counts, universe in [(2024, old, set(old_universe)), (2026, new, set(new_universe))]:
                outside = sum(v for p, v in counts.items() if p not in universe)
                assert period[f"unassigned_{year}"] == outside, (county_id, day, year)
                assert sum(g[f"votes_{year}"] for g in expected) + outside == period[f"county_{year}"]
            for cohort in ["matched", "unchanged"]:
                selected = [g for g in expected if g["bucket"] is not None and (cohort == "matched" or g["unchanged"])]
                check_cohort(period[cohort], selected, (county_id, day, cohort))
                for index, bucket in enumerate(period["buckets"]):
                    check_cohort(bucket[cohort], [g for g in selected if g["bucket"] == index], (county_id, day, cohort, index))
            period_count += 1
        geo = read(ROOT / f"data/maps/{county_id}.geojson")
        features = geo["features"]
        assert len(features) == len(new_universe), (county_id, "map feature count")
        assert {f["properties"]["precinct"] for f in features} == set(new_universe)
        for feature in features:
            props = feature["properties"]
            assert props["county"] == county_id and props["precinct"] in reference["groups"][props["group"]]["new"]
            assert feature["geometry"]["type"] in ["Polygon", "MultiPolygon"] and feature["geometry"]["coordinates"]
        map_features += len(features)
        classification = census["counties"][county_id]
        assert set(classification["precincts"]) == set(new_universe), (county_id, "Census / native map join")
        for field, official in county_reference[county_id]["counts"].items():
            values = [p["counts"].get(field) for p in classification["precincts"].values()]
            assert all(v is not None and math.isfinite(v) and v >= 0 for v in values), (county_id, field)
            close(sum(values), classification["assigned_totals"][field], (county_id, field, "native Census sum"))
            close(classification["census_totals"][field], official, (county_id, field, "Census county control"))
            close(classification["assigned_totals"][field], official, (county_id, field, "Census conservation"))
            census_cells += len(values)
        for p in classification["precincts"].values():
            counts = p["counts"]
            close(counts["non_white_vap"], counts["vap"] - counts["white_nh_vap"], (county_id, "non-white complement"))
            close(counts["non_white"], counts["population"] - counts["white_nh"], (county_id, "non-white population"))
            close(counts["under18"], counts["population"] - counts["vap"], (county_id, "age complement"))
    tarrant_old = read(ROOT / "data/cache/tarrant/2024-series.json")
    tarrant_new = read(ROOT / "data/cache/tarrant/2026-series.json")
    assert len(tarrant_old) == 12 and sum(sum(s["counts"].values()) for s in tarrant_old) == 635101
    assert tarrant_old[0]["counts"].get("UNASSIGNED") == 1
    assert sum(s["counts"].get("UNASSIGNED", 0) for s in tarrant_old) == 1
    assert [sum(s["counts"].values()) for s in tarrant_new[:5]] == [50142, 50722, 48631, 46124, 50639]
    nueces_audit_path = PROJECT / "sources/precinct-expansion/discovery/nueces-native-2026-audit.json"
    if nueces_audit_path.exists():
        audit = read(nueces_audit_path)
        assert audit["parser_revision"] >= 2 and audit["independent_parsers_agree"]
        assert audit["parsed_rows"] == audit["unique_vuid"] == audit["independent_pdftotext_rows"] == audit["independent_early_voted_record_lines"]
        lengths = audit["vuid_token_lengths"]
        assert lengths.get("8", 0) > 0 and lengths.get("9", 0) > 0 and lengths.get("10", 0) > 0
        assert sum(lengths.values()) == audit["parsed_rows"], "short native VUID rows were discarded"
        sources = read(ROOT / "data/cache/nueces/2026-series.json")
        daily_controls = {row["date"]: row["county_in_person"] for row in audit["daily"]}
        for source in sources:
            assert sum(source["counts"].values()) == daily_controls[source["date"]], "Nueces native all-identifier-length control"
            assert source["sha256"] == audit["sha256"]
    return dict(counties=len(refs), added=len(admitted), source_precinct_cells=source_rows,
                periods=period_count, group_comparisons=group_count, map_features=map_features,
                census_cells=census_cells, presidential_source_cells=presidential_cells, unavailable_cutoffs=unavailable)


def resolved_sources(snapshot, history):
    result = {}
    for county in snapshot["counties"]:
        latest = {}
        for source in history.get("counties", {}).get(county["id"], {}).get("sources", []) + county["sources"]:
            key = source["date"], source.get("cumulative", False)
            stamp = datetime.fromisoformat(source["retrieved_at"].replace("Z", "+00:00"))
            if key not in latest or stamp >= latest[key][0]:
                latest[key] = stamp, source["counts"]
        years, issues = {}, []
        for year in [2024, 2026]:
            previous, days = {}, []
            for day in range(1, 13):
                if year == 2026 and day > snapshot["days"]:
                    days.append((None, None))
                    continue
                daily = latest.get((cutoff(year, day), False), (None, None))[1]
                direct = latest.get((cutoff(year, day), True), (None, None))[1]
                if daily is None and direct is not None and previous is not None:
                    delta = {p: direct.get(p, 0) - previous.get(p, 0) for p in direct.keys() | previous.keys()}
                    if any(v < 0 for v in delta.values()):
                        issues.append("negative cumulative difference")
                    else:
                        daily = {p: v for p, v in delta.items() if v}
                summed = None
                if previous is not None and daily is not None:
                    summed = previous.copy()
                    for precinct, votes in daily.items():
                        summed[precinct] = summed.get(precinct, 0) + votes
                if direct is not None and summed is not None and direct != summed:
                    issues.append("conflicting cumulative observation")
                cumulative = direct if direct is not None else summed
                days.append((daily, cumulative))
                previous = cumulative
            years[year] = days
        result[county["id"]] = years, issues
    return result


def demographic_bucket(group, classification, metric, county):
    native = classification["counties"].get(county, {}).get("precincts", {})
    numerator = denominator = 0
    for precinct in group["new"]:
        counts = native.get(precinct, {}).get("counts", {})
        n, d = counts.get(metric["numerator"]), counts.get(metric["denominator"])
        if n is None or d is None or not 0 <= n <= d:
            return None
        numerator += n
        denominator += d
    if denominator <= 0:
        return None
    return sum(100 * numerator / denominator >= edge for edge in metric["cuts"])


def audit_api(snapshot, census):
    assert get("/api/reference") == read(ROOT / "data/reference.json"), "live reference metadata differs from audited native geography"
    state = get("/api/statewide")
    saved_state = read(ROOT / "data/statewide.json")
    assert len(state["counties"]) == 254 and state["counties"] == saved_state["counties"]
    registered_cells = 0
    for county in state["counties"]:
        assert len(county["days"]) == 12
        for row in county["days"]:
            for year in [2024, 2026]:
                registration = row[f"registered_{year}"]
                assert registration is None or isinstance(registration, int) and registration > 0
                registered_cells += registration is not None
            if row["day"] > snapshot["days"]:
                assert row["votes_2026"] is None and row["cumulative_2026"] is None
    history = read(ROOT / "data/history.json")
    resolved = resolved_sources(snapshot, history)
    records = {c["id"]: c for c in snapshot["counties"]}
    scopes = ["all", "tarrant", "harris", "collin"]
    extra = next((c["id"] for c in snapshot["counties"] if c["id"] not in ORIGINAL and c["id"] not in scopes and len(c["periods"]) < snapshot["days"]), None)
    scopes += [extra] if extra else []
    classifications = [("partisan", None, None)] + [("demographic", census, m) for m in census["metrics"]]
    primary = get("/api/primary")
    classifications += [("primary", primary, primary["metrics"][0])]
    views = cells = 0
    for kind, classification, metric in classifications:
        for cohort in ["matched", "unchanged"]:
            for scope in scopes:
                metric_id = "partisan" if metric is None else metric["id"]
                view = get("/api/trends?" + urlencode(dict(view=kind, cohort=cohort, county=scope, metric=metric_id)))
                selected = []
                for county in snapshot["counties"]:
                    if scope != "all" and county["id"] != scope:
                        continue
                    groups = []
                    last = max(county["periods"], key=lambda p: p["day"]) if county["periods"] else None
                    for group in last["groups"] if last else []:
                        if cohort == "unchanged" and not group["unchanged"]:
                            continue
                        band = group["bucket"] if metric is None else demographic_bucket(group, classification, metric, county["id"])
                        if band is not None:
                            groups.append((group, band))
                    years, issues = resolved[county["id"]]
                    complete = not issues and all(years[year][i][0] is not None for year in [2024, 2026] for i in range(snapshot["days"]))
                    if groups and (scope != "all" or complete):
                        selected.append((county["id"], groups, years))
                assert view["generated_at"] == snapshot["generated_at"], "snapshot changed during audit"
                assert view["coverage"]["included_counties"] == [c[0] for c in selected], (scope, kind, metric_id, cohort)
                for index, bucket in enumerate(view["buckets"] + [view["totals"]]):
                    band = None if index == len(view["buckets"]) else index
                    assert bucket["groups"] == sum(sum(band is None or b == band for _, b in groups) for _, groups, _ in selected)
                    assert len(bucket["days"]) == 12
                    for i, row in enumerate(bucket["days"]):
                        for year in [2024, 2026]:
                            assert row[f"date_{year}"] == cutoff(year, i + 1)
                            for position, measure in [(0, "daily"), (1, "cumulative")]:
                                value = None
                                if selected and (year == 2024 or i < snapshot["days"]) and all(years[year][i][position] is not None for _, _, years in selected):
                                    value = sum(sum(sum(years[year][i][position].get(p, 0) for p in group["old" if year == 2024 else "new"]) for group, b in groups if band is None or b == band) for _, groups, years in selected)
                                assert row[f"{measure}_{year}"] == value, (scope, kind, metric_id, cohort, index, i + 1, year, measure)
                                cells += 1
                views += 1
    for county in ["tarrant", "harris", "collin"]:
        response = get(f"/api/map/{county}")
        assert response == read(ROOT / f"data/maps/{county}.geojson")
        period = next(p for p in records[county]["periods"] if p["day"] == snapshot["days"])
        with urlopen(BASE + "/api/export.csv?" + urlencode(dict(county=county, day=snapshot["days"], cohort="matched"))) as result:
            rows = list(csv.DictReader(io.StringIO(result.read().decode())))
        assert len(rows) == 6
        for row, bucket in zip(rows, period["buckets"]):
            assert int(row["votes_2024"]) == bucket["matched"]["votes_2024"]
            assert int(row["votes_2026"]) == bucket["matched"]["votes_2026"]
    return dict(trend_views=views, trend_cells=cells, registration_cells=registered_cells, partial_scope=extra)


def audit_browser(snapshot, census):
    from PIL import Image
    from playwright.sync_api import expect, sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    errors, images, partial_groups = [], [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        page = browser.new_page(viewport={"width": 1512, "height": 1000}, reduced_motion="reduce")
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(BASE, wait_until="networkidle", timeout=120000)
        page.wait_for_function("data&&Tracking.state&&CountyView.view", timeout=120000)
        expect(page.locator("#county-workspace")).to_be_visible()
        expect(page.locator("#statewide-table tbody tr")).to_have_count(254)
        n = len(snapshot["counties"])
        expect(page.locator("#precinct-county-count")).to_have_text(f"{n} counties")
        expect(page.locator("#county option")).to_have_count(n + 1)
        page.locator("#precincts-tab").click()
        page.locator("#precinct-explore-tab").click()
        page.wait_for_function("Atlas.initialized&&Atlas.layer&&document.getElementById('county-map').clientWidth>0")
        expect(page.locator("#map-county option")).to_have_count(n)
        records = {c["id"]: c for c in snapshot["counties"]}
        selected = ["tarrant", "harris", "collin"]
        representative = next(c["id"] for c in snapshot["counties"] if c["id"] not in ORIGINAL | set(selected) and c["periods"] and c["periods"][-1]["matched"]["groups"])
        selected.append(representative)
        for county in selected:
            page.locator("#partisan-mode").click()
            page.locator("#county").select_option(county)
            page.wait_for_function("(id)=>county===id&&Atlas.county===id&&Atlas.layer&&Atlas.layers.size===Atlas.cache.get(id)?.features.length", arg=county, timeout=120000)
            expected = read(ROOT / f"data/maps/{county}.geojson")["features"]
            expect(page.locator("#county-map path[data-precinct]")).to_have_count(len(expected))
            assert page.evaluate("Atlas.map.getBounds().contains(Atlas.layer.getBounds())"), county
            dots = page.locator('.regression-point[aria-hidden="false"]')
            assert dots.count(), (county, "no visible comparable native groups")
            point = dots.first
            index = int(point.get_attribute("data-group"))
            point.focus()
            point.press("Enter")
            page.wait_for_function("(v)=>Atlas.active?.county===v[0]&&Atlas.active?.group_index===v[1]", arg=[county, index])
            assert page.evaluate("[...Atlas.layers.values()].filter(l=>l.feature.properties.group===Atlas.active.group_index).every(l=>Atlas.map.getBounds().contains(l.getBounds())&&l.options.color==='#713bc2')"), county
            native = records[county]["periods"][-1]["groups"][index]["new"][0]
            page.evaluate("(id)=>Atlas.layers.get(id).fire('click')", native)
            expect(page.locator("#selection-title")).to_have_text("Precinct " + native)
            population = census["counties"][county]["precincts"][native]["counts"]["population"]
            expected_population = f"{math.floor(population + 0.5):,}"
            assert page.locator("#selection-stats dd").nth(3).inner_text() == expected_population
            if county == "tarrant":
                page.screenshot(path=str(OUT / "tarrant-explore-desktop.png"), full_page=True)
                with page.expect_download(timeout=120000) as downloaded:
                    page.locator('[data-image="map"]').click()
                destination = OUT / "tarrant-map.png"
                downloaded.value.save_as(str(destination))
                with Image.open(destination) as image:
                    assert image.format == "PNG" and image.size == (1600, 1000)
                    assert image.convert("RGBA").getpixel((0, 0))[3] == 255
                    colors = Counter(image.convert("RGB").get_flattened_data())
                    assert sum(count for color, count in colors.items() if max(color) - min(color) > 35) > 1000
                images.append(destination.name)
            page.locator("#map-reset").click()
        # Incomplete presidential returns cannot become a partisan winner merely
        # because another old precinct in the common group has known votes.
        references = {r["id"]: r for r in read(ROOT / "data/reference.json")}
        for county in ["bexar", "hays"]:
            current = max(records[county]["periods"], key=lambda p: p["day"])
            candidates = []
            for index, group in enumerate(current["groups"]):
                known = [p in references[county]["presidential"] for p in group["old"]]
                population = sum(census["counties"][county]["precincts"][p]["counts"]["vap"] for p in group["new"])
                if any(known) and not all(known) and group["votes_2024"] > 0 and population > 0:
                    candidates.append((index, group))
            assert candidates, (county, "targeted partial presidential case disappeared")
            page.locator("#county").select_option(county)
            page.locator("#demographic-mode").click()
            page.locator("#metric").select_option("non_white_vap")
            page.wait_for_function("(id)=>county===id&&demoReady()&&metricId==='non_white_vap'", arg=county, timeout=120000)
            page.locator("#regression-scale").select_option("full")
            for index, group in candidates:
                point = page.locator(f'.regression-point[data-id="{county}:{index}"]')
                expect(point).to_have_count(1)
                expect(point).to_have_attribute("data-party", "unknown")
                expect(point).to_have_attribute("data-harris-share", "")
                expect(point).to_have_attribute("fill", "#77818e")
                expect(point).to_have_attribute("aria-hidden", "false")
                point.focus()
                point.press("Enter")
                page.wait_for_function("(v)=>Atlas.active?.county===v[0]&&Atlas.active?.group_index===v[1]", arg=[county, index])
                expect(page.locator("#selection-stats dd").nth(2)).to_have_text("—")
                partial_groups.append(f"{county}:{index}")
            with page.expect_download() as downloaded:
                page.locator("#regression-download").click()
            path = OUT / f"{county}-partial-presidential-demographics.csv"
            downloaded.value.save_as(str(path))
            points_csv = list(csv.DictReader(path.open()))
            for _, group in candidates:
                matching = [r for r in points_csv if r["precincts_2024"] == ";".join(group["old"])]
                assert len(matching) == 1 and matching[0]["harris_share_2024_pct"] == "", (county, "partial party share exported")
        page.locator("#regression-scale").select_option("focus")
        page.locator("#county").select_option("tarrant")
        page.locator("#demographic-mode").click()
        page.locator("#metric").select_option("non_white_vap")
        page.wait_for_function("demoReady()&&metricId==='non_white_vap'&&county==='tarrant'", timeout=120000)
        expect(page.locator("#regression-chart svg")).to_have_attribute("data-y-min", "60")
        expect(page.locator(".regression-quadrant")).to_have_count(0)
        assert set(page.locator(".regression-point").evaluate_all("els=>els.map(e=>e.getAttribute('fill'))")) <= {"#285b91", "#a84236", "#77818e"}
        page.locator("#precinct-trends-tab").click()
        page.wait_for_function("Tracking.view?.county==='tarrant'&&Tracking.view?.metric==='non_white_vap'", timeout=120000)
        with page.expect_download() as downloaded:
            page.locator("#tracking-download").click()
        destination = OUT / "tarrant-non-white-daily.csv"
        downloaded.value.save_as(str(destination))
        rows = list(csv.DictReader(destination.open()))
        assert len(rows) == 72 and {r["county"] for r in rows} == {"tarrant"}
        assert all(r["daily_2026"] == "" and r["cumulative_2026"] == "" for r in rows if int(r["day"]) > snapshot["days"])
        toggle = page.locator('#daily-section [data-panel="daily-section"]')
        toggle.click()
        expect(toggle).to_have_attribute("aria-expanded", "false")
        toggle.click()
        expect(toggle).to_have_attribute("aria-expanded", "true")
        # Matrix browsing is paged, while its CSV preserves the complete scope.
        page.locator("#partisan-mode").click()
        page.locator("#county").select_option("all")
        expect(page.locator("#matrix thead th")).to_have_count(13)
        expect(page.locator("#matrix-page")).to_have_text(f"1–12 of {n}")
        page.locator("#matrix-next").click()
        expect(page.locator("#matrix-page")).to_have_text(f"13–24 of {n}")
        page.locator("#matrix-search").fill("Tarrant")
        expect(page.locator("#matrix thead th")).to_have_count(2)
        expect(page.locator("#matrix-page")).to_have_text("1–1 of 1")
        with page.expect_download() as downloaded:
            page.locator("#download").click()
        destination = OUT / "all-precinct-buckets-filtered-matrix.csv"
        downloaded.value.save_as(str(destination))
        all_rows = list(csv.DictReader(destination.open()))
        available = [c for c in snapshot["counties"] if any(p["day"] == snapshot["days"] for p in c["periods"])]
        assert len(all_rows) == 6 * len(available)
        assert {r["county"] for r in all_rows} == {c["name"] for c in available}, "matrix page/search clipped CSV scope"
        if any(c["status"] != "current" for c in snapshot["counties"]):
            expect(page.locator("#source-errors")).to_be_visible()
            assert not page.locator("#source-errors").evaluate("element=>element.open"), "source detail must start collapsed"
        page.locator("#matrix-search").fill("")
        page.screenshot(path=str(OUT / "expanded-matrix-desktop.png"), full_page=True)
        page.locator("#county").select_option("tarrant")
        page.locator("#demographic-mode").click()
        page.wait_for_function("demoReady()&&Tracking.view?.county==='tarrant'&&Tracking.view?.metric==='non_white_vap'", timeout=120000)
        for width in [1512, 768, 390]:
            page.set_viewport_size({"width": width, "height": 1000})
            page.wait_for_timeout(250)
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth"), width
            page.screenshot(path=str(OUT / f"tarrant-trends-{width}.png"), full_page=True)
            page.locator("#precinct-explore-tab").click()
            page.wait_for_timeout(250)
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth"), width
            page.locator("#precinct-trends-tab").click()
        page.locator("#counties-tab").click()
        expect(page.locator("#statewide-table tbody tr")).to_have_count(254)
        assert page.evaluate("CountyView.mode==='partisan'&&mode==='demographic'"), "classification scope leaked"
        page.locator("#statewide-search").fill("Tarrant")
        page.locator('[data-state-county="tarrant"]').click()
        expect(page.locator("#statewide-precincts")).to_be_visible()
        page.locator("#statewide-precincts").click()
        expect(page.locator("#precinct-explore")).to_be_visible()
        assert page.evaluate("county==='tarrant'&&Atlas.county==='tarrant'")
        assert not errors, errors
        browser.close()
    return dict(linked_counties=selected, partial_presidential_groups=partial_groups, png_exports=images,
                csv_rows=len(rows), full_scope_bucket_csv_rows=len(all_rows), javascript_errors=errors)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--api-only", action="store_true")
    args = parser.parse_args()
    snapshot = read(ROOT / "data/latest.json") if args.offline else get("/api/data")
    references, census = read(ROOT / "data/reference.json"), read(ROOT / "data/demographics.json")
    before = input_manifest(references)
    report = {"status": "passed", "snapshot": snapshot["generated_at"], "offline": audit_local(snapshot, references, census)}
    if not args.offline:
        report["api"] = audit_api(snapshot, census)
        if not args.api_only:
            report["browser"] = audit_browser(snapshot, census)
    OUT.mkdir(parents=True, exist_ok=True)
    after = input_manifest(references)
    changed = [path for path in before.keys() | after.keys() if before.get(path) != after.get(path)]
    if changed:
        report["status"] = "invalidated"
        report["changed_inputs"] = sorted(changed)
    (OUT / "expansion-verification.json").write_text(json.dumps(report, indent=2) + "\n")
    assert not changed, ("Source inputs changed during verification; dependent results invalidated", changed)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
