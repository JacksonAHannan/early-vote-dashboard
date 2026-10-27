#!/usr/bin/env python3
"""Screen the pinned county aggregates; never downloads or persists voter rows."""
import collections
import datetime as dt
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def screen(root=ROOT):
    base_path = root / "analysis/county-methodology/baseline.json"
    base = json.loads(base_path.read_text())
    counties = {c["id"]: c for c in base["counties"]}
    names = json.loads((root / "analysis/county-methodology/h_r-counties.json").read_text())
    aggregate_path = root / "dashboard/data/statewide.json"
    statewide = json.loads(aggregate_path.read_text())
    controls = {c["id"]: c for c in statewide["counties"]}
    rows = []
    for name in names:
        county = counties.get(name)
        if county is None:
            rows.append(dict(county=name, admitted=False, disposition="real_source_gap",
                             diagnosis="No admitted native precinct reference/current usable source in the pinned snapshot.",
                             next_action="Inspect official county voter-history fields and native election precinct evidence before admission.",
                             evidence=[]))
            continue
        universes = {2024: {p for g in county["reference_groups"] for p in g["old"]},
                     2026: {p for g in county["reference_groups"] for p in g["new"]}}
        sources = county["sources"]
        foreign, quarantine, missing, mismatched, evidence, audit = {}, {}, {}, [], [], []
        for year in (2024, 2026):
            start = dt.date(year, 10, 21 if year == 2024 else 19)
            expected = {(start + dt.timedelta(days=i)).isoformat() for i in range(8)}
            series = [s for s in sources if s["date"].startswith(str(year))]
            observed = {s["date"] for s in series if not s.get("cumulative")}
            missing[str(year)] = sorted(expected - observed)
            for s in series:
                unknown = {p: n for p, n in s["counts"].items() if p not in universes[year]}
                if unknown:
                    foreign[f"{year}:{s['date']}"] = unknown
                control_day = next((d for d in controls.get(name, {}).get("days", [])
                                    if d.get(f"date_{year}") == s["date"]), None)
                reported = (control_day or {}).get("by_method", {}).get("in_person", {}).get(f"votes_{year}")
                raw_total = sum(s["counts"].values())
                unknown_total = sum(unknown.values())
                audit.append(dict(date=s["date"], cumulative=s.get("cumulative", False),
                                  roster_total=raw_total, native_positive_total=raw_total - unknown_total,
                                  unknown_positive_total=unknown_total,
                                  separately_published_sos_daily=reported,
                                  roster_minus_sos_daily=None if reported is None or s.get("cumulative") else raw_total - reported,
                                  native_positive_labels=sum(p in universes[year] and n > 0 for p, n in s["counts"].items()),
                                  qualified_complete=s.get("complete", False)))
                if s.get("quarantined"):
                    quarantine[f"{year}:{s['date']}"] = s["quarantined"]
                note = s.get("note", "")
                if "differs" in note or "mismatch" in note:
                    mismatched.append(dict(date=s["date"], note=note))
                evidence.append({k: s[k] for k in ("date", "source", "sha256", "retrieved_at", "cumulative", "complete") if k in s})
        coverage = [{"day": p["day"], **p["coverage"]} for p in county["periods"]]
        classifications = collections.Counter()
        for group in county["reference_groups"]:
            if group.get("bucket") is None:
                classifications[group.get("reason") or "Unclassified"] += len(group["new"])
        paired = [c["available_precincts"] for c in coverage]
        total = len(universes[2026])
        healthy = len(coverage) == 8 and all(v == total for v in paired)
        diagnosis = []
        if healthy:
            diagnosis.append("All native precincts have paired observations on each of the first eight cumulative cutoffs. Positive observations alone do not certify that every vote within a precinct has been published.")
        else:
            diagnosis.append("Daily positive-count sources do not prove omitted precincts have zero votes; cumulative pairing can shrink when a later source omits a native precinct.")
        if any(missing.values()):
            diagnosis.append("At least one expected dated source is absent; no assumption of a closed day or zero turnout is valid.")
        if foreign:
            diagnosis.append("Unrecognized residence labels remain unallocated; county-wide control agreement alone cannot assign them.")
        if mismatched:
            diagnosis.append("A source/control count discrepancy is recorded and prevents blanket completeness.")
        rows.append(dict(county=name, admitted=True, native_precincts={str(y): len(v) for y, v in universes.items()},
                         coverage=coverage, missing_daily_sources=missing, unknown_label_counts=foreign,
                         unclassified_native_precincts=dict(classifications),
                         source_count_audit=audit,
                         quarantined=quarantine, source_control_disagreements=mismatched,
                         disposition="healthy" if healthy else "real_source_gap", diagnosis=" ".join(diagnosis),
                         next_action="Retain exact native assignments; monitor source revisions and independent controls." if healthy else
                         "Recover missing dated source or independently prove native aliases/explicit bounded zeros; never allocate a residual or truncate a label.",
                         evidence=evidence))
    return dict(schema_version=1, baseline_generated_at=base["generated_at"],
                baseline_sha256=hashlib.sha256(base_path.read_bytes()).hexdigest(),
                statewide_aggregate_sha256=hashlib.sha256(aggregate_path.read_bytes()).hexdigest(),
                scope="Each of 107 assigned county native universes, eight cutoff pairs, every retained source and available method-matched SOS control. Healthy denotes paired observation coverage, not proof of complete within-precinct reporting.",
                county_count=len(rows), counties=rows)


if __name__ == "__main__":
    result = screen()
    destination = ROOT / "analysis/county-methodology/h-r/ledger.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(dict(counties=result["county_count"], dispositions=dict(collections.Counter(c["disposition"] for c in result["counties"])))) )
