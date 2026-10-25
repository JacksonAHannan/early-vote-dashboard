#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["curl-cffi==0.16.3"]
# ///
"""Validate paired Harris received-mail precinct aggregates; retain no voter rows.

uv run dashboard/scripts/collect_harris_mail.py --through 2026-10-23
An unqualified refresh writes anonymous audit evidence and preserves last good data.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import dataclass
import datetime as dt
import hashlib
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import zipfile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
STARTS = {2024: dt.date(2024, 10, 21), 2026: dt.date(2026, 10, 19)}
URLS = {
    (2024, "mail"): "https://appfiles.harrisvotes.com/harrisvotes/prd/Reports/Cumulative_BBM_1124.zip",
    (2026, "mail"): "https://appfiles.harrisvotes.com/harrisvotes/prd/Reports/Cumulative_BBM_ToPost_1126.zip",
    (2024, "in_person"): "https://appfiles.harrisvotes.com/harrisvotes/prd/Reports/Cumulative_EV_1124.zip",
    (2026, "in_person"): "https://appfiles.harrisvotes.com/harrisvotes/prd/Reports/Cumulative_EV_ToPost_1126.zip",
}
CURRENT_CONTROL = "https://appfiles.harrisvotes.com/harrisvotes/prd/docs/Uploads/EVPA_unofficial.pdf"
HISTORICAL_CONTROL = "https://earlyvoting.texas-election.com/Elections/getEVDetails.do"
METHOD_NOTE = "Received-mail roster, not applications, outgoing ballots or certified accepted-ballot totals. Identities are processed only in memory. Proven byte-identical repeated CSV records are removed; ambiguous assignments and cross-method overlaps quarantine only affected precincts from the first conflicting observation onward. No votes are allocated to close controls."


class Table(HTMLParser):
    """Read the legacy official county summary table, never voter-detail HTML."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.row, self.cell, self.identifier = [], None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row, self.identifier = [], None
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        if self.row is not None:
            match = re.search(r"downloadReport\(['\"](\d+)['\"]\)", dict(attrs).get("onclick", ""))
            if match:
                self.identifier = int(match[1])

    def handle_data(self, value):
        if self.cell is not None:
            self.cell.append(value)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join(" ".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append((self.row, self.identifier))
            self.row = None


def integer(value):
    value = str(value).strip().replace(",", "")
    if not value.isdigit():
        raise ValueError("Independent aggregate control is not a nonnegative integer")
    return int(value)


def normalize(value):
    value = str(value if value is not None else "").strip().lstrip("\ufeff").upper()
    return value.lstrip("0") or ("0" if value else "UNASSIGNED")


def parse_date(value):
    try:
        return dt.datetime.strptime(value.strip(), "%m/%d/%Y").date()
    except ValueError as error:
        raise ValueError("Harris activity date format changed") from error


def fetch(url, form=None):
    from curl_cffi import requests
    for attempt in range(3):
        try:
            response = requests.post(url, data=form, impersonate="chrome", timeout=90) if form else requests.get(url, impersonate="chrome", timeout=90)
            response.raise_for_status()
            if not response.content:
                raise ValueError("Empty official response")
            return response.content
        except Exception:
            if attempt == 2:
                # Never include response bodies or individual source fields.
                raise RuntimeError("Official Harris download failed after three attempts") from None
            time.sleep(.25 * 2 ** attempt)


def atomic_json(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(prefix=".harris-mail-", dir=path.parent, delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write((json.dumps(document, separators=(",", ":")) + "\n").encode())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class Event:
    method: str
    date: dt.date
    precinct: str


class Roster:
    """Private transient identity index; export only the aggregate public method."""
    def __init__(self, year):
        self.year = year
        self.events = []
        self.raw = defaultdict(Counter)
        self.exact_duplicates = defaultdict(Counter)
        self.quarantine = {}
        self.reasons = defaultdict(set)
        self.identities = defaultdict(list)
        self.fingerprints = set()
        self.statistics = Counter()
        self.members = []

    def quarantine_precinct(self, precinct, date, reason):
        self.quarantine[precinct] = min(date, self.quarantine.get(precinct, date))
        self.reasons[precinct].add(reason)

    def add(self, identity, county_identity, event, fingerprint):
        self.raw[(event.method, event.date)][event.precinct] += 1
        self.statistics["raw_rows"] += 1
        if not identity:
            self.statistics["missing_state_identity_rows"] += 1
        if not county_identity:
            self.statistics["missing_county_identity_rows"] += 1
        keys = (["state:" + identity] if identity else []) + (["county:" + county_identity] if county_identity else [])
        if not keys:
            self.quarantine_precinct(event.precinct, event.date, "blank_identity")
            self.statistics["blank_identity_rows"] += 1
            self.events.append(event)
            return
        signature = event.method, fingerprint
        if signature in self.fingerprints:
            self.exact_duplicates[(event.method, event.date)][event.precinct] += 1
            self.statistics["byte_identical_copies_removed"] += 1
            return
        self.fingerprints.add(signature)
        prior_events = set()
        for key in keys:
            prior_events.update(self.identities[key])
        for prior in prior_events:
            # Equal parsed fields with different bytes are not proved duplicates.
            reason = "cross_method_overlap" if prior.method != event.method else "conflicting_identity_assignment" if (prior.date, prior.precinct) != (event.date, event.precinct) else "nonidentical_identity_repeat"
            since = max(prior.date, event.date)
            for precinct in (prior.precinct, event.precinct):
                self.quarantine_precinct(precinct, since, reason)
            self.statistics[reason] += 1
        for key in keys:
            self.identities[key].append(event)
        self.events.append(event)

    def read_zip(self, raw, method):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if not members:
                raise ValueError("Official Harris ZIP has no CSV member")
            for member in members:
                payload = archive.read(member)
                text = payload.decode("utf-8-sig")
                physical_lines = text.splitlines(keepends=True)
                reader = csv.reader(io.StringIO(text, newline=""))
                headers = next(reader, None)
                required = ("StateVoterID", "IDNumber", "Precinct", "ActivityDate")
                if not headers or any(name not in headers for name in required) or len(set(headers)) != len(headers):
                    raise ValueError("Harris roster headers changed")
                columns = {name: headers.index(name) for name in required}
                line_number, count = reader.line_num, 0
                for row in reader:
                    record = "".join(physical_lines[line_number:reader.line_num]).encode()
                    line_number = reader.line_num
                    if not row:
                        continue
                    if len(row) != len(headers):
                        raise ValueError("Harris CSV record width changed")
                    when = parse_date(row[columns["ActivityDate"]])
                    if when.year != self.year or when < dt.date(self.year, 9, 1) or when > dt.date(self.year, 11, 15):
                        raise ValueError("Harris roster contains another election date")
                    if method == "in_person" and not STARTS[self.year] <= when < STARTS[self.year] + dt.timedelta(days=12):
                        raise ValueError("Harris in-person activity outside early-vote calendar")
                    self.add(row[columns["StateVoterID"]].strip(), row[columns["IDNumber"]].strip(), Event(method, when, normalize(row[columns["Precinct"]])), hashlib.sha256(record).digest())
                    count += 1
                self.members.append({"method": method, "member": member, "sha256": hashlib.sha256(payload).hexdigest(), "rows": count})

    def counts(self, method, when, cumulative):
        return Counter(event.precinct for event in self.events if event.method == method and (event.date <= when if cumulative else event.date == when))

    def raw_count(self, method, when, cumulative):
        return sum(sum(counts.values()) for (kind, day), counts in self.raw.items() if kind == method and (day <= when if cumulative else day == when))

    def copies_count(self, method, when, cumulative):
        return sum(sum(counts.values()) for (kind, day), counts in self.exact_duplicates.items() if kind == method and (day <= when if cumulative else day == when))

    def public_audit(self):
        return {"year": self.year, "statistics": dict(self.statistics), "unassigned_precinct_rows": sum(counts["UNASSIGNED"] for counts in self.raw.values()), "members": self.members, "quarantine": [{"precinct": p, "since": date.isoformat(), "reasons": sorted(self.reasons[p])} for p, date in sorted(self.quarantine.items())]}


def qualify(control, logical, raw, copies):
    if control is None or not control.get("complete"):
        return False, "missing_complete_independent_control"
    count = control.get("count")
    if type(count) is not int or count < 0:
        return False, "negative_or_invalid_control"
    if count == logical:
        return True, "unique_roster_equals_control"
    if count == raw and raw - logical == copies:
        return True, "raw_roster_equals_control_with_proven_exact_copy_correction"
    return False, "roster_control_mismatch"


def observation(roster, universe, when, day, method, measure, controls):
    cumulative = measure == "cumulative"
    methods = ("mail", "in_person") if method == "total" else (method,)
    counts = Counter()
    validation = []
    for component in methods:
        logical_counts = roster.counts(component, when, cumulative)
        logical = sum(logical_counts.values())
        raw = roster.raw_count(component, when, cumulative)
        copies = roster.copies_count(component, when, cumulative)
        control = controls.get((roster.year, when.isoformat(), component, measure))
        accepted, reason = qualify(control, logical, raw, copies)
        if logical_counts["UNASSIGNED"]:
            accepted, reason = False, "unassigned_precinct_prevents_complete_partition"
        validation.append({"method": component, "accepted": accepted, "reason": reason, "logical_roster": logical, "raw_roster": raw, "proven_exact_copies": copies, "control": control})
        counts.update(logical_counts)
    accepted = all(value["accepted"] for value in validation)
    excluded = {p for p, since in roster.quarantine.items() if since <= when}
    # A verified exhaustive county roster supports explicit zeros in its known
    # reference universe; missing controls never turn absent precincts into zero.
    available = {p: counts[p] for p in sorted(universe) if p not in excluded} if accepted else {}
    return {"year": roster.year, "day": day, "date": when.isoformat(), "method": method, "measure": measure, "counts": available, "complete_roster": accepted, "quarantined_precincts": sorted(excluded & universe), "unknown_precincts": len(universe) - len(available), "validation": validation}


def make_observations(roster, universe, through, controls):
    length = 12 if roster.year == 2024 else min(12, max(0, (through - STARTS[2026]).days + 1))
    return [observation(roster, universe, STARTS[roster.year] + dt.timedelta(days=index), index + 1, method, measure, controls) for index in range(length) for method in ("mail", "in_person", "total") for measure in ("daily", "cumulative")]


def pdf_controls(raw, through, source=CURRENT_CONTROL):
    result = subprocess.run(["pdftotext", "-layout", "-", "-"], input=raw, capture_output=True, check=True)
    text = result.stdout.decode()
    if "November 3, 2026" not in text:
        raise ValueError("Harris control PDF is for another election")
    values = {}
    for kind, pattern in (("in_person", r"Early In[- ]Person Voters:"), ("mail", r"Mail Ballots (?:Received|Returned):"), ("total", r"Total Early Voters:")):
        match = re.search(pattern + r"\s*([^\n]+)", text, re.I)
        if not match:
            raise ValueError("Independent Harris control row missing")
        row = [int(number.replace(",", "")) for number in re.findall(r"\d[\d,]*", match[1])]
        if len(row) != 13 or sum(row[:12]) != row[12]:
            raise ValueError("Independent Harris control arithmetic failed")
        values[kind] = row[:12]
    if any(a + b != c for a, b, c in zip(values["mail"], values["in_person"], values["total"])):
        raise ValueError("Independent Harris combined row arithmetic failed")
    output = {}
    provenance = {"url": source, "sha256": hashlib.sha256(raw).hexdigest(), "kind": "native_county_received_mail_control"}
    for offset in range(12):
        when = STARTS[2026] + dt.timedelta(days=offset)
        if when > through:
            continue
        for method in ("mail", "in_person"):
            output[(2026, when.isoformat(), method, "cumulative")] = {"count": sum(values[method][:offset + 1]), "complete": True, "source": provenance}
            if method != "mail" or offset > 0:
                # First PDF mail cell includes all pre-opening receipts. It is
                # a cumulative anchor, not the opening day's receipt count.
                output[(2026, when.isoformat(), method, "daily")] = {"count": values[method][offset], "complete": True, "source": provenance}
    return output


def historical_summary(raw, when):
    table = Table()
    table.feed(raw.decode("utf-8-sig"))
    header = next((row for row, _ in table.rows if row and row[0] == "County"), None)
    if not header or header[2] != f"# In Person On {when:%m/%d/%Y}" or header[5:7] != ["Cumulative By Mail Voters", "Cumulative In-Person And Mail Voters"]:
        raise ValueError("Historical SOS mail control columns/date changed")
    row = next((row for row, identifier in table.rows if identifier == 101 and row[0] == "HARRIS"), None)
    if row is None:
        raise ValueError("Historical Harris control row missing")
    ip, cum, mail, total = (integer(row[index]) for index in (2, 3, 5, 6))
    if any(value is None for value in (ip, cum, mail, total)) or cum + mail != total:
        raise ValueError("Historical Harris combined control arithmetic failed")
    return {"in_person_daily": ip, "in_person_cumulative": cum, "mail_cumulative": mail}


def collect_controls(through):
    controls, errors = {}, []
    try:
        controls.update(pdf_controls(fetch(CURRENT_CONTROL), through))
    except Exception as error:
        errors.append({"year": 2026, "source": CURRENT_CONTROL, "reason": str(error)})
    summaries = {}
    for offset in range(-1, 12):
        when = STARTS[2024] + dt.timedelta(days=offset)
        try:
            raw = historical_bytes(when)
            source = {"url": HISTORICAL_CONTROL, "sha256": hashlib.sha256(raw).hexdigest(), "date": when.isoformat(), "kind": "official_sos_county_control"}
            row = historical_summary(raw, when)
            summaries[when] = row
            for key, count in row.items():
                method, measure = key.rsplit("_", 1)
                controls[(2024, when.isoformat(), method, measure)] = {"count": count, "complete": True, "source": source}
        except Exception as error:
            errors.append({"year": 2024, "date": when.isoformat(), "reason": str(error)})
    for when, row in summaries.items():
        previous = summaries.get(when - dt.timedelta(days=1))
        if previous:
            change = row["mail_cumulative"] - previous["mail_cumulative"]
            if change >= 0:
                control = dict(controls[(2024, when.isoformat(), "mail", "cumulative")])
                control["count"] = change
                control["previous_source"] = controls[(2024, (when - dt.timedelta(days=1)).isoformat(), "mail", "cumulative")]["source"]
                controls[(2024, when.isoformat(), "mail", "daily")] = control
            else:
                errors.append({"year": 2024, "date": when.isoformat(), "reason": "negative_mail_control_change"})
    return controls, errors


def historical_bytes(when):
    directory = ROOT / "dashboard/data/statewide-cache/2024"
    metadata = directory / f"{when}.json"
    if metadata.exists():
        expected = json.loads(metadata.read_text())["source"]["sha256"]
        if not re.fullmatch("[a-f0-9]{64}", expected):
            raise ValueError("Invalid retained historical control hash")
        for path in (directory / f"{when}.{expected}.response.html", directory / f"{when}.response.html"):
            if path.exists():
                raw = path.read_bytes()
                if hashlib.sha256(raw).hexdigest() == expected:
                    return raw
    return fetch(HISTORICAL_CONTROL, {"idElection": "49664", "selectedDate": f"{when} 00:00:00.0", "pollPlaceIdtown": "", "electionDate": ","})


def reference():
    entries = json.loads((ROOT / "dashboard/data/reference.json").read_text())
    return next(entry for entry in entries if entry["id"] == "harris")


def paired_coverage(observations, groups):
    lookup = {(row["year"], row["day"], row["method"], row["measure"]): row for row in observations}
    pairs = []
    for day in range(1, 13):
        for method in ("mail", "total"):
            for measure in ("daily", "cumulative"):
                old = lookup.get((2024, day, method, measure))
                new = lookup.get((2026, day, method, measure))
                if not old or not new:
                    continue
                available = sum(all(normalize(p) in old["counts"] for p in group["old"]) and all(normalize(p) in new["counts"] for p in group["new"]) for group in groups)
                pairs.append({"day": day, "method": method, "measure": measure, "matched_groups": available})
    return pairs


def collect(through):
    ref = reference()
    universes = {year: {normalize(p) for group in ref["groups"] for p in group["old" if year == 2024 else "new"]} for year in (2024, 2026)}
    controls, control_errors = collect_controls(through)
    rosters, sources = {}, []
    for year in (2024, 2026):
        roster = Roster(year)
        for method in ("mail", "in_person"):
            url = URLS[(year, method)]
            raw = fetch(url)
            sources.append({"year": year, "method": method, "url": url, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
            roster.read_zip(raw, method)
            del raw
        rosters[year] = roster
    observations = [row for year, roster in rosters.items() for row in make_observations(roster, universes[year], through, controls)]
    pairs = paired_coverage(observations, ref["groups"])
    accepted = any(pair["method"] == "mail" and pair["matched_groups"] for pair in pairs)
    return {"schema_version": 1, "county": "harris", "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "through": through.isoformat(), "accepted": accepted, "measure": "received_mail", "method": METHOD_NOTE, "sources": sources, "control_errors": control_errors, "roster_audits": [roster.public_audit() for roster in rosters.values()], "observations": observations, "paired_coverage": pairs}


def publish(result, output, audit):
    failures = [{"year": row["year"], "date": row["date"], "method": row["method"], "measure": row["measure"], **check} for row in result.get("observations", []) for check in row["validation"] if not check["accepted"]]
    summary = {"status": "accepted" if result.get("accepted") else "rejected", "generated_at": result.get("generated_at"), "through": result.get("through"), "sources": result.get("sources", []), "roster_audits": result.get("roster_audits", []), "control_errors": result.get("control_errors", []), "paired_coverage": result.get("paired_coverage", []), "failed_acceptance": failures, "last_good_replaced": bool(result.get("accepted"))}
    atomic_json(audit, summary)
    if result.get("accepted"):
        atomic_json(output, result)
    else:
        atomic_json(Path(audit).with_name("harris-candidate.json"), result)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    completed = dt.datetime.now(ZoneInfo("America/Chicago")).date() - dt.timedelta(days=1)
    parser.add_argument("--through", type=dt.date.fromisoformat, default=completed)
    parser.add_argument("--output", type=Path, default=ROOT / "dashboard/data/precinct-mail/harris.json")
    parser.add_argument("--audit-output", type=Path, default=ROOT / "analysis/mail-turnout/harris-verification.json")
    args = parser.parse_args()
    if args.through.year != 2026:
        parser.error("--through must be a 2026 date")
    if args.through > completed:
        parser.error("--through must be a completed day in America/Chicago")
    try:
        result = collect(args.through)
        summary = publish(result, args.output, args.audit_output)
    except Exception as error:
        summary = {"status": "rejected", "reason": str(error), "last_good_replaced": False}
        atomic_json(args.audit_output, summary)
    print(json.dumps({key: value for key, value in summary.items() if key not in ("sources", "roster_audits", "control_errors", "paired_coverage", "failed_acceptance")}, separators=(",", ":")))
    if summary["status"] != "accepted":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
