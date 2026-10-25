#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyshp>=2.3,<3", "shapely>=2.1,<3"]
# ///
"""Build additive native precinct references from retained official aggregate sources.

uv run dashboard/scripts/build_precinct_expansion.py --counties tarrant harris --offline
The builder performs no network requests. Cross-year groups use every positive
polygon intersection, without thresholds, snapping or allocation of votes.
TLC VTD presidential counts are used only through unique one-to-one normalized
vertex matches within both source metadata's published 0.001-metre tolerance.
Unmatched native precincts keep missing presidential data, never county averages.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import html
import io
import json
from pathlib import Path
import re
import zipfile

import shapefile
import shapely
from shapely.geometry import shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "sources/precinct-expansion/geography"
BOUNDARIES = ROOT / "sources/boundaries"
VTD = ROOT / "sources/other-counties-2026-10-20/hockley/vtd-check/geometry/VTDs_24PG.shp"
RETURNS = ROOT / "sources/other-counties-2026-10-20/hockley/tlc-election24g.zip"
RETURNS_URL = ("https://data.capitol.texas.gov/dataset/35b16aee-0bb0-4866-b1ec-859f1f044241/"
               "resource/e1cd6332-6a7a-4c78-ad2a-852268f6c7a2/download/2024-general-vtds-election-data.zip")
VTD_URL = ("https://data.capitol.texas.gov/dataset/4d8298d0-d176-4c19-b174-42837027b73e/"
           "resource/906f47e4-4e39-4156-b1bd-4969be0b2780/download/vtds_24pg.zip")
QUALIFICATION = ("TLC-derived 2024 presidential VTD counts joined only through unique one-to-one "
                 "normalized-vertex matches within both official geometry sources' published "
                 "0.001 metre XY tolerance. Original geometry is not claimed exactly equal. "
                 "Unmatched native precincts are unclassified. TLC VTD results can differ from "
                 "certified county totals; complete-source and classified-subset totals are "
                 "reported separately. No votes are allocated by this pipeline.")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(value):
    text = str(value).strip().upper()
    return text.lstrip("0") or "0"


def vtd_identity(value):
    # Leading zeroes inside alphanumeric VTD identifiers are meaningful: TLC
    # has both 0108A and 108A in Midland. These are not native precinct labels.
    text = str(value).strip().upper()
    return str(int(text)) if text.isdigit() else text


def natural(value):
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value))


def provenance(path, url=None):
    value = {"path": str(path.relative_to(ROOT)), "sha256": digest(path)}
    if url:
        value["url"] = url
    return value


def write_csv(path, rows, fields):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_shapes(path, field, wanted):
    result = {fips: {} for fips in wanted}
    for item in shapefile.Reader(str(path)).iterShapeRecords():
        row = item.record.as_dict()
        fips = int(row["CNTY"])
        if fips not in result:
            continue
        identity = vtd_identity(row[field]) if field == "VTD" else normalize(row[field])
        geometry = shape(item.shape.__geo_interface__)
        assert identity not in result[fips], (path, fips, identity, "duplicate")
        assert not geometry.is_empty and geometry.area > 0, (path, fips, identity)
        result[fips][identity] = geometry
    assert all(result.values()), (path, "Missing county geometry")
    return result


def components(old, new):
    # Keep original coordinates for source-precision presidential comparisons.
    # Explicit linework repair is used only where GEOS cannot overlay a source
    # self-touching ring; its changes are recorded separately in the audit.
    valid_old = {p: g if g.is_valid else shapely.make_valid(g) for p, g in old.items()}
    valid_new = {p: g if g.is_valid else shapely.make_valid(g) for p, g in new.items()}
    assert all(g.is_valid and g.geom_type in ("Polygon", "MultiPolygon")
               for g in [*valid_old.values(), *valid_new.values()])
    keys = list(valid_new)
    tree = STRtree(list(valid_new.values()))
    edges, exact = [], []
    parent = {}

    def find(node):
        parent.setdefault(node, node)
        if parent[node] != node:
            parent[node] = find(parent[node])
        return parent[node]

    for old_id, geometry in valid_old.items():
        for index in tree.query(geometry, predicate="intersects"):
            new_id = keys[index]
            area = geometry.intersection(valid_new[new_id]).area
            if area > 0:
                edges.append({"old_precinct": old_id, "new_precinct": new_id,
                              "intersection_area_m2": area})
                parent[find(("old", old_id))] = find(("new", new_id))
            if old[old_id].is_valid and new[new_id].is_valid and old[old_id].equals(new[new_id]):
                exact.append([old_id, new_id])
    assert {row["old_precinct"] for row in edges} == set(old)
    assert {row["new_precinct"] for row in edges} == set(new)
    groups = collections.defaultdict(lambda: {"old": [], "new": []})
    for vintage, precinct in list(parent):
        groups[find((vintage, precinct))][vintage].append(precinct)
    rows = [{vintage: sorted(group[vintage], key=natural) for vintage in ("old", "new")}
            for group in groups.values()]
    rows.sort(key=lambda group: natural(group["old"][0]))
    assert len({p for group in rows for p in group["old"]}) == len(old)
    assert len({p for group in rows for p in group["new"]}) == len(new)
    return rows, exact, edges


def geometry_repairs(vintages):
    return [{"vintage": vintage, "precinct": precinct,
             "reason": shapely.is_valid_reason(geometry), "method": "GEOS make_valid, linework; no snapping",
             "source_vertices": int(shapely.count_coordinates(geometry)),
             "repaired_vertices": int(shapely.count_coordinates(shapely.make_valid(geometry))),
             "area_delta_m2": shapely.make_valid(geometry).area - geometry.area}
            for vintage, shapes in vintages.items() for precinct, geometry in shapes.items()
            if not geometry.is_valid]


def presidential_bridge(native, vtd, source_rows):
    keys = list(vtd)
    tree = STRtree(list(vtd.values()))
    matches, audit = {}, []
    for precinct, geometry in native.items():
        candidates = [keys[index] for index in tree.query(geometry)
                      if shapely.equals_exact(geometry, vtd[keys[index]], tolerance=.001, normalize=True)]
        row = {"native_precinct": precinct, "vtd": "", "unique_match": len(candidates) == 1,
               "raw_topological_equal": "", "native_vertices": int(shapely.count_coordinates(geometry)),
               "vtd_vertices": "", "hausdorff_distance_m": "", "symmetric_difference_m2": ""}
        if len(candidates) == 1:
            key = candidates[0]
            assert key not in matches, (key, "VTD maps to more than one native precinct")
            matches[key] = precinct
            candidate = vtd[key]
            assert shapely.count_coordinates(geometry) == shapely.count_coordinates(candidate)
            row.update(vtd=key, raw_topological_equal=geometry.equals(candidate),
                       vtd_vertices=int(shapely.count_coordinates(candidate)),
                       hausdorff_distance_m=geometry.hausdorff_distance(candidate),
                       symmetric_difference_m2=geometry.symmetric_difference(candidate).area)
        audit.append(row)
    values = {}
    seen = set()
    source_totals = collections.Counter()
    for row in source_rows:
        candidate = row["Name"].lower()
        if candidate not in ("harris", "trump"):
            continue
        key = vtd_identity(row["VTD"])
        assert (key, candidate) not in seen
        seen.add((key, candidate))
        votes = int(row["Votes"])
        assert votes >= 0
        source_totals[candidate] += votes
        if key in matches:
            values.setdefault(matches[key], {})[candidate] = votes
    assert all(set(value) == {"harris", "trump"} for value in values.values())
    return values, audit, dict(source_totals)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--counties", nargs="+")
    parser.add_argument("--counties-file", type=Path, help="JSON array of county IDs")
    parser.add_argument("--offline", action="store_true", help="All operations are always offline")
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--merge-existing", action="store_true",
                        help="Replace only selected counties in the additive reference and audit")
    parser.add_argument("--native-returns-dir", type=Path,
                        help="Optional per-county certified presidential-2024.csv and source.json")
    args = parser.parse_args()
    if args.counties_file:
        assert not args.counties, "Choose --counties or --counties-file"
        args.counties = json.loads(args.counties_file.read_text())
    assert args.counties, "Select counties with --counties or --counties-file"
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    classification = json.loads((ROOT / "dashboard/data/county-reference.json").read_text())["counties"]
    statewide = {c["id"]: c for c in json.loads((ROOT / "dashboard/data/statewide.json").read_text())["counties"]}
    assert len(args.counties) == len(set(args.counties))
    fips_by_county = {slug: int(classification[slug]["fips"][2:]) for slug in args.counties}
    paths = {vintage: BOUNDARIES / vintage / f"Precincts{vintage.upper()}.shp" for vintage in ("24g", "26p")}
    crs = paths["24g"].with_suffix(".prj").read_text()
    assert crs == paths["26p"].with_suffix(".prj").read_text() == VTD.with_suffix(".prj").read_text()
    for path in (paths["24g"], VTD):
        metadata = html.unescape(path.with_suffix(".shp.xml").read_text())
        assert set(float(value) for value in re.findall(r"<XYTolerance>([^<]+)</XYTolerance>", metadata)) == {.001}
    old = read_shapes(paths["24g"], "PREC", fips_by_county.values())
    new = read_shapes(paths["26p"], "PREC", fips_by_county.values())
    vtd = read_shapes(VTD, "VTD", fips_by_county.values())
    election = {fips: [] for fips in fips_by_county.values()}
    with zipfile.ZipFile(RETURNS) as archive:
        member = "2024_General_Election_Returns.csv"
        with io.TextIOWrapper(archive.open(member), encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                if row["Office"] == "President" and int(row["FIPS"]) in election:
                    election[int(row["FIPS"])].append(row)
    geometry_hashes = {v: {ext: digest(p.with_suffix(ext)) for ext in (".shp", ".shx", ".dbf", ".prj")}
                       for v, p in paths.items()}
    vtd_source, presidential_source = provenance(VTD, VTD_URL), provenance(RETURNS, RETURNS_URL)
    references, audits = [], {}
    for slug, fips in fips_by_county.items():
        target = output / slug
        target.mkdir(exist_ok=True)
        groups, exact, edges = components(old[fips], new[fips])
        votes, bridge, tlc_totals = presidential_bridge(old[fips], vtd[fips], election[fips])
        write_csv(target / "tlc-presidential-source.csv", election[fips], list(election[fips][0]))
        write_csv(target / "verified-vtd-to-native-bridge.csv", bridge, list(bridge[0]))
        native_source = None
        native_votes = {}
        if args.native_returns_dir:
            candidate = args.native_returns_dir / slug / "presidential-2024.csv"
            if candidate.exists():
                native_source = json.loads(candidate.with_name("source.json").read_text())
                assert native_source["url"] and native_source["sha256"] == digest(candidate)
                rows = list(csv.DictReader(candidate.open()))
                native_votes = {normalize(row["precinct"]): {field: int(row[field]) for field in ("harris", "trump")}
                                for row in rows}
                assert len(native_votes) == len(rows) and set(native_votes) <= set(old[fips])
                assert all(v >= 0 for row in native_votes.values() for v in row.values())
                for field in ("harris", "trump"):
                    assert sum(row[field] for row in native_votes.values()) == native_source["totals"][field]
                votes.update(native_votes)
        qualification = QUALIFICATION
        if native_source:
            qualification = (f"Certified county 2024 presidential returns for {len(native_votes)} native precincts. "
                             f"{native_source.get('method', '')} "
                             + ("All native precincts have certified geographic returns; special non-geographic ballot categories are kept separate."
                                if len(native_votes) == len(old[fips]) else QUALIFICATION))
        write_csv(target / "presidential-2024.csv", [{"precinct": p, **values} for p, values in sorted(votes.items(), key=lambda x: natural(x[0]))],
                  ["precinct", "harris", "trump"])
        write_csv(target / "crosswalk.csv", edges, ["old_precinct", "new_precinct", "intersection_area_m2"])
        write_csv(target / "groups.csv", [{"precincts_2024": ";".join(g["old"]), "precincts_2026": ";".join(g["new"])} for g in groups],
                  ["precincts_2024", "precincts_2026"])
        write_csv(target / "exact-pairs.csv", [{"old_precinct": a, "new_precinct": b} for a, b in exact], ["old_precinct", "new_precinct"])
        write_csv(target / "precinct-universe.csv", [{"year": year, "precinct": p} for year, shapes in ((2024, old[fips]), (2026, new[fips])) for p in sorted(shapes, key=natural)],
                  ["year", "precinct"])
        audit = {"county": slug, "fips": fips, "precincts_2024": len(old[fips]), "precincts_2026_primary": len(new[fips]),
                 "common_geographic_groups": len(groups), "exact_pairs": len(exact), "positive_overlap_edges": len(edges),
                 "largest_group_nodes": max(len(g["old"]) + len(g["new"]) for g in groups),
                 "county_union_symmetric_difference_m2": unary_union([shapely.make_valid(g) for g in old[fips].values()]).symmetric_difference(unary_union([shapely.make_valid(g) for g in new[fips].values()])).area,
                 "source_geometry_repairs": geometry_repairs({"24g": old[fips], "26p": new[fips]}),
                 "overlay_polygons_valid": True, "all_precincts_mapped": True, "overlap_threshold_m2": 0,
                 "presidential_native_precincts": len(votes), "presidential_missing_native_precincts": sorted(set(old[fips]) - set(votes), key=natural),
                 "tlc_complete_county_totals": tlc_totals, "official_county_controls": {k: classification[slug][k] for k in ("harris", "trump")},
                 "tlc_minus_official": {k: tlc_totals[k] - classification[slug][k] for k in ("harris", "trump")},
                 "classified_subset_totals": {k: sum(row[k] for row in votes.values()) for k in ("harris", "trump")},
                 "presidential_qualification": qualification, "native_presidential_source": native_source,
                 "geography_qualification": "TLC 2024 general / 2026 primary; 2026 primary is a November proxy.",
                 "geometry_source_hashes": geometry_hashes,
                 "vtd_source": vtd_source, "presidential_source": presidential_source, "shapely": shapely.__version__}
        (target / "summary.json").write_text(json.dumps(audit, indent=2) + "\n")
        audits[slug] = audit
        references.append({"id": slug, "name": statewide[slug]["name"], "state_id": statewide[slug]["state_id"],
                           "groups": groups, "exact_pairs": exact, "presidential": votes,
                           "references": {"groups": provenance(target / "groups.csv"), "exact_pairs": provenance(target / "exact-pairs.csv"),
                                          "presidential": {**provenance(target / "presidential-2024.csv"), "qualification": qualification},
                                          "audit": provenance(target / "summary.json")}})
        print(f"{slug}: {len(old[fips])}/{len(new[fips])} native precincts; {len(groups)} groups; {len(votes)} qualified presidential precincts", flush=True)
    if args.merge_existing and (output / "new-reference.json").exists():
        existing = json.loads((output / "new-reference.json").read_text())
        replacements = {county["id"]: county for county in references}
        references = [replacements.pop(county["id"], county) for county in existing] + list(replacements.values())
        previous_audits = json.loads((output / "summary.json").read_text())
        previous_audits.update(audits)
        audits = previous_audits
    (output / "new-reference.json").write_text(json.dumps(references, separators=(",", ":")) + "\n")
    (output / "summary.json").write_text(json.dumps(audits, indent=2) + "\n")


if __name__ == "__main__":
    main()
