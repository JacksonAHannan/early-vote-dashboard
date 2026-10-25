#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["geopandas==1.1.4"]
# ///
"""Rebuild Census block-point precinct estimates from cached official inputs.

Run: uv run dashboard/scripts/build_demographics.py
Network is used only for missing public aggregate inputs; --offline forbids it.
No voter records or election returns are read or allocated by this script.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import time
from urllib.parse import urlencode
from urllib.request import urlopen
import zipfile

os.environ.setdefault("PROJ_NETWORK", "OFF")

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "sources/census-atlas"
RAW = STORE / "raw"
CACHED_RAW = RAW
EXTRA_CACHE: list[Path] = []
OUT = ROOT / "dashboard/data/demographics.json"
BOUNDARY = ROOT / "sources/boundaries/26p/Precincts26P.shp"
TLC = "https://data.capitol.texas.gov/dataset/2b59f5ce-5fa4-4040-a550-caffbe8986c4/resource/"
URLS = {
    "blocks_pop.zip": TLC + "33ed77c5-951b-4a88-9de7-9c90c4ba50db/download/blocks_pop.zip",
    "counties_pop.txt": TLC + "bf046b18-7794-4aa8-9d0c-4de7fab5d29a/download/counties_pop.txt",
    "readme_2020censusdata.txt": TLC + "cc4b411d-10a4-4fdd-accf-24a68397b19b/download/readme_2020censusdata.txt",
    "acs-2024-schedule.html": "https://www.census.gov/programs-surveys/acs/news/data-releases/2024/release-schedule.html",
    "acs-2025-schedule.html": "https://www.census.gov/programs-surveys/acs/news/data-releases/2025/release-schedule.html",
}
POINT_LAYER = "https://tigerweb.geo.census.gov/arcgis/rest/services/Census2020/Tracts_Blocks/MapServer/2"
FIELDS = {"population": "total", "vap": "vap", "hispanic": "hisp", "white_nh": "anglo",
          "black": "black", "asian": "asian", "hispanic_vap": "hispvap",
          "white_nh_vap": "anglovap", "black_vap": "blackvap", "asian_vap": "asianvap"}
METHOD = ("2020 Census PL 94-171 block counts, published by the Texas Legislative Council, "
          "summed into TLC 2026 primary precincts by the Census block internal point (within). "
          "These are block-point precinct estimates, not 2026 population estimates or voter "
          "demographics. Split blocks are assigned whole; unmatched points are excluded and "
          "reported. Black and Asian include any race combination and can overlap Hispanic. "
          "White non-Hispanic means White alone, not Hispanic. VAP is age 18+, not citizen "
          "voting-age population. Total non-white is everyone other than White alone, not Hispanic; "
          "its count is population minus White non-Hispanic (and VAP minus White non-Hispanic VAP "
          "for age 18+), not a sum of overlapping groups. No votes are allocated.")


def add_derived_counts(counts: dict) -> None:
    counts["under18"] = counts["population"] - counts["vap"]
    counts["non_white"] = counts["population"] - counts["white_nh"]
    counts["non_white_vap"] = counts["vap"] - counts["white_nh_vap"]


def normalize(value: str) -> str:
    value = str(value).strip().upper()
    return value.lstrip("0") or "0"


def fetch(name: str, url: str, offline: bool) -> Path:
    path = input_path(name)
    if path.exists():
        return path
    if offline:
        raise FileNotFoundError(f"Uncached input: {name}")
    for attempt in range(3):
        try:
            with urlopen(url, timeout=90) as response:
                data = response.read()
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
            print(f"Downloaded {name}: {len(data):,} bytes", flush=True)
            return path
        except Exception:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
    raise RuntimeError(name)


def input_path(name: str) -> Path:
    """Reuse immutable existing public sources without copying large state files."""
    for folder in [CACHED_RAW, RAW, *EXTRA_CACHE]:
        cached = folder / name
        if cached.exists():
            return cached
    return RAW / name


def source(path: Path, url: str) -> dict:
    return {"url": url, "path": str(path.relative_to(ROOT)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size}


def main() -> None:
    global STORE, RAW, OUT, EXTRA_CACHE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--reference", type=Path, default=ROOT / "dashboard/data/reference.json")
    parser.add_argument("--counties", nargs="+")
    parser.add_argument("--counties-file", type=Path, help="JSON array of county IDs; allows preparing Census before crosswalk admission")
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--cache-dir", type=Path, action="append", default=[],
                        help="Additional retained aggregate input cache, checked before downloading")
    args = parser.parse_args()
    STORE, RAW, OUT = args.store.resolve(), args.store.resolve() / "raw", args.output.resolve()
    EXTRA_CACHE = [folder.resolve() for folder in args.cache_dir]
    reference_path = args.reference.resolve()
    reference = json.loads(reference_path.read_text())
    if args.counties_file:
        assert not args.counties, "Choose --counties or --counties-file"
        args.counties = json.loads(args.counties_file.read_text())
    if args.counties:
        reference = [county for county in reference if county["id"] in args.counties]
    county_reference = json.loads((ROOT / "dashboard/data/county-reference.json").read_text())["counties"]
    selected_ids = args.counties or [county["id"] for county in reference]
    assert len(selected_ids) == len(set(selected_ids)) and set(selected_ids) <= county_reference.keys()
    counties = {county_id: int(county_reference[county_id]["fips"][2:]) for county_id in selected_ids}
    assert counties
    RAW.mkdir(parents=True, exist_ok=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    urls = dict(URLS)
    for name, fips in counties.items():
        params = {"where": f"STATE='48' AND COUNTY='{fips:03d}'",
                  "outFields": "GEOID,POP100,HU100,INTPTLON,INTPTLAT",
                  "returnGeometry": "false", "f": "json"}
        urls[f"{name}-block-points.json"] = POINT_LAYER + "/query?" + urlencode(params)
    urls["census-block-layer.json"] = POINT_LAYER + "?f=json"
    with ThreadPoolExecutor(max_workers=3) as executor:
        list(executor.map(lambda item: fetch(*item, args.offline), urls.items()))

    import geopandas as gpd
    import pandas as pd
    import pyogrio
    import pyproj
    import shapely

    # Read only the named flat-file member; no remote GDAL paths or archive extraction.
    with zipfile.ZipFile(input_path("blocks_pop.zip")) as archive:
        assert archive.namelist() == ["Blocks_Pop.txt"]
        selected = []
        with io.TextIOWrapper(archive.open("Blocks_Pop.txt"), encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                if int(row["FIPS"]) in counties.values():
                    selected.append(row)
    blocks = {row["SCTBKEY"]: row for row in selected}
    assert len(blocks) == len(selected), "Duplicate Census block GEOIDs"
    county_rows = {int(row["FIPS"]): row for row in csv.DictReader(
        io.StringIO(input_path("counties_pop.txt").read_text(encoding="utf-8-sig")))}

    shapes = gpd.read_file(BOUNDARY, engine="pyogrio", columns=["CNTY", "PREC"])
    assert shapes.crs and shapes.crs.is_projected
    shapes = shapes[shapes.CNTY.isin(counties.values())].copy()
    shapes["precinct"] = shapes.PREC.map(normalize)
    assert not shapes[["CNTY", "precinct"]].duplicated().any(), "Duplicate precinct shapes"
    geometry_audit = {"input_features": len(shapes), "null": int(shapes.geometry.isna().sum()),
                      "empty": int(shapes.geometry.is_empty.sum()),
                      "invalid": int((~shapes.geometry.is_valid).sum()),
                      "geometry_types": shapes.geometry.geom_type.value_counts().to_dict()}
    assert not geometry_audit["null"] and not geometry_audit["empty"]
    # Explicitly repair invalid source rings before point predicates; retain an audit.
    if geometry_audit["invalid"]:
        before = float(shapes.geometry.area.sum())
        shapes.geometry = shapes.geometry.make_valid()
        geometry_audit["repair"] = "GEOS make_valid, linework; no precision snapping"
        geometry_audit["repair_area_delta_m2"] = float(shapes.geometry.area.sum()) - before
    assert shapes.geometry.is_valid.all()
    metrics = []
    for field, label in [("non_white_vap", "Total non-white"), ("hispanic_vap", "Hispanic"), ("black_vap", "Black"),
                         ("asian_vap", "Asian"), ("white_nh_vap", "White non-Hispanic"),
                         ("under18", "Under 18")]:
        metrics.append({"id": field, "label": label, "unit": "percent", "numerator": field,
                        "denominator": "population" if field == "under18" else "vap",
                        "cuts": [20, 40, 60, 80],
                        "source": "2020 Census · TLC · block-point precinct estimate",
                        "vintage": "2020 Census / 2026 primary precincts"})
    data = {"schema_version": 1, "metrics": metrics, "counties": {},
            "sources": [], "method": METHOD}
    audit = {"method": METHOD, "geometry": geometry_audit, "counties": {},
             "versions": {"python": platform.python_version(), "geopandas": gpd.__version__,
                          "pandas": pd.__version__, "shapely": shapely.__version__,
                          "pyproj": pyproj.__version__, "pyogrio": pyogrio.__version__,
                          "gdal": pyogrio.__gdal_version_string__,
                          "geos": shapely.geos_version_string},
             "crs": shapes.crs.to_wkt(), "point_crs": "EPSG:4326",
             "predicate": "point within precinct, county constrained, expected many-to-one",
             "nearest_fallback": False, "precision_grid": None}
    for county, fips in counties.items():
        raw = json.loads(input_path(f"{county}-block-points.json").read_text())
        assert "error" not in raw and not raw.get("exceededTransferLimit"), county
        points = [feature["attributes"] for feature in raw["features"]]
        ids = [point["GEOID"] for point in points]
        expected = {key for key in blocks if int(key[2:5]) == fips}
        assert len(ids) == len(set(ids)) and set(ids) == expected, f"Block universe mismatch: {county}"
        for point in points:
            assert point["POP100"] == int(blocks[point["GEOID"]]["total"]), "Census population mismatch"
        coords = gpd.GeoDataFrame(points, geometry=gpd.points_from_xy(
            [float(p["INTPTLON"]) for p in points], [float(p["INTPTLAT"]) for p in points]),
            crs="EPSG:4326").to_crs(shapes.crs)
        county_shapes = shapes[shapes.CNTY == fips]
        joined = gpd.sjoin(coords, county_shapes[["precinct", "geometry"]], how="left", predicate="within")
        assert len(joined) == len(points), f"Multiply assigned blocks: {county}"
        precincts = {}
        # A precinct with no assigned populated blocks has unavailable composition, not county averages.
        for precinct in county_shapes.precinct:
            precincts[precinct] = {"counts": {key: 0 for key in [*FIELDS, "under18"]},
                                   "quality": {"status": "block_point_estimate", "census_year": 2020,
                                               "boundary_vintage": "26P", "blocks": 0,
                                               "populated_blocks": 0, "moe": None,
                                               "moe_status": "not_applicable_decennial_census"}}
        unmatched = []
        assigned_totals = {key: 0 for key in FIELDS}
        for _, point in joined.iterrows():
            row = blocks[point.GEOID]
            if pd.isna(point.precinct):
                unmatched.append(point.GEOID)
                continue
            target = precincts[point.precinct]
            target["quality"]["blocks"] += 1
            target["quality"]["populated_blocks"] += int(int(row["total"]) > 0)
            for key, raw_field in FIELDS.items():
                value = int(row[raw_field])
                target["counts"][key] += value
                assigned_totals[key] += value
            target["counts"]["under18"] += int(row["total"]) - int(row["vap"])
        census_totals = {key: sum(int(blocks[k][raw_field]) for k in ids)
                         for key, raw_field in FIELDS.items()}
        for key, raw_field in FIELDS.items():
            assert census_totals[key] == int(county_rows[fips][raw_field]), f"County Census mismatch: {county} {key}"
            assert assigned_totals[key] + sum(int(blocks[k][raw_field]) for k in unmatched) == census_totals[key]
        add_derived_counts(census_totals)
        add_derived_counts(assigned_totals)
        for precinct, value in precincts.items():
            counts = value["counts"]
            add_derived_counts(counts)
            assert 0 <= counts["vap"] <= counts["population"]
            assert all(0 <= counts[key] <= counts["vap" if key.endswith("_vap") else "population"]
                       for key in counts if key not in ("population", "vap"))
            for metric in metrics:
                assert 0 <= counts[metric["numerator"]] <= counts[metric["denominator"]]
            if counts["population"] == 0:
                value["quality"]["status"] = "no_assigned_population"
        for key in ("under18", "non_white", "non_white_vap"):
            assert sum(p["counts"][key] for p in precincts.values()) == assigned_totals[key]
        coverage = {"source_blocks": len(points), "assigned_blocks": len(points) - len(unmatched),
                    "unmatched_blocks": len(unmatched),
                    "unmatched_populated_blocks": sum(int(blocks[k]["total"]) > 0 for k in unmatched),
                    "source_population": census_totals["population"],
                    "assigned_population": assigned_totals["population"],
                    "population_coverage_pct": 100 * assigned_totals["population"] / census_totals["population"],
                    "precincts": len(precincts),
                    "populated_precincts": sum(p["counts"]["population"] > 0 for p in precincts.values())}
        data["counties"][county] = {"precincts": precincts, "coverage": coverage,
                                     "census_totals": census_totals, "assigned_totals": assigned_totals}
        audit["counties"][county] = {**coverage, "unmatched_block_ids": unmatched,
                                      "county_count_reconciliation": "all 10 fields equal TLC county totals",
                                      "assignment_reconciliation": "assigned + unmatched equal source, all 10 fields",
                                      "derived_count_reconciliation": "under18, non_white and non_white_vap are complements; precinct sums equal assigned totals"}
        print(county, json.dumps(coverage), flush=True)
    for county in reference:
        wanted = {precinct for group in county["groups"] for precinct in group["new"]}
        present = set(data["counties"][county["id"]]["precincts"])
        missing = sorted(wanted - present)
        audit["counties"][county["id"]]["reference_current_precincts"] = len(wanted)
        audit["counties"][county["id"]]["missing_reference_precincts"] = missing
        assert not missing, f"Reference precincts without Census geometry: {county['id']} {missing}"
    audit["reference_sha256"] = hashlib.sha256(reference_path.read_bytes()).hexdigest()
    audit["reference_counties_checked"] = [county["id"] for county in reference]
    audit["reference_counties_pending"] = sorted(set(counties) - {county["id"] for county in reference})
    data["sources"] = [source(input_path(name), url) for name, url in urls.items()]
    for suffix in [".shp", ".shx", ".dbf", ".prj"]:
        path = BOUNDARY.with_suffix(suffix)
        data["sources"].append(source(path, "https://data.capitol.texas.gov/dataset/precincts"))
    audit["sources"] = data["sources"]
    temp = OUT.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    temp.replace(OUT)
    (STORE / "validation.json").write_text(json.dumps(audit, indent=2) + "\n")
    # Reopen the serialized output and validate aggregation contract.
    reopened = json.loads(OUT.read_text())
    assert set(reopened["counties"]) == set(counties)
    assert all(c["precincts"] for c in reopened["counties"].values())
    print(f"Wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
