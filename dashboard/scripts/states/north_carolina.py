#!/usr/bin/env python3
"""Aggregate NCSBE absentee records in memory; never persist voter records.

Only accepted returned ballots count. Dates are ballot return dates, not file
publication dates. The official county residence field supports county history;
precinct names are preserved separately without claiming unchanged boundaries.
"""
import argparse
import collections
import csv
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[3]
SOURCES = ROOT / "sources/multistate/nc"
OUTPUT = ROOT / "dashboard/data/states/nc.json"
BASE = "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS"
ELECTIONS = {2024: "2024-11-05", 2026: "2026-11-03"}
STARTS = {2024: "2024-10-17", 2026: "2026-10-15"}
PARTIES = {"DEM": "Democratic", "REP": "Republican", "UNA": "Unaffiliated", "LIB": "Libertarian", "GRE": "Green"}
SEX = {"F": "Female", "M": "Male", "U": "Undesignated"}
RACES = {"WHITE": "White", "BLACK OR AFRICAN AMERICAN": "Black", "ASIAN": "Asian", "INDIAN AMERICAN OR ALASKA NATIVE": "American Indian or Alaska Native", "NATIVE HAWAIIAN OR PACIFIC ISLANDER": "Native Hawaiian or Pacific Islander", "TWO OR MORE RACES": "Two or more races", "OTHER": "Other", "UNDESIGNATED": "Undesignated"}
AXES = ("party", "race", "age", "sex", "ethnicity", "white_nonwhite")
LABELS = {
    "party": tuple(PARTIES.values()) + ("Undesignated",),
    "race": tuple(RACES.values()),
    "age": ("18–29", "30–44", "45–64", "65+", "Undesignated"),
    "sex": tuple(SEX.values()),
    "ethnicity": ("Hispanic or Latino", "Not Hispanic or Latino", "Undesignated"),
    "white_nonwhite": ("White non-Hispanic", "Non-white", "Undesignated"),
}


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def fetch(url, description, sources, save_public=False):
    request = urllib.request.Request(url, headers={"User-Agent": "EarlyVoteResearch/1.0 (aggregate public election data)"})
    with urllib.request.urlopen(request, timeout=120) as response:
        body = response.read()
        published_at = response.headers.get("Last-Modified")
    digest = hashlib.sha256(body).hexdigest()
    record = {"url": url, "retrieved_at": utc_now(), "sha256": digest, "description": description}
    if published_at:
        record["published_at"] = published_at
    record["bytes"] = len(body)
    if save_public:
        SOURCES.mkdir(parents=True, exist_ok=True)
        extension = ".zip" if body[:2] == b"PK" else ".csv"
        path = SOURCES / (digest + extension)
        path.write_bytes(body)
        record["file"] = str(path.relative_to(ROOT))
    sources.append(record)
    return body


def election_url(year, filename):
    return f"{BASE}/{ELECTIONS[year].replace('-', '_')}/{filename}"


def age_bucket(value):
    try:
        age = int(value)
    except (TypeError, ValueError):
        return "Undesignated"
    if age < 18 or age > 120:
        return "Undesignated"
    return "18–29" if age < 30 else "30–44" if age < 45 else "45–64" if age < 65 else "65+"


def attributes(row, index):
    def value(key):
        return row[index[key]].strip()
    race, ethnicity = value("race").upper(), value("ethnicity").upper()
    # Unknown ethnicity does not establish non-Hispanic white; unknown race is
    # not silently included in the non-white group.
    if race == "WHITE" and ethnicity == "NOT HISPANIC OR NOT LATINO":
        white_nonwhite = "White non-Hispanic"
    elif ethnicity == "HISPANIC OR LATINO" or race in RACES and race not in ("WHITE", "UNDESIGNATED"):
        white_nonwhite = "Non-white"
    else:
        white_nonwhite = "Undesignated"
    return {
        "party": PARTIES.get(value("voter_party_code"), value("voter_party_code") or "Undesignated"),
        "race": RACES.get(race, "Undesignated"),
        "age": age_bucket(value("age")),
        "sex": SEX.get(value("gender"), "Undesignated"),
        "ethnicity": "Hispanic or Latino" if ethnicity == "HISPANIC OR LATINO" else "Not Hispanic or Latino" if ethnicity == "NOT HISPANIC OR NOT LATINO" else "Undesignated",
        "white_nonwhite": white_nonwhite,
    }


