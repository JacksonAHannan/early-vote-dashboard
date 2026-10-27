#!/usr/bin/env python3
"""Dated Panola ordinary in-person VRH PDFs; all raw records stay in memory."""
import argparse
import base64
import collections
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import sys
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "dashboard/scripts"))
import collect_county_native as native

LANDING = "https://www.co.panola.tx.us/1201/Elections"
START = date(2026, 10, 19)


def parse_panola(text, when):
    # Poppler can join the last field to the next page's first record with a
    # form feed instead of a newline. Treat that exact PDF boundary as a line.
    text = text.replace("\f", "\n")
    trailer = re.search(r"(?m)^\s*TPanola\s+183(\d+)\s*$", text)
    if not trailer or int(trailer[1]) <= 0:
        raise ValueError("Panola native batch trailer unavailable or empty")
    # Excel's PDF printing can repeat a fragment of the final row after the
    # explicit VRH batch trailer. That fragment is outside the actual batch.
    text = text[:trailer.start()]
    headers = re.findall(r"HPanola\s+183VRH\s+(\d{14})", text)
    if len(headers) != 1 or datetime.strptime(headers[0], "%Y%m%d%H%M%S").date() != when:
        raise ValueError("Panola VRH export timestamp does not match voting day")
    starts = list(re.finditer(r"(?m)^\s*DPanola\s+183(\d{0,10})\s+(\d+)\b", text))
    if not starts or len(starts) != len(re.findall(r"DPanola", text)):
        raise ValueError("Panola empty or unparsed detail record")
    rows = []
    for i, match in enumerate(starts):
        if match[2] != "53815":
            raise ValueError("Panola detail record belongs to a different election")
        chunk = text[match.end(): starts[i + 1].start() if i + 1 < len(starts) else len(text)]
        events = re.findall(r"(?m)^\s*(EV|ED|AV|AB|AX|PB|PX)\s+(EV|ED|AV|AB|AX|PB|PX)\s+(\d{8})\s+\d{2}:\d{2}\s+\d+\s*$", chunk)
        precincts = re.findall(r"(?m)^\s*2\s+([PS])\s*(\d+(?:\.\d+)?)\s*$", chunk)
        if len(events) != 1 or events[0] != ("EV", "EV", when.strftime("%Y%m%d")):
            raise ValueError("Panola detail method/date changed")
        if len(precincts) != 1:
            raise ValueError("Panola residence code missing or ambiguous")
        rows.append((match[1] if len(match[1]) == 10 else "", "".join(precincts[0])))
    return rows


def discover(html, through):
    marker = "Early Voting Turnout for November 3rd 2026 Uniform Election"
    if marker not in html:
        raise ValueError("Panola current-election roster section unavailable")
    section = html.split(marker, 1)[1].split("Early Voting Turnout for May", 1)[0]
    links = re.findall(r'<a\b[^>]*href=["\x27]([^"\x27]+)["\x27][^>]*>\s*Day\s+(\d+)\s*\(PDF\)\s*</a>', section, re.I)
    result, ambiguous = {}, set()
    for href, ordinal in links:
        when = START + timedelta(days=int(ordinal) - 1)
        if not START <= when <= min(through, date(2026, 10, 30)):
            continue
        url = urljoin(LANDING, href)
        if not url.startswith("https://www.co.panola.tx.us/DocumentCenter/View/"):
            raise ValueError("Panola roster destination changed")
        if when in result and result[when] != url:
            ambiguous.add(when)
        result[when] = url
    return {day: url for day, url in result.items() if day not in ambiguous}


def collect_files(links, download=native.download, pdf_text=native.pdf_text):
    files, errors = {}, {}
    for when, url in sorted(links.items()):
        try:
            raw = download(url)
            text = pdf_text(raw)
            rows = parse_panola(text, when)
            trailer = re.search(r"(?m)^\s*TPanola\s+183(\d+)\s*$", text.replace("\f", "\n"))
            total = int(trailer[1])
            frequencies = collections.Counter(identity for identity, _ in rows if identity)
            blanks = sum(not identity for identity, _ in rows)
            if len(frequencies) + blanks != total:
                raise ValueError("Panola native trailer does not reconcile unique and blank identities")
            files[when] = dict(rows=rows, source=url, sha256=hashlib.sha256(raw).hexdigest(),
                               native_trailer_total=total, valid_unique_ids=len(frequencies),
                               blank_or_short_ids=blanks)
        except Exception as error:
            errors[when.isoformat()] = str(error) if isinstance(error, ValueError) and str(error).startswith("Panola") else type(error).__name__
    return files, errors


def sos_url(when):
    return ("https://goelect.txelections.civixapps.com/api-ivis-system/api/v1/getFileByFormat"
            f"?type=EVR_EARLYVOTING&electionId=53815&electionDate={when:%m/%d/%Y}"
            "&county=PANOLA&countyId=183&format=csv")


