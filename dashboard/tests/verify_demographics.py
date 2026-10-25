#!/usr/bin/env python3
"""Independent demographic endpoint audit; needs only the Python standard library.

TURNOUT_TEST_URL=http://127.0.0.1:8743 python dashboard/tests/verify_demographics.py
The audit reads the running snapshot, immutable Census dataset and county maps.
It never refreshes election sources or imports the Rust demographic engine.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "sources/census-atlas/integration-audit.json"
BASE = os.environ.get("TURNOUT_TEST_URL", "http://127.0.0.1:8741").rstrip("/")


def get(path: str) -> dict:
    with urlopen(BASE + path, timeout=45) as response:
        assert response.status == 200
        return json.load(response)


def compare(actual, expected, context: str) -> None:
    if isinstance(expected, dict):
        assert isinstance(actual, dict), context
        for key, value in expected.items():
            assert key in actual, f"{context}: missing {key}"
            compare(actual[key], value, f"{context}.{key}")
    elif isinstance(expected, float):
        assert isinstance(actual, (float, int)) and math.isfinite(actual), context
        assert math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-8), (
            f"{context}: actual={actual}, expected={expected}")
    else:
        assert actual == expected, f"{context}: actual={actual!r}, expected={expected!r}"


def cohort_total(groups: list[dict]) -> dict:
    old = sum(group["votes_2024"] for group in groups)
    new = sum(group["votes_2026"] for group in groups)
    return {"groups": len(groups), "votes_2024": old, "votes_2026": new,
            "ratio": new / old if old else None}


def independent_fit(points: list[dict]) -> dict | None:
    xy = [(point["x"], point["y"]) for point in points if point["y"] is not None]
    if len(xy) < 2:
        return None
    xs, ys = list(zip(*xy))
    if min(xs) == max(xs):
        return None
    if min(ys) == max(ys):
        slope, intercept, r_squared = 0.0, ys[0], None
    else:
        slope, intercept = statistics.linear_regression(xs, ys)
        r_squared = min(1.0, max(0.0, statistics.correlation(xs, ys) ** 2))
    return {"intercept": intercept, "slope": slope, "r_squared": r_squared,
            "x_min": min(xs), "x_max": max(xs)}


def expected_view(snapshot: dict, census: dict, scope: str, day: int,
                  cohort: str, metric: dict) -> dict:
    cuts = [0, *[cut for cut in metric["cuts"] if 0 < cut < 100], 100]
    bins = [{"label": f"{lo}–{hi}%", "lo": lo, "hi": hi,
             "groups": 0, "votes_2024": 0, "votes_2026": 0, "ratio": None}
            for lo, hi in zip(cuts, cuts[1:])]
    categorized = {key: [] for key in ("eligible", "included", "missing_demographics",
                                       "invalid_demographics", "zero_denominator")}
    points = []
    missing_period = []
    for county in snapshot["counties"]:
        if scope != "all" and scope != county["id"]:
            continue
        period = next((period for period in county["periods"] if period["day"] == day), None)
        if period is None:
            missing_period.append(county["id"])
            continue
        precincts = census["counties"].get(county["id"], {}).get("precincts", {})
        for index, group in enumerate(period["groups"]):
            # Demographic matched is all geography groups, including mixed partisan margins.
            if cohort == "unchanged" and not group["unchanged"]:
                continue
            categorized["eligible"].append(group)
            if not group["new"]:
                categorized["invalid_demographics"].append(group)
                continue
            records = [precincts.get(precinct) for precinct in group["new"]]
            numer, denom = metric["numerator"], metric["denominator"]
            if any(record is None or record["counts"].get(numer) is None or
                   record["counts"].get(denom) is None for record in records):
                categorized["missing_demographics"].append(group)
                continue
            if any(not math.isfinite(record["counts"][key]) or record["counts"][key] < 0
                   for record in records for key in (numer, denom)) or any(
                    record["counts"][numer] > record["counts"][denom] for record in records):
                categorized["invalid_demographics"].append(group)
                continue
            # Summed numerators / summed denominators; never mean precinct percentages.
            counts = {}
            shared = set.intersection(*(set(record["counts"]) for record in records))
            for key in shared:
                values = [record["counts"][key] for record in records]
                if all(value is not None and math.isfinite(value) and value >= 0 for value in values):
                    counts[key] = sum(values)
            if counts[denom] == 0:
                categorized["zero_denominator"].append(group)
                continue
            x = 100 * counts[numer] / counts[denom]
            bucket = next((i for i, upper in enumerate(cuts[1:]) if x < upper), len(bins) - 1)
            old, new = group["votes_2024"], group["votes_2026"]
            point = {"county": county["id"], "id": f"{county['id']}:{index}",
                     "group_index": index, "old": group["old"], "new": group["new"],
                     "x": x, "y": 100 * new / old if old else None,
                     "votes_2024": old, "votes_2026": new, "bucket": bucket, "counts": counts}
            points.append(point)
            categorized["included"].append(group)
            bins[bucket]["groups"] += 1
            bins[bucket]["votes_2024"] += old
            bins[bucket]["votes_2026"] += new
    for bucket in bins:
        if bucket["votes_2024"]:
            bucket["ratio"] = bucket["votes_2026"] / bucket["votes_2024"]
    coverage = {key: cohort_total(groups) for key, groups in categorized.items()}
    coverage["omitted_zero_baseline"] = sum(point["y"] is None for point in points)
    coverage["counties_missing_period"] = missing_period
    return {"county": scope, "day": day, "cohort": cohort, "metric": metric,
            "points": points, "bins": bins, "n": len(points) - coverage["omitted_zero_baseline"],
            "fit": independent_fit(points), "coverage": coverage}


def audit() -> dict:
    raw_census = (ROOT / "dashboard/data/demographics.json").read_bytes()
    census = json.loads(raw_census)
    served_census = get("/api/demographics")
    assert census == served_census, "Served Census data differs from the preserved source-derived file"
    snapshot = get("/api/data")
    assert snapshot["days"] >= 4, "Four cumulative days required"
    scopes = ["all", *[county["id"] for county in snapshot["counties"]]]
    assert len(scopes) == 10 and {metric["id"] for metric in census["metrics"]} == {
        "non_white_vap", "hispanic_vap", "black_vap", "asian_vap", "white_nh_vap", "under18"}
    # Verify derived complements from the source count fields independently of
    # the declared metric and the builder; overlapping race totals cannot be added.
    for county in census["counties"].values():
        precincts = [row["counts"] for row in county["precincts"].values()]
        for row in [*precincts, county["assigned_totals"], county["census_totals"]]:
            assert row["non_white"] == row["population"] - row["white_nh"]
            assert row["non_white_vap"] == row["vap"] - row["white_nh_vap"]
            assert 0 <= row["non_white_vap"] <= row["vap"]
        for key in ("non_white", "non_white_vap"):
            assert sum(row[key] for row in precincts) == county["assigned_totals"][key]
    report = {"passed": True, "base_url": BASE,
              "checked_at": datetime.now(timezone.utc).isoformat(),
              "snapshot_generated_at": snapshot["generated_at"],
              "snapshot_sha256": hashlib.sha256(json.dumps(snapshot, sort_keys=True,
                                                          separators=(",", ":")).encode()).hexdigest(),
              "census_sha256": hashlib.sha256(raw_census).hexdigest(),
              "days": [1, 2, 3, 4], "cohorts": ["matched", "unchanged"],
              "metrics": [metric["id"] for metric in census["metrics"]],
              "scopes": scopes, "requests": 2, "views": 0, "points": 0, "bins": 0,
              "regressions": 0, "map_features": 0,
              "matched_groups_without_partisan_bucket": 0,
              "multi_precinct_group_point_checks": 0,
              "weighted_share_differs_from_unweighted_mean": 0,
              "missing_or_zero_demographic_groups": 0, "zero_2024_baseline_points": 0}
    for county in snapshot["counties"]:
        geo = get("/api/map/" + county["id"])
        report["requests"] += 1
        features = geo["features"]
        assert geo["type"] == "FeatureCollection"
        assert len({feature["id"] for feature in features}) == len(features)
        period = county["periods"][0]
        expected_ids = {precinct for group in period["groups"] for precinct in group["new"]}
        assert {feature["properties"]["precinct"] for feature in features} == expected_ids
        for feature in features:
            props = feature["properties"]
            assert feature["id"] == props["id"] == f"{county['id']}:{props['precinct']}"
            assert props["county"] == county["id"]
            assert props["precinct"] in census["counties"][county["id"]]["precincts"]
            for period in county["periods"]:
                assert props["precinct"] in period["groups"][props["group"]]["new"]
        report["map_features"] += len(features)
    for metric in census["metrics"]:
        for day in report["days"]:
            for cohort in report["cohorts"]:
                result = get("/api/demographic-view?" + urlencode(
                    {"day": day, "cohort": cohort, "metric": metric["id"]}))
                report["requests"] += 1
                assert result["generated_at"] == snapshot["generated_at"], "Snapshot changed mid-audit; rerun"
                assert set(result["views"]) == set(scopes)
                for scope in scopes:
                    expected = expected_view(snapshot, census, scope, day, cohort, metric)
                    actual = result["views"][scope]
                    context = f"{metric['id']}/day{day}/{cohort}/{scope}"
                    assert actual["method"].startswith(census["method"]), context + " source method lost"
                    assert "all common geographic groups" in actual["method"], context + " cohort method missing"
                    assert len(actual["points"]) == len(expected["points"]), context + " point count"
                    assert len(actual["bins"]) == len(expected["bins"]), context + " bin count"
                    compare({key: value for key, value in actual.items() if key not in ("points", "bins")},
                            {key: value for key, value in expected.items() if key not in ("points", "bins")}, context)
                    for point, wanted in zip(actual["points"], expected["points"]):
                        compare(point, wanted, context + "/" + wanted["id"])
                        if len(point["new"]) > 1:
                            report["multi_precinct_group_point_checks"] += 1
                            rows = [census["counties"][point["county"]]["precincts"][precinct]["counts"]
                                    for precinct in point["new"]]
                            shares = [100 * row[metric["numerator"]] / row[metric["denominator"]]
                                      for row in rows if row[metric["denominator"]] > 0]
                            if shares and not math.isclose(statistics.mean(shares), point["x"], abs_tol=1e-6):
                                report["weighted_share_differs_from_unweighted_mean"] += 1
                        point_county = next(county for county in snapshot["counties"]
                                            if county["id"] == point["county"])
                        point_period = next(period for period in point_county["periods"]
                                            if period["day"] == day)
                        group = point_period["groups"][point["group_index"]]
                        if cohort == "matched" and group["bucket"] is None:
                            report["matched_groups_without_partisan_bucket"] += 1
                    for bucket, wanted in zip(actual["bins"], expected["bins"]):
                        compare(bucket, wanted, context + "/bin")
                    coverage = actual["coverage"]
                    for key in ("groups", "votes_2024", "votes_2026"):
                        assert coverage["eligible"][key] == sum(coverage[category][key] for category in (
                            "included", "missing_demographics", "invalid_demographics", "zero_denominator")), context
                        assert coverage["included"][key] == sum(bucket[key] for bucket in actual["bins"]), context
                    report["missing_or_zero_demographic_groups"] += sum(coverage[key]["groups"] for key in (
                        "missing_demographics", "invalid_demographics", "zero_denominator"))
                    report["zero_2024_baseline_points"] += coverage["omitted_zero_baseline"]
                    report["views"] += 1
                    report["points"] += len(actual["points"])
                    report["bins"] += len(actual["bins"])
                    report["regressions"] += int(actual["fit"] is not None)
    assert report["views"] == 480 and report["bins"] == 2400
    assert report["map_features"] == sum(len(c["precincts"]) for c in census["counties"].values())
    assert report["matched_groups_without_partisan_bucket"] > 0, "Mixed partisan-margin groups were not exercised"
    assert report["weighted_share_differs_from_unweighted_mean"] > 0, "No distinguishing weighted-share cases exercised"
    for query in ({"day": 0, "metric": "hispanic_vap"},
                  {"day": 1, "metric": "unknown"},
                  {"day": 1, "metric": "hispanic_vap", "cohort": "unknown"}):
        try:
            get("/api/demographic-view?" + urlencode(query))
            raise AssertionError(f"Invalid request accepted: {query}")
        except HTTPError as error:
            assert error.code == 400
        report["requests"] += 1
    report["checks"] = ["Census endpoint byte-derived semantic equality", "all current map IDs and group links",
                        "all demographic cohort points and summed count fields", "weighted group shares",
                        "all bucket group/vote totals and ratios", "complete inclusion/exclusion accounting",
                        "native zero denominators and zero 2024 baselines", "regression n and independent OLS",
                        "matched includes groups without a partisan bucket", "invalid query errors"]
    return report


if __name__ == "__main__":
    try:
        result = audit()
    except Exception as error:
        REPORT.write_text(json.dumps({"passed": False, "base_url": BASE,
                                      "checked_at": datetime.now(timezone.utc).isoformat(),
                                      "error": str(error)}, indent=2) + "\n")
        raise
    REPORT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