def cell():
    return {"votes": 0, "breakdowns": {axis: collections.Counter() for axis in AXES}}


def add(target, values, count=1):
    target["votes"] += count
    for axis, label in values.items():
        target["breakdowns"][axis][label] += count


def merge(target, source):
    target["votes"] += source["votes"]
    for axis in AXES:
        target["breakdowns"][axis].update(source["breakdowns"][axis])


def aggregate_records(rows, year, through):
    """Consume CSV rows without retaining identity/address fields or raw rows."""
    header = next(rows)
    index = {name.strip().lower(): i for i, name in enumerate(header)}
    required = {"county_desc", "ncid", "voter_reg_num", "precinct_desc", "ballot_req_type", "ballot_rtn_dt", "ballot_rtn_status", "race", "ethnicity", "gender", "age", "voter_party_code"}
    if not required <= index.keys():
        raise ValueError("NCSBE absentee schema changed: missing " + ", ".join(sorted(required - index.keys())))
    daily = collections.defaultdict(cell)
    precincts = collections.Counter()
    statuses = collections.Counter()
    accepted_types = collections.Counter()
    names, seen, duplicates = set(), set(), 0
    date_cache = {}
    for row in rows:
        if not row or len(row) < len(header):
            continue
        county = row[index["county_desc"]].strip().upper()
        if not county:
            continue
        names.add(county)
        status = row[index["ballot_rtn_status"]].strip().upper()
        statuses[status] += 1
        if not status.startswith("ACCEPTED"):
            continue
        date_raw = row[index["ballot_rtn_dt"]].strip()
        if date_raw not in date_cache:
            try:
                date_cache[date_raw] = dt.datetime.strptime(date_raw[:10], "%m/%d/%Y").date().isoformat()
            except ValueError:
                raise ValueError("Accepted ballot has an invalid return date") from None
        date = date_cache[date_raw]
        identity = row[index["ncid"]].strip() or county + ":" + row[index["voter_reg_num"]].strip()
        if identity in seen:
            duplicates += 1
        # The official controls count accepted ballot records, including a
        # small number of repeated NCIDs. Do not silently subtract those rows
        # from turnout. Record the duplicate diagnostic and reconcile exactly.
        seen.add(identity)
        request_type = row[index["ballot_req_type"]].strip().upper()
        if request_type in ("EARLY VOTING", "ONE-STOP"):
            method = "in_person"
        elif request_type in ("MAIL", "CIVILIAN", "MILITARY", "OVERSEAS"):
            method = "mail"
        else:
            raise ValueError("Unknown accepted ballot request type: " + request_type)
        accepted_types[method] += 1
        if date > through or date >= ELECTIONS[year]:
            continue
        values = attributes(row, index)
        for kind in (method, "total"):
            add(daily[county, date, kind], values)
        precinct = row[index["precinct_desc"]].strip()
        if precinct:
            precincts[county, precinct, date, method] += 1
    return daily, precincts, sorted(names), {"statuses": dict(statuses), "all_accepted_by_method": dict(accepted_types), "duplicate_accepted_records": duplicates}


def observations(daily, names, ids, year, through):
    result = []
    dates_present = sorted({date for _, date, _ in daily})
    if not dates_present:
        raise ValueError(f"No accepted returned ballots in {year}")
    first = dt.date.fromisoformat(dates_present[0])
    last = dt.date.fromisoformat(through)
    # This statewide export includes every returned ballot reported to NCSBE.
    # Empty county/date cells within the covered dates are known source zeros;
    # dates beyond the reported maximum are left unknown.
    last = min(last, dt.date.fromisoformat(dates_present[-1]))
    labels = {axis: set(LABELS[axis]) for axis in AXES}
    for value in daily.values():
        for axis in AXES:
            labels[axis].update(value["breakdowns"][axis])
    for county in names:
        cumulative = {method: cell() for method in ("in_person", "mail", "total")}
        date = first
        while date <= last:
            day = date.isoformat()
            for method in cumulative:
                current = daily.get((county, day, method), cell())
                merge(cumulative[method], current)
                for measure, value in (("daily", current), ("cumulative", cumulative[method])):
                    result.append({"year": year, "date": day, "county": ids[county], "county_name": county.title(), "precinct": None, "measure": measure, "method": method, "votes": value["votes"], "breakdowns": {axis: {label: counts.get(label, 0) for label in sorted(labels[axis])} for axis, counts in value["breakdowns"].items()}, "date_basis": "ballot_return_date", "scope": "county"})
            date += dt.timedelta(days=1)
    return result