def state_records(response):
    encoded = json.loads(response)["upload"].rsplit(",", 1)[-1]
    raw = base64.b64decode(encoded, validate=True)
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if not {"ID_VOTER", "VOTING_METHOD", "PRECINCT"} <= set(reader.fieldnames or []):
        raise ValueError("Panola official identity-source schema changed")
    rows = []
    for row in reader:
        if row["VOTING_METHOD"] not in {"IN-PERSON", "MAIL-IN"}:
            raise ValueError("Panola identity-source voting method changed")
        if row["VOTING_METHOD"] == "IN-PERSON":
            identity = row["ID_VOTER"].strip()
            precinct = row["PRECINCT"].strip().upper().lstrip("0") or "UNASSIGNED"
            rows.append((identity, precinct))
    return rows, hashlib.sha256(raw).hexdigest()


def prove_aliases(files, state, universe):
    native_frequency = collections.Counter(identity for file in files.values() for identity, _ in file["rows"])
    associations = collections.defaultdict(set)
    matched = collections.Counter()
    for when, file in files.items():
        native_ids = {identity: label for identity, label in file["rows"] if native_frequency[identity] == 1}
        state_frequency = collections.Counter(identity for identity, _ in state.get(when, []))
        for identity, target in state.get(when, []):
            if not identity or state_frequency[identity] != 1 or identity not in native_ids:
                continue
            label = native_ids[identity]
            associations[label].add(target)
            matched[label, target] += 1
    aliases = {label: next(iter(targets)) for label, targets in associations.items()
               if len(targets) == 1 and targets <= universe}
    proof = [dict(native=label, observed_targets=sorted(targets),
                  matched_rows=sum(matched[label, target] for target in targets), accepted=label in aliases)
             for label, targets in sorted(associations.items())]
    return aliases, proof, associations


def collect(through):
    reference = json.loads((ROOT / "dashboard/data/reference.json").read_text())
    counties = reference if isinstance(reference, list) else reference["counties"]
    county = counties["panola"] if isinstance(counties, dict) else next(c for c in counties if c["id"] == "panola")
    universe = {p for g in county["groups"] for p in g["new"]}
    landing_raw = native.download(LANDING)
    links = discover(landing_raw.decode(), through)
    files, errors = collect_files(links)
    if not files:
        raise ValueError("No usable Panola daily in-person source")
    state, manifests = {}, []
    for when in sorted(files):
        url = sos_url(when)
        try:
            rows, digest = state_records(native.download(url))
            state[when] = rows
            manifests.append(dict(date=when.isoformat(), source=url, sha256=digest, in_person_rows=len(rows)))
        except Exception as error:
            errors[when.isoformat() + ":identity-source"] = type(error).__name__
    aliases, proof, associations = prove_aliases(files, state, universe)
    manifest = dict(method="panola-vrh-exact-identity-alias-v1", landing_source=LANDING,
                    landing_sha256=hashlib.sha256(landing_raw).hexdigest(), state_sources=manifests,
                    native_sources=[dict(date=day.isoformat(), source=file["source"],
                                         sha256=file["sha256"], trailer_total=file["native_trailer_total"])
                                    for day, file in sorted(files.items())],
                    failed_dates=dict(errors),
                    aliases=proof)
    # The crosswalk is bounded to this election's sources. Unknown split labels
    # remain unknown; no decimal, letter, prefix or suffix truncation is used.
    alias_proof = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    for file in files.values():
        file["alias_proof"] = alias_proof
        file["native_sha256"] = file["sha256"]
        evidence = dict(native_sha256=file["sha256"], **manifest)
        file["sha256"] = hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    output = native.aggregate("panola", files, universe, aliases)
    for daily in output:
        when = date.fromisoformat(daily["date"])
        labels = {label for _, label in files[when]["rows"]}
        ambiguous_targets = {target for label in labels if label not in aliases
                             for target in associations.get(label, ()) if target in universe}
        unavailable = set(daily.get("unavailable_precincts", [])) | ambiguous_targets
        daily["unavailable_precincts"] = sorted(unavailable)
        for target in unavailable:
            daily["counts"].pop(target, None)
        daily["note"] += (" County VRH field validation: county183, election53815, both event codesEV, exactdated record. "
                          f"Native PDF SHA256 {files[when]['native_sha256']}. No source code is truncated; only exact-ID-proved full-code aliases are used. "
                          "All observed foreign and ambiguous targets are considered before alias acceptance. "
                          f"Explicit batch trailer {files[when]['native_trailer_total']} records; {files[when]['valid_unique_ids']} valid unique IDs; "
                          f"{files[when]['blank_or_short_ids']} printed rows have blank or short IDs and their cells remain unavailable. "
                          "Printed copies after the first explicit batch trailer are excluded.")
    if errors:
        print(json.dumps(dict(county="panola", failed_dates=errors)), file=sys.stderr)
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--county", choices=["panola"], default="panola")
    parser.add_argument("--through", required=True, type=date.fromisoformat)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not START <= args.through <= date(2026, 10, 30):
        parser.error("through must fall in the 2026 early-voting calendar")
    try:
        result = collect(args.through)
    except Exception as error:
        print(f"Panola official collection failed ({type(error).__name__})", file=sys.stderr)
        return 1
    encoded = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
