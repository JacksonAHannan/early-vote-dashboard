#!/usr/bin/env python3
"""Tarrant SOS daily turnout; county independent controls. No roster is saved.

uv run --with curl-cffi==0.16.3 python dashboard/scripts/collect_tarrant.py
Only aggregate counts, source URLs, hashes, and diagnostics reach disk.
"""
from __future__ import annotations

import argparse
import base64
import collections
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import time
from zoneinfo import ZoneInfo
import zipfile

from curl_cffi import requests

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT.parent / "sources/precinct-expansion/tarrant"
OLD = "https://earlyvoting.texas-election.com/Elections/downloadVoterInfoReport.do"
NEW = "https://goelect.txelections.civixapps.com/api-ivis-system/api/v1/getFileByFormat"
NOTE = (
    "Texas SOS daily IN-PERSON roster by reported residence precinct; mail excluded. "
    "Separate limited/provisional flags are not supplied. The county's independent "
    "in-person roster and polling-location daily controls differ; this series "
    "retains the state roster scope and its original precinct labels, without "
    "allocating missing voters or repairing unknown precincts."
)


def download(url, form=None):
    for attempt in range(3):
        try:
            with requests.Session(impersonate="chrome") as session:
                r = session.post(url, data=form, timeout=120) if form else session.get(url, timeout=120)
            r.raise_for_status()
            if r.status_code != 200:
                raise ValueError("official source not ready")
            return r.content
        except Exception:
            if attempt == 2:
                raise RuntimeError("official source unavailable; no response body retained") from None
            time.sleep(attempt + 1)


def normalize(value):
    value = value.strip()
    return str(int(value)) if value.isdigit() else value.upper()


def parse_state(raw, allow_known_conflict=False):
    """Return aggregates and anonymous-memory identifiers used for validation."""
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    required = {"VOTER_NAME", "VOTING_METHOD", "PRECINCT", "ID_VOTER"}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("state roster headers changed")
    all_ids, inperson_ids = {}, set()
    counts, methods = collections.Counter(), collections.Counter()
    duplicate_rows = 0
    for row in reader:
        voter = row["ID_VOTER"].strip()
        if not voter:
            raise ValueError("blank state voter identifier")
        method = row["VOTING_METHOD"].strip()
        name = row["VOTER_NAME"].strip()
        precinct = normalize(row["PRECINCT"]) or "UNASSIGNED"
        methods[method] += 1
        if voter in all_ids:
            previous_method, previous_name, previous_precinct = all_ids[voter]
            if (not allow_known_conflict or method != "IN-PERSON" or previous_method != method
                    or not name or name != previous_name or previous_precinct == precinct):
                raise ValueError("unvalidated repeated state voter identifier")
            duplicate_rows += 1
            if duplicate_rows != 1:
                raise ValueError("unexpected additional repeated state identifier")
            counts[previous_precinct] -= 1
            counts["UNASSIGNED"] += 1
            if not counts[previous_precinct]:
                del counts[previous_precinct]
            all_ids[voter] = method, name, "UNASSIGNED"
            continue
        all_ids[voter] = method, name, precinct
        if method == "IN-PERSON":
            inperson_ids.add(voter)
            counts[precinct] += 1
        elif method != "MAIL-IN":
            raise ValueError("state voting method changed")
    if not counts:
        raise ValueError("no in-person rows; missing is not zero")
    if allow_known_conflict and duplicate_rows != 1:
        raise ValueError("the audited historical ambiguity changed; re-audit required")
    return dict(sorted(counts.items())), inperson_ids, dict(methods), duplicate_rows


def collect_day(when):
    if when.year == 2024:
        form = dict(idElection="49664", selectedDate=f"{when} 00:00:00.0", electionDate=",",
                    earlyVoteFlag="true", downloadElectionFileCSVFlag="true", idTown="220")
        raw = download(OLD, form)
        source = f"{OLD}?idElection=49664&selectedDate={when}&idTown=220"
    else:
        source = (f"{NEW}?type=EVR_EARLYVOTING&electionId=53815&electionDate="
                  f"{when:%m/%d/%Y}&county=TARRANT&countyId=220&format=csv")
        response = json.loads(download(source))
        encoded = response.get("upload", "").rsplit(",", 1)[-1]
        raw = base64.b64decode(encoded, validate=True)
    counts, ids, methods, duplicate_rows = parse_state(raw, allow_known_conflict=when == date(2024, 10, 21))
    note = NOTE
    if duplicate_rows:
        note += (" One repeated identical-name voter identifier with conflicting precincts is "
                 "counted once in UNASSIGNED; neither conflicting residence is guessed.")
    daily = dict(county="tarrant", date=str(when), counts=counts, source=source,
                 sha256=hashlib.sha256(raw).hexdigest(), retrieved_at=datetime.now(timezone.utc).isoformat(),
                 note=note, cumulative=False)
    diagnostic = dict(date=str(when), methods=methods, precincts=len(counts),
                      in_person=sum(counts.values()), repeated_rows_removed=duplicate_rows,
                      unassigned=counts.get("UNASSIGNED", 0), sha256=daily["sha256"], source=source)
    return daily, ids, diagnostic


