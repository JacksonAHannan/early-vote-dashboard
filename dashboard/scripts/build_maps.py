#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["shapely>=2.1,<3", "pyproj>=3.7,<4"]
# ///
"""Build display precinct geometry from the unchanged Texas 2026 primary source.

Run: uv run dashboard/scripts/build_maps.py
Requires the installed GDAL ogr2ogr executable. No network or Census request occurs.
The output is display geometry only; demographic intersections use the original SHP.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

import pyproj
import shapely
from shapely.geometry import mapping, shape

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "sources/boundaries/26p/Precincts26P.shp"
SOURCE_URL = "https://data.capitol.texas.gov/dataset/d04c72b9-16c4-4ab2-8c6d-c666d41e04b7/resource/33ec5b30-ee4d-424f-9769-57b87cb5e311/download/precincts26p.zip"
REFERENCE = ROOT / "dashboard/data/reference.json"
OUTPUT = ROOT / "dashboard/data/maps"
PROVENANCE = ROOT / "sources/map-atlas"
USER_ARCHIVE = ROOT / "sources/boundaries/precincts26p.zip"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_precinct(value: str) -> str:
    text = str(value).strip().upper()
    return text.lstrip("0") or "0"


def quantize_coordinates(value, decimals=7):
    if isinstance(value, (list, tuple)):
        return [quantize_coordinates(item, decimals) for item in value]
    return round(float(value), decimals)


def polygon_count(geometry) -> int:
    return len(geometry.geoms) if geometry.geom_type == "MultiPolygon" else 1


def choose_simplification(geometries):
    """Preserve the county exterior and every polygon; protect tiny precincts.

    Coverage simplification processes shared edges once, avoiding per-feature
    simplification's overlaps/gaps. Reduce the county tolerance when any feature
    changes more than 1% of area, disappears, or loses a disconnected component.
    """
    if not shapely.coverage_is_valid(geometries):
        # Native coverage can have non-matching edges or overlaps. Preserve it
        # unsimplified rather than silently snapping boundaries or dropping a
        # precinct; the source and resulting coverage state are audited below.
        return list(geometries), 0, 0
    for tolerance in (10, 5, 2, 1, 0.5, 0):
        simplified = (shapely.coverage_simplify(geometries, tolerance, simplify_boundary=False)
                      if tolerance else geometries)
        changes = [abs(a.area - b.area) / a.area for a, b in zip(geometries, simplified)]
        safe = all(not b.is_empty and b.is_valid and polygon_count(a) == polygon_count(b)
                   for a, b in zip(geometries, simplified))
        if safe and max(changes, default=0) <= 0.01 and shapely.coverage_is_valid(simplified):
            return list(simplified), tolerance, max(changes, default=0)
    raise ValueError("No safe display simplification")


def build(reference_path: Path = REFERENCE, output: Path = OUTPUT,
          provenance: Path = PROVENANCE, counties: list[str] | None = None) -> dict:
    if not shutil.which("ogr2ogr"):
        raise RuntimeError("GDAL ogr2ogr is required")
    output.mkdir(parents=True, exist_ok=True)
    provenance.mkdir(parents=True, exist_ok=True)
    reference = json.loads(reference_path.read_text())
    if counties:
        reference = [county for county in reference if county["id"] in counties]
    reference_by_county = {county["id"]: county for county in reference}
    if counties:
        assert set(reference_by_county) == set(counties), "Unknown requested county"
    county_reference = json.loads((ROOT / "dashboard/data/county-reference.json").read_text())["counties"]
    county_fips = {slug: county_reference[slug]["fips"][2:] for slug in reference_by_county}
    source_prj = SOURCE.with_suffix(".prj").read_text()
    source_crs = pyproj.CRS.from_wkt(source_prj)
    transformer = pyproj.Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)
    where = "CNTY IN (" + ",".join(str(int(code)) for code in county_fips.values()) + ")"
    with tempfile.TemporaryDirectory(prefix="texas-precinct-map-") as temporary:
        raw_path = Path(temporary) / "source.json"
        subprocess.run(["ogr2ogr", "-f", "GeoJSON", str(raw_path), str(SOURCE),
                        "-where", where, "-select", "CNTY,PREC",
                        "-lco", "COORDINATE_PRECISION=4"], check=True)
        raw = json.loads(raw_path.read_text())
    selected = {slug: [] for slug in county_fips}
    slug_by_fips = {int(code): slug for slug, code in county_fips.items()}
    for feature in raw["features"]:
        selected[slug_by_fips[int(feature["properties"]["CNTY"]) ]].append(feature)
    manifest = {
        "source": str(SOURCE.relative_to(ROOT)),
        "source_url": SOURCE_URL,
        "attribution": "Texas Legislative Council, 2026 Primary Election Voting Precincts, CC BY",
        "source_files": {str(path.relative_to(ROOT)): sha256(path)
                         for path in sorted(SOURCE.parent.glob("Precincts26P.*"))},
        "source_crs_wkt": source_crs.to_wkt(),
        "target_crs": "EPSG:4326; RFC 7946 longitude, latitude",
        "reference": str(reference_path.relative_to(ROOT)),
        "reference_sha256": sha256(reference_path),
        "processing": {
            "method": "Shapely coverage_simplify; shared edges simplified together; county exterior retained",
            "maximum_tolerance_m": 10,
            "maximum_relative_feature_area_change": 0.01,
            "coordinate_decimals": 7,
            "normalization": "PREC field padding has leading zeroes removed, including alphanumeric precincts, to match reference.new",
            "shapely": shapely.__version__, "pyproj": pyproj.__version__,
            "gdal": subprocess.check_output(["ogr2ogr", "--version"], text=True).strip(),
        },
    }
    if USER_ARCHIVE.exists():
        with zipfile.ZipFile(USER_ARCHIVE) as archive:
            entries = [name for name in archive.namelist() if name.lower().endswith(".shp")]
            archive_shp_hash = hashlib.sha256(archive.read(entries[0])).hexdigest()
        manifest["user_archive"] = {"path": str(USER_ARCHIVE), "sha256": sha256(USER_ARCHIVE),
            "shapefile_member": entries[0], "shapefile_sha256": archive_shp_hash,
            "identical_shapefile": archive_shp_hash == sha256(SOURCE)}
    verification = {"passed": True, "counties": {}, "total_features": 0,
                    "source_shapefile_sha256": sha256(SOURCE)}
    for slug, fips in county_fips.items():
        county = reference_by_county[slug]
        group_by_precinct = {}
        for index, group in enumerate(county["groups"]):
            for precinct in group["new"]:
                assert precinct not in group_by_precinct, (slug, precinct, "duplicate reference")
                group_by_precinct[precinct] = index
        rows = sorted(selected[slug], key=lambda f: normalize_precinct(f["properties"]["PREC"]))
        ids = [normalize_precinct(feature["properties"]["PREC"]) for feature in rows]
        assert set(ids) == set(group_by_precinct), (slug, "Reference/source universe differs")
        assert len(ids) == len(set(ids)), (slug, "Duplicate source precinct")
        geometries = [shape(feature["geometry"]) for feature in rows]
        repairs = [{"precinct": precinct, "reason": shapely.is_valid_reason(geometry),
                    "method": "GEOS make_valid, linework; no snapping",
                    "area_delta_m2": shapely.make_valid(geometry).area - geometry.area}
                   for precinct, geometry in zip(ids, geometries) if not geometry.is_valid]
        geometries = [g if g.is_valid else shapely.make_valid(g) for g in geometries]
        assert all(g.is_valid and not g.is_empty and g.area > 0 for g in geometries)
        source_coverage_valid = bool(shapely.coverage_is_valid(geometries))
        simplified, tolerance, max_area_change = choose_simplification(geometries)
        projected = [shapely.transform(g, transformer.transform, interleaved=False) for g in simplified]
        # Increase serialization precision when rounding would close a narrow
        # ring or invalidate shared edges. Do not repair or drop such a feature.
        for coordinate_decimals in (7, 8, 9, 10, 11):
            features, display_shapes = [], []
            for precinct, geometry in zip(ids, projected):
                geojson = mapping(geometry)
                geojson["coordinates"] = quantize_coordinates(geojson["coordinates"], coordinate_decimals)
                final_shape = shape(geojson)
                if (not final_shape.is_valid or final_shape.is_empty
                        or polygon_count(final_shape) != polygon_count(geometry)):
                    break
                bbox = list(final_shape.bounds)
                assert -107 < bbox[0] < bbox[2] < -93 and 25 < bbox[1] < bbox[3] < 37
                identity = f"{slug}:{precinct}"
                features.append({"type": "Feature", "id": identity, "bbox": bbox,
                                 "properties": {"id": identity, "county": slug, "precinct": precinct,
                                                "group": group_by_precinct[precinct]}, "geometry": geojson})
                display_shapes.append(final_shape)
            if len(features) == len(ids) and (not source_coverage_valid or shapely.coverage_is_valid(display_shapes)):
                break
        else:
            raise ValueError(f"{slug}: coordinate serialization cannot preserve valid polygons and coverage")
        bounds = [feature["bbox"] for feature in features]
        bbox = [min(b[0] for b in bounds), min(b[1] for b in bounds),
                max(b[2] for b in bounds), max(b[3] for b in bounds)]
        collection = {"type": "FeatureCollection", "county": slug, "name": county["name"],
                      "census_fips": "48" + fips, "bbox": bbox,
                      "metadata": {"source_sha256": sha256(SOURCE), "source_crs": source_crs.name,
                                   "target_crs": "EPSG:4326", "simplification_m": tolerance,
                                   "max_feature_area_change_fraction": max_area_change},
                      "features": features}
        if coordinate_decimals != 7:
            collection["metadata"]["coordinate_decimals"] = coordinate_decimals
        county_output = output / f"{slug}.geojson"
        county_output.write_text(json.dumps(collection, separators=(",", ":"), allow_nan=False) + "\n")
        # Validate the written artifact, rather than only its in-memory precursor.
        written = json.loads(county_output.read_text())
        assert len(written["features"]) == len(group_by_precinct)
        assert {f["properties"]["precinct"] for f in written["features"]} == set(group_by_precinct)
        for feature in written["features"]:
            props = feature["properties"]
            assert props["group"] == group_by_precinct[props["precinct"]]
            assert feature["bbox"] == list(shape(feature["geometry"]).bounds)
        projected_shapes = [shape(feature["geometry"]) for feature in written["features"]]
        display_coverage_valid = bool(shapely.coverage_is_valid(projected_shapes))
        if source_coverage_valid:
            assert display_coverage_valid, (slug, "Rounded WGS84 coverage invalid")
        checks = {"features": len(features), "reference_new_precincts": len(group_by_precinct),
                  "reference_groups": len(county["groups"]), "group_join_exact": True,
                  "id_universe_exact": True, "valid_polygons": True,
                  "source_valid_coverage": source_coverage_valid, "valid_coverage": display_coverage_valid,
                  "preserved_disconnected_components": True, "bbox": bbox,
                  "source_geometry_repairs": repairs,
                  "coordinate_decimals": coordinate_decimals,
                  "simplification_m": tolerance, "max_feature_area_change_fraction": max_area_change,
                  "source_vertices": sum(int(shapely.count_coordinates(g)) for g in geometries),
                  "display_vertices": sum(int(shapely.count_coordinates(g)) for g in projected_shapes),
                  "bytes": county_output.stat().st_size, "sha256": sha256(county_output)}
        verification["counties"][slug] = checks
        verification["total_features"] += len(features)
        print(f"{slug}: {len(features)} precincts, {checks['bytes']:,} bytes, {tolerance}m, exact join")
    verification["total_bytes"] = sum(c["bytes"] for c in verification["counties"].values())
    (provenance / "source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (provenance / "verification.json").write_text(json.dumps(verification, indent=2) + "\n")
    return verification


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=REFERENCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--provenance", type=Path, default=PROVENANCE)
    parser.add_argument("--counties", nargs="+")
    args = parser.parse_args()
    build(args.reference.resolve(), args.output.resolve(), args.provenance.resolve(), args.counties)