def controls(body):
    reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
    totals = collections.Counter()
    for row in reader:
        kind = row["abs_request_type"].strip().upper()
        totals["in_person" if kind in ("EARLY VOTING", "ONE-STOP") else "mail"] += int(row.get("0", row.get("ballot_count", "0")))
    return dict(totals)


def county_returns(body):
    result = collections.defaultdict(collections.Counter)
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        name = next(name for name in archive.namelist() if name.endswith((".txt", ".csv")))
        reader = csv.DictReader(io.TextIOWrapper(archive.open(name), encoding="utf-8-sig", errors="replace"), delimiter="\t")
        for row in reader:
            if row["Contest Name"].strip().upper() != "US PRESIDENT":
                continue
            choice = row["Choice"].upper()
            key = "harris" if "HARRIS" in choice else "trump" if "TRUMP" in choice else None
            if key:
                result[row["County"].upper()][key] += int(row["Total Votes"])
    if len(result) != 100:
        raise ValueError(f"Expected 100 presidential county returns; got {len(result)}")
    return result


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, separators=(",", ":"), ensure_ascii=False) + "\n")
    temporary.replace(path)


def collect(through, force_history=False):
    sources, errors, cached = [], [], {}
    if OUTPUT.exists():
        cached = json.loads(OUTPUT.read_text())
    all_observations, all_precincts, diagnostics, names = [], [], {}, set()
    ids = {}
    returns_url = election_url(2024, "results_pct_20241105.zip")
    try:
        returns = county_returns(fetch(returns_url, "Certified 2024 presidential returns by precinct; rolled up to county", sources, True))
        # McDowell sorts differently from its FIPS ordering; use the official
        # Census Gazetteer mapping rather than deriving IDs from row order.
        gazetteer = json.loads((SOURCES / "county-fips-verification.json").read_text())
        ids = {row["name"].removesuffix(" County").upper(): row["id"] for row in gazetteer["counties"]}
        if set(ids) != set(returns):
            raise ValueError("Official election/Census county names do not reconcile")
    except Exception as error:
        errors.append({"url": returns_url, "error": str(error)})
        if not cached.get("counties"):
            raise
        returns = {row["name"].upper(): {k: row[k] for k in ("harris", "trump") if k in row} for row in cached["counties"]}
        ids = {row["name"].upper(): row["id"] for row in cached["counties"]}
    for year in (2024, 2026):
        old = [row for row in cached.get("observations", []) if row["year"] == year]
        if year == 2024 and old and not force_history:
            all_observations.extend(old)
            names.update(row["county_name"].upper() for row in old)
            sources.extend(source for source in cached.get("sources", []) if "2024_11_05/absentee" in source.get("url", ""))
            errors.extend(error for error in cached.get("errors", []) if "2024_11_05/absentee" in error.get("url", ""))
            diagnostics[str(year)] = cached.get("validation", {}).get(str(year), {})
            continue
        stamp = ELECTIONS[year].replace("-", "")
        zip_url = election_url(year, f"absentee_{stamp}.zip")
        try:
            body = fetch(zip_url, "Accepted absentee/early-vote records; processed in memory only; no voter records saved", sources)
            cutoff = through if year == 2026 else (dt.date.fromisoformat(ELECTIONS[year]) - dt.timedelta(days=1)).isoformat()
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                member = next(name for name in archive.namelist() if name.endswith((".csv", ".txt")))
                reader = csv.reader(io.TextIOWrapper(archive.open(member), encoding="utf-8-sig", errors="replace"))
                daily, precincts, county_names, diagnostic = aggregate_records(reader, year, cutoff)
            del body
            unknown = set(county_names) - ids.keys()
            if unknown:
                raise ValueError("Unknown official county names: " + ", ".join(sorted(unknown)))
            # The statewide roster may contain no records for a county before
            # its first reported return. Its reported count is zero, while the
            # file's overall date coverage still limits which dates are known.
            observed_counties = len(county_names)
            county_names = sorted(ids)
            names.update(county_names)
            rows = observations(daily, county_names, ids, year, cutoff)
            controls_url = election_url(year, f"absentee_counts_state_{stamp}.csv")
            try:
                expected = controls(fetch(controls_url, "Official statewide accepted ballot control totals by request type and demographics", sources, True))
                actual = diagnostic["all_accepted_by_method"]
                diagnostic["official_control_by_method"] = expected
                diagnostic["control_difference_by_method"] = {method: actual.get(method, 0) - expected.get(method, 0) for method in ("in_person", "mail")}
                # These are independently published files, not an admission
                # gate. Preserve reported geographic/date data and disclose
                # differences instead of deleting an entire year's coverage.
                if any(diagnostic["control_difference_by_method"].values()):
                    errors.append({"url": controls_url, "error": "Official detailed/control publication difference; reported accepted records retained: " + str(diagnostic["control_difference_by_method"])})
            except Exception as error:
                errors.append({"url": controls_url, "error": "Independent statewide control unavailable; reported accepted records retained: " + str(error)})
            diagnostic["first_date"] = min(row["date"] for row in rows)
            diagnostic["last_date"] = max(row["date"] for row in rows)
            diagnostic["counties"] = len(county_names)
            diagnostic["counties_with_returned_records"] = observed_counties
            diagnostic["precincts"] = len({(county, precinct) for county, precinct, _, _ in precincts})
            diagnostic["county_observations"] = len(rows)
            diagnostics[str(year)] = diagnostic
            all_observations.extend(rows)
            all_precincts.extend({"year": year, "date": date, "county": ids[county], "county_name": county.title(), "precinct": precinct, "measure": "daily", "method": method, "votes": votes, "scope": "reported_residence_precinct", "comparable": False} for (county, precinct, date, method), votes in sorted(precincts.items()))
            print(f"NC {year}: {len(rows)} county observations, {diagnostic['precincts']} reported precincts; control differences {diagnostic.get('control_difference_by_method', 'unavailable')}", flush=True)
        except Exception as error:
            errors.append({"url": zip_url, "error": str(error)})
            if not old:
                raise
            all_observations.extend(old)
            sources.extend(source for source in cached.get("sources", []) if f"{year}_" in source.get("url", ""))
            diagnostics[str(year)] = cached.get("validation", {}).get(str(year), {})
    counties = [{"id": ids[name], "fips": ids[name], "name": name.title(), **returns.get(name, {})} for name in sorted(ids)]
    result = {"schema_version": 1, "id": "nc", "name": "North Carolina", "generated_at": utc_now(), "through": through, "election_dates": {str(k): v for k, v in ELECTIONS.items()}, "start_dates": {str(k): v for k, v in STARTS.items()}, "observations": all_observations, "counties": counties, "sources": list({source["url"]: source for source in sources}.values()), "errors": errors, "validation": diagnostics, "comparison_scope": "county", "notes": ["Accepted, accepted-exception and accepted-cured returned ballot records only, matching official controls. Repeated accepted NCIDs are recorded in validation metadata, not silently removed from official totals. Mail is dated by ballot return/receipt; in-person by the recorded ballot return date.", "Party is voter registration party; it does not identify candidate choice. Race, ethnicity, age and sex describe participating voters, not Census residents.", "County boundaries support the cross-cycle comparison. Precinct observations are preserved separately; identical precinct names do not establish identical 2024/2026 geography.", "Historical dates reconstruct the current accepted 2024 file by return date; later cures/rejections can revise that history. Current data are reported observations, not certification that every county has uploaded every ballot.", "White/non-white uses explicit race and ethnicity jointly. White with unknown ethnicity and unknown race without affirmative Hispanic ethnicity remain Undesignated."]}
    atomic_json(OUTPUT, result)
    if all_precincts:
        precinct_path = SOURCES / "precinct-daily.json"
        if precinct_path.exists():
            previous = json.loads(precinct_path.read_text())
            refreshed_years = {row["year"] for row in all_precincts}
            all_precincts.extend(row for row in previous.get("observations", []) if row["year"] not in refreshed_years)
        atomic_json(precinct_path, {"schema_version": 1, "id": "nc", "generated_at": result["generated_at"], "through": through, "comparison_scope": "unmatched_precincts", "observations": all_precincts})
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--through", default=(dt.date.today() - dt.timedelta(days=1)).isoformat())
    parser.add_argument("--force-history", action="store_true")
    args = parser.parse_args()
    dt.date.fromisoformat(args.through)
    try:
        data = collect(args.through, args.force_history)
        print(json.dumps({"id": "nc", "observations": len(data["observations"]), "counties": len(data["counties"]), "errors": data["errors"]}))
    except Exception as error:
        print("NC refresh failed; previous successful data retained: " + str(error), file=sys.stderr)
        sys.exit(1)