def county_control(year):
    """Aggregate the undated county ZIP independently; never assign it to days."""
    source = (f"https://www.tarrantcountytx.gov/content/dam/main/elections/{year}/11{year % 100:02}/"
              "ev_reports/Early_voting_in_person_report.zip")
    raw = download(source)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".txt")]
        if len(names) != 1:
            raise ValueError("county archive members changed")
        with archive.open(names[0]) as member:
            reader = csv.DictReader(io.TextIOWrapper(member, encoding="utf-8-sig"), delimiter="\t")
            required = {"Precinct", "SOS Voter ID", "Election Code", "Party of Ballot Issued"}
            if not required.issubset(reader.fieldnames or []):
                raise ValueError("county roster headers changed")
            headers = reader.fieldnames
            counts, election_codes, parties = collections.Counter(), collections.Counter(), collections.Counter()
            ids = set()
            repeated_ids = blank_ids = 0
            for row in reader:
                precinct = row["Precinct"].strip()
                if not re.fullmatch(r"\d{6}", precinct):
                    raise ValueError("county residence precinct format changed")
                counts[precinct] += 1
                election_codes[row["Election Code"]] += 1
                parties[row["Party of Ballot Issued"]] += 1
                voter = row["SOS Voter ID"].strip()
                blank_ids += not voter
                repeated_ids += voter in ids
                ids.add(voter)
    return dict(year=year, source=source, sha256=hashlib.sha256(raw).hexdigest(),
                retrieved_at=datetime.now(timezone.utc).isoformat(), counts=dict(sorted(counts.items())),
                rows=sum(counts.values()), precincts=len(counts), headers=headers,
                election_codes=dict(election_codes), party_codes=dict(parties),
                repeated_vuid_rows=repeated_ids, blank_vuid_rows=blank_ids,
                note="Undated cumulative county in-person roster. Six-digit precinct labels retained verbatim. "
                     "Not substituted for daily state counts or allocated backwards.")


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n")
    tmp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    completed = datetime.now(ZoneInfo("America/Chicago")).date() - timedelta(days=1)
    parser.add_argument("--through", type=date.fromisoformat, default=min(date(2026, 10, 30), completed))
    parser.add_argument("--year", type=int, choices=[2024, 2026], action="append")
    parser.add_argument("--skip-county-controls", action="store_true")
    args = parser.parse_args()
    years = args.year or [2024, 2026]
    audit_path = SOURCES / "state-daily-audit.json"
    old_audit = json.loads(audit_path.read_text()) if audit_path.exists() else {}
    diagnostics = {d["date"]: d for d in old_audit.get("days", [])}
    for year in years:
        first = date(year, 10, 21 if year == 2024 else 19)
        n = 12 if year == 2024 else min(12, (args.through - first).days + 1)
        if n < 1:
            raise ValueError("no completed voting day requested")
        dates = [first + timedelta(days=i) for i in range(n)]
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(collect_day, dates))
        seen, series = set(), []
        for daily, ids, diagnostic in results:
            if seen.intersection(ids):
                raise ValueError("in-person voter repeated across daily state exports")
            seen.update(ids)
            series.append(daily)
            diagnostics[diagnostic["date"]] = diagnostic
        write(ROOT / f"data/cache/tarrant/{year}-series.json", series)
        if year == 2024:
            write(ROOT / "data/history-cache/tarrant/2024-series.json", series)
        if not args.skip_county_controls:
            control = county_control(year)
            write(SOURCES / f"county-roster-{year}-aggregate.json", control)
        print(json.dumps(dict(year=year, dates=n, in_person=sum(sum(d["counts"].values()) for d in series))))
    write(audit_path, dict(generated_at=datetime.now(timezone.utc).isoformat(),
                          days=[diagnostics[d] for d in sorted(diagnostics)], scope=NOTE))


if __name__ == "__main__":
    main()
