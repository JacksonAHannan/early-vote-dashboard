#!/usr/bin/env python3
"""Audit a pinned Hunt PDF horizontal-panel layout using private exact IDs.

The output is an aggregate research candidate, not an approved precinct alias.
The county full code still needs an explicit native precinct crosswalk.
"""
import base64
import collections
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
COUNTY_URL = "https://www.huntcounty.net/upload/page/0153/docs/Daily Early Voting Totals Report/Vote History 10.19.26.pdf"
COUNTY_SHA = "fb911b5f7c32b0de8b18f4100ef4f05888871f4369034d8a1e462a1207709a15"
SOS_SHA = "4f50ec8704ebb770ee895f4a5970659c141cd22f8ed8a771bc1ffaf6806d3f61"


def all_targets(pairs, known):
    targets = collections.defaultdict(set)
    for pair in pairs:
        if pair["rows"] > 0:
            targets[pair["sos_label"]].add(pair["native_prefix_candidate"])
    # Consider EVERY observed target before checking the native partition. A
    # foreign or ambiguous target invalidates the label; no majority assignment.
    return {label: next(iter(values)) for label, values in targets.items()
            if len(values) == 1 and values <= known}


def county_identities(raw):
    if hashlib.sha256(raw).hexdigest() != COUNTY_SHA:
        raise ValueError("County document revised: reviewed panel layout no longer applies")
    result = subprocess.run(["pdftotext", "-bbox", "-", "-"], input=raw, capture_output=True, check=True)
    ns = {"x": "http://www.w3.org/1999/xhtml"}
    pages = ET.fromstring(result.stdout).findall(".//x:page", ns)
    if len(pages) != 110:
        raise ValueError("County horizontal panel pagination changed")
    identities = {}
    for i in range(42):
        words = pages[i].findall("x:word", ns)
        id_rows = {round(float(w.get("yMin")), 1): w.text for w in words
                   if 140 < float(w.get("xMin")) < 145 and re.fullmatch(r"\d{10}", w.text or "")}
        panel = pages[i + 55].findall("x:word", ns)
        for y, identity in id_rows.items():
            labels = [w.text for w in panel if abs(float(w.get("yMin")) - y) < .15
                      and 110 < float(w.get("xMin")) < 115]
            if len(labels) != 1:
                raise ValueError("Private identity lacks exactly one full county code")
            match = re.fullmatch(r"([0-9]+[A-Z]?)-([A-Z0-9-]+)", labels[0])
            if not match or identity in identities:
                raise ValueError("County code or identity ambiguous")
            identities[identity] = match[1], labels[0]
    if len(identities) != 1808:
        raise ValueError("Reviewed ordinary in-person panel row count changed")
    return identities


def run():
    base = json.loads((ROOT / "analysis/county-methodology/baseline.json").read_text())
    county = next(c for c in base["counties"] if c["id"] == "hunt")
    source = next(s for s in county["sources"] if s["date"] == "2026-10-19")
    raw = urllib.request.urlopen(urllib.parse.quote(COUNTY_URL, safe=":/")).read()
    identities = county_identities(raw)
    result = subprocess.run(
        ["uv", "run", "--quiet", "--with", "curl-cffi==0.16.3", "--with", "playwright==1.64.1",
         "python", str(ROOT / "dashboard/scripts/transport.py")],
        input=json.dumps({"url": source["source"]}).encode(), capture_output=True, timeout=145, check=True)
    data = base64.b64decode(json.loads(result.stdout)["upload"].rsplit(",", 1)[-1], validate=True)
    if hashlib.sha256(data).hexdigest() != SOS_SHA:
        raise ValueError("SOS document revised: regenerate review against current data")
    rows = [r for r in csv.DictReader(io.StringIO(data.decode("utf-8-sig"))) if r["VOTING_METHOD"] == "IN-PERSON"]
    unique = collections.Counter(r["ID_VOTER"] for r in rows)
    pairs = collections.Counter()
    for row in rows:
        identity = row["ID_VOTER"]
        if identity in identities and unique[identity] == 1:
            native, full = identities[identity]
            pairs[row["PRECINCT"].strip().upper().lstrip("0"), native, full] += 1
    pair_rows = [dict(sos_label=a, native_prefix_candidate=b, county_full_code=c, rows=n)
                 for (a, b, c), n in sorted(pairs.items())]
    known = {p for g in county["reference_groups"] for p in g["new"]}
    safe_candidate = all_targets(pair_rows, known)
    output = dict(county="hunt", date="2026-10-19", county_source=COUNTY_URL, county_sha256=COUNTY_SHA,
                  sos_source=source["source"], sos_sha256=SOS_SHA,
                  county_exact_id_native_code_rows=len(identities), state_inperson_rows=len(rows),
                  unjoined_state_rows=len(rows) - sum(pairs.values()), pairs=pair_rows,
                  unambiguous_candidate_labels=len(safe_candidate),
                  disposition="candidate_only_prefix_is_not_independent_native_alias_proof")
    path = ROOT / "analysis/county-methodology/h-r/hunt-code-identity-proof.json"
    path.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({k: output[k] for k in ("county", "date", "county_exact_id_native_code_rows", "state_inperson_rows", "unjoined_state_rows", "unambiguous_candidate_labels", "disposition")}))


if __name__ == "__main__":
    run()
