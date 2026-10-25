#!/usr/bin/env python3
"""Build all-county classifications from retained official aggregate inputs.

python dashboard/scripts/build_county_reference.py --offline
python dashboard/scripts/build_county_reference.py --offline --verify-blocks

No turnout or voter records are allocated. The optional block audit independently
reconciles every county's ten Census fields with the existing statewide block ZIP.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "sources/county-buckets"
RAW = STORE / "raw"
OUT = ROOT / "dashboard/data/county-reference.json"
CENSUS = ROOT / "sources/census-atlas/raw/counties_pop.txt"
CENSUS_URL = ("https://data.capitol.texas.gov/dataset/2b59f5ce-5fa4-4040-a550-caffbe8986c4/"
              "resource/bf046b18-7794-4aa8-9d0c-4de7fab5d29a/download/counties_pop.txt")
OFFICIAL = "https://results.texas-election.com/static/data/election/49664/1012/"
COMMIT = "a3f8124c1c84db778f7ca4c1a01f6b7fca69444b"
MIRROR = f"https://raw.githubusercontent.com/Camreyn/civicresultmaps/{COMMIT}/data/tx-2024-official-results/"
COUNTY_SHA = "fa818d6a89dd0b6ec7dd5f04120dc3073d2a83edba51c8dafbbd0186b1492b9a"
FIELDS = {"population": "total", "vap": "vap", "hispanic": "hisp", "white_nh": "anglo",
          "black": "black", "asian": "asian", "hispanic_vap": "hispvap",
          "white_nh_vap": "anglovap", "black_vap": "blackvap", "asian_vap": "asianvap"}
CANDIDATES = {"harris": ("340860", "KAMALA D. HARRIS/TIM WALZ", "DEM", 4_835_250),
              "trump": ("9240", "DONALD J. TRUMP/JD VANCE", "REP", 6_393_597)}
METHOD = ("Whole counties classified by official 2024 presidential Harris–Trump two-party "
          "margin or 2020 Census PL 94-171 county composition published by the Texas Legislative "
          "Council. All 254 counties have both classifications. Demographic percentages describe "
          "county residents, not the demographics or votes of early voters. Adult shares use "
          "voting-age population (18+), not citizen voting-age population; Under 18 uses total "
          "population. Black and Asian include any race combination and can overlap Hispanic. "
          "Total non-white is the complement of White alone, not Hispanic, not a sum of "
          "overlapping groups. County FIPS are joined explicitly by name and code; SOS portal "
          "alphabetic county numbers are not FIPS. No precinct interpolation or vote allocation.")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(name: str) -> str:
    return "".join(c.lower() for c in name if c.isascii() and c.isalnum())


def fetch(name: str, offline: bool) -> Path:
    path = RAW / name
    if not path.exists():
        if offline:
            raise FileNotFoundError(path)
        for base in (OFFICIAL, MIRROR):
            try:
                data = urlopen(base + name, timeout=45).read()
                json.loads(data)
                path.write_bytes(data)
                break
            except Exception:
                if base == MIRROR:
                    raise
    if name == "County.json":
        assert digest(path) == COUNTY_SHA, "Official County.json source fingerprint changed"
    return path


def source(path: Path, url: str, **metadata: object) -> dict:
    return {"url": url, "path": str(path.relative_to(ROOT)), "sha256": digest(path),
            "bytes": path.stat().st_size, **metadata}


def verify_blocks(county_counts: dict[str, dict]) -> dict:
    """Independent geography-free sum of every retained Census block by its FIPS."""
    path = ROOT / "sources/census-atlas/raw/blocks_pop.zip"
    totals = {fips: dict.fromkeys(FIELDS, 0) for fips in county_counts}
    block_ids = set()
    with zipfile.ZipFile(path) as archive:
        assert archive.namelist() == ["Blocks_Pop.txt"]
        with io.TextIOWrapper(archive.open("Blocks_Pop.txt"), encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                fips = "48" + row["FIPS"].zfill(3)
                assert fips in totals and row["SCTBKEY"].startswith(fips)
                assert row["SCTBKEY"] not in block_ids, "Duplicate Census block GEOID"
                block_ids.add(row["SCTBKEY"])
                for field, raw_field in FIELDS.items():
                    totals[fips][field] += int(row[raw_field])
    assert block_ids, "Empty Census block source"
    for fips, values in totals.items():
        for field, value in values.items():
            assert value == county_counts[fips][field], (fips, field, value)
    return {"blocks": len(block_ids), "county_fields_reconciled": len(totals) * len(FIELDS),
            "source_sha256": digest(path)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--verify-blocks", action="store_true")
    args = parser.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    files = {name: fetch(name, args.offline) for name in ("County.json", "Federal.json")}
    elections = json.loads(files["County.json"].read_text())
    federal = json.loads(files["Federal.json"].read_text())
    census_rows = list(csv.DictReader(io.StringIO(CENSUS.read_text(encoding="utf-8-sig"))))
    assert len(elections) == len(census_rows) == 254
    census = {"48" + row["FIPS"].zfill(3): row for row in census_rows}
    assert len(census) == 254 and elections.keys() == census.keys()
    state_races = [r for r in federal["Races"] if r["id"] == 1001]
    assert len(state_races) == 1 and state_races[0]["N"] == "PRESIDENT/VICE-PRESIDENT"
    state_candidates = {str(c["ID"]): c for c in state_races[0]["Candidates"]}
    metrics = [{"id": field, "label": label, "unit": "percent", "numerator": field,
                "denominator": "population" if field == "under18" else "vap",
                "cuts": [20, 40, 60, 80], "source": "2020 Census · TLC · county totals",
                "vintage": "2020 Census / counties"}
               for field, label in [("non_white_vap", "Total non-white"), ("hispanic_vap", "Hispanic"),
                                    ("black_vap", "Black"), ("asian_vap", "Asian"),
                                    ("white_nh_vap", "White non-Hispanic"), ("under18", "Under 18")]]
    counties = {}
    counts_by_fips = {}
    for fips, election in sorted(elections.items()):
        row = census[fips]
        county_id = canonical(election["N"])
        assert canonical(row["FENAME"]) == county_id, (fips, row["FENAME"], election["N"])
        assert county_id not in counties
        race = election["Races"]["1001"]
        assert race["OID"] == 1001 and race["ON"] == "PRESIDENT/VICE-PRESIDENT"
        counts = {field: int(row[raw_field]) for field, raw_field in FIELDS.items()}
        counts.update(under18=counts["population"] - counts["vap"],
                      non_white=counts["population"] - counts["white_nh"],
                      non_white_vap=counts["vap"] - counts["white_nh_vap"])
        assert counts["non_white"] == int(row["nanglo"])
        assert counts["non_white_vap"] == int(row["nanglovap"])
        assert 0 < counts["vap"] <= counts["population"]
        for metric in metrics:
            assert 0 <= counts[metric["numerator"]] <= counts[metric["denominator"]]
        name = {"MCLENNAN": "McLennan", "MCMULLEN": "McMullen", "DEWITT": "DeWitt"}.get(
            election["N"], election["N"].title())
        county = {"name": name, "fips": fips, "counts": counts}
        for field, (candidate_id, label, party, _) in CANDIDATES.items():
            candidate = race["C"][candidate_id]
            assert candidate["id"] == int(candidate_id) and candidate["N"] == label and candidate["P"] == party
            assert isinstance(candidate["V"], int) and candidate["V"] >= 0
            county[field] = candidate["V"]
        assert county["harris"] + county["trump"] > 0
        counties[county_id] = county
        counts_by_fips[fips] = counts
    for field, (candidate_id, label, party, expected) in CANDIDATES.items():
        state = state_candidates[candidate_id]
        assert state["N"] == label and state["P"] == party
        assert sum(c[field] for c in counties.values()) == state["V"] == expected
    assert sum(c["counts"]["population"] for c in counties.values()) == 29_145_505
    # Compare names against current statewide turnout identities, without treating
    # the portal's unrelated alphabetic state_id as Census FIPS.
    statewide = json.loads((ROOT / "dashboard/data/statewide.json").read_text())
    assert {c["id"] for c in statewide["counties"]} == counties.keys()
    assert all(canonical(c["name"]) == c["id"] for c in statewide["counties"])
    precinct_census = json.loads((ROOT / "dashboard/data/demographics.json").read_text())
    for county_id, entry in precinct_census["counties"].items():
        assert entry["census_totals"] == counties[county_id]["counts"], county_id
    sources = [source(CENSUS, CENSUS_URL, publisher="Texas Legislative Council", census_year=2020)]
    for name, path in files.items():
        sources.append(source(path, OFFICIAL + name, publisher="Texas Secretary of State",
                              election_id=49664, data_version=1012, election_date="2024-11-05",
                              transport_url=MIRROR + name,
                              transport_note="Official endpoint returned Cloudflare HTTP 403. "
                              "Retained raw government JSON from the pinned public preservation mirror. "
                              "County.json SHA-256 also matches the independent October 2026 source audit.",
                              fingerprint_receipt_url="https://watersheds.johnmorrisonarchitect.com/county-official-audit"))
    output = {"schema_version": 1, "metrics": metrics, "counties": counties,
              "sources": sources, "method": METHOD}
    OUT.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    audit = {"counties": len(counties), "unique_fips": len(counts_by_fips),
             "metrics": len(metrics), "harris": sum(c["harris"] for c in counties.values()),
             "trump": sum(c["trump"] for c in counties.values()),
             "census_totals": {field: sum(c["counts"][field] for c in counties.values())
                               for field in next(iter(counties.values()))["counts"]},
             "output_sha256": digest(OUT), "county_identity_join": "254 exact normalized-name and explicit-FIPS joins"}
    audit["existing_precinct_census_controls_reconciled"] = len(precinct_census["counties"])
    if args.verify_blocks:
        audit["block_reconciliation"] = verify_blocks(counts_by_fips)
        (STORE / "verification.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
