#!/usr/bin/env python3
"""Stage additive Texas county prerequisites without writing either dashboard.

uv run --with geopandas==1.1.4 --with pyshp --with curl-cffi==0.16.3 \
  python sources/county-recovery/build_admission_bundle.py

Uses retained official aggregate inputs and existing project builders offline.
The isolated project mirror retains normal project-relative provenance paths.
Only selected county additions replace entries in staged merged JSON; every
pre-existing county object is asserted unchanged. No voter records are used.
"""
import argparse
import collections
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import traceback

sys.dont_write_bytecode = True
DEFAULT = 'aransas borden bowie cass coleman cooke culberson henderson lamar medina redriver refugio roberts vanzandt ward zapata zavala'.split()
ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, separators=(',', ':'), allow_nan=False) + '\n')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def link(source, target):
    assert source.exists(), source
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        assert target.resolve() == source.resolve(), target
    else:
        assert not target.exists(), target
        target.symlink_to(source.resolve(), target_is_directory=source.is_dir())


def invoke(obj, args):
    before = sys.argv
    try:
        sys.argv = [str(obj.__file__), *map(str, args)]
        obj.main()
    finally:
        sys.argv = before


def merge(before, additions, expected):
    result = json.loads(json.dumps(before))
    assert set(additions['counties']) == set(expected)
    result['counties'].update(additions['counties'])
    for county, value in before['counties'].items():
        if county not in expected:
            assert result['counties'][county] == value, county
    sources = {json.dumps(s, sort_keys=True): s for s in before.get('sources', [])}
    sources.update({json.dumps(s, sort_keys=True): s for s in additions.get('sources', [])})
    if 'sources' in result:
        result['sources'] = list(sources.values())
    return result


def run(args, status):
    source = args.source_root.resolve()
    project = args.output.resolve() / 'project'
    assert project != source and source not in project.parents
    project.mkdir(parents=True, exist_ok=True)
    # Symlink read-only input subtrees, never a builder's output directory.
    for subdir in ['boundaries', 'other-counties-2026-10-20']:
        link(source / 'sources' / subdir, project / 'sources' / subdir)
    originals = {}
    for name in ['reference', 'county-reference', 'statewide', 'demographics', 'primary']:
        path = source / f'dashboard/data/{name}.json'
        originals[name] = read(path)
        write(project / f'dashboard/data/{name}.json', originals[name])
        status['input_hashes'][f'dashboard/data/{name}.json'] = digest(path)
    oldrefs = originals['reference']
    assert len({c['id'] for c in oldrefs}) == len(oldrefs)
    assert not set(args.counties) & {c['id'] for c in oldrefs}
    status['existing_counties'] = len(oldrefs)
    status['selected_counties'] = args.counties
    for path in (source / 'sources/census-atlas/raw').glob('*'):
        if path.is_file():
            link(path, project / 'sources/census-atlas/raw' / path.name)
    for county in args.counties:
        found = list(source.glob(f'sources/**/raw/{county}-block-points.json'))
        assert found, ('Uncached Census points', county)
        link(found[0], project / 'sources/census-atlas/raw' / found[0].name)
    link(source / 'sources/place-types/raw/texas-locales-2025.geojson',
         project / 'sources/place-types/raw/texas-locales-2025.geojson')

    expansion = module(source / 'dashboard/scripts/build_precinct_expansion.py', 'admission_expansion')
    expansion.ROOT = project
    expansion.BOUNDARIES = project / 'sources/boundaries'
    expansion.VTD = project / 'sources/other-counties-2026-10-20/hockley/vtd-check/geometry/VTDs_24PG.shp'
    expansion.RETURNS = project / 'sources/other-counties-2026-10-20/hockley/tlc-election24g.zip'
    geography = project / 'sources/precinct-expansion/geography'
    invoke(expansion, ['--offline', '--counties', *args.counties, '--output', geography])
    newrefs = read(geography / 'new-reference.json')
    assert {r['id'] for r in newrefs} == set(args.counties)
    for county in newrefs:
        for vintage in ['old', 'new']:
            ids = [p for group in county['groups'] for p in group[vintage]]
            assert len(ids) == len(set(ids)), (county['id'], vintage, 'partition')
    refs = oldrefs + newrefs
    assert refs[:len(oldrefs)] == oldrefs
    write(project / 'dashboard/data/reference.json', refs)
    status['completed'].append('reference: disjoint old/new native partitions and existing215 preserved')
    checkpoint(args, status)

    census = module(source / 'dashboard/scripts/build_demographics.py', 'admission_census')
    census.ROOT = project
    census.CACHED_RAW = project / 'sources/census-atlas/raw'
    census.BOUNDARY = project / 'sources/boundaries/26p/Precincts26P.shp'
    census_path = project / 'dashboard/data/demographics-additions.json'
    invoke(census, ['--offline', '--reference', project / 'dashboard/data/reference.json',
                   '--counties', *args.counties, '--output', census_path,
                   '--store', project / 'sources/census-atlas'])
    census_additions = read(census_path)
    merged_census = merge(originals['demographics'], census_additions, args.counties)
    write(project / 'dashboard/data/demographics.json', merged_census)
    status['completed'].append('Census: source totals conserved by existing builder; existing215 preserved')
    checkpoint(args, status)

    maps = module(source / 'dashboard/scripts/build_maps.py', 'admission_maps')
    maps.ROOT = project
    maps.SOURCE = project / 'sources/boundaries/26p/Precincts26P.shp'
    maps.USER_ARCHIVE = project / 'sources/boundaries/precincts26p.zip'
    maps.build(project / 'dashboard/data/reference.json', project / 'dashboard/data/maps',
               project / 'sources/map-atlas', args.counties)
    status['completed'].append('maps: exact ID/group joins, valid polygons and documented simplification')
    checkpoint(args, status)

    # Existing place builder can operate on a temporary classifier subset; restore
    # the full county reference immediately and merge only selected additions.
    county_reference = originals['county-reference']
    subset = json.loads(json.dumps(county_reference))
    subset['counties'] = {c: subset['counties'][c] for c in args.counties}
    places = module(source / 'dashboard/scripts/build_places.py', 'admission_places')
    places.ROOT = project
    write(project / 'dashboard/data/county-reference.json', subset)
    places_path = project / 'dashboard/places/additions.json'
    try:
        invoke(places, ['--offline', '--source-root', project, '--output', places_path])
    finally:
        write(project / 'dashboard/data/county-reference.json', county_reference)
    oldplaces = read(source / 'dashboard/places/texas.json')
    place_additions = read(places_path)
    merged_places = merge(oldplaces, place_additions, args.counties)
    write(project / 'dashboard/places/texas.json', merged_places)
    status['completed'].append('places: five categories plus residual partition VAP; existing counties preserved')

    primary_builder = module(source / 'dashboard/scripts/build_primary.py', 'admission_primary')
    primary = json.loads(json.dumps(originals['primary']))
    for county in newrefs:
        assert county['id'] not in primary_builder.CONTROLS, 'Verified primary source needs full builder'
        expected = {p for group in county['groups'] for p in group['new']}
        primary['counties'][county['id']] = {'precincts': {}, 'coverage': {
            'status': 'unavailable', 'expected_precincts': len(expected),
            'included_precincts': 0, 'missing_precincts': sorted(expected),
            'reason': 'No verified party-specific precinct ballot totals acquired; combined turnout and candidate totals cannot substitute.'}}
    for county, value in originals['primary']['counties'].items():
        assert primary['counties'][county] == value
    write(project / 'dashboard/data/primary.json', primary)
    write(project / 'dashboard/primary/2026.json', primary)
    status['completed'].append('primary: explicit unavailable for additions; verified existing data preserved')

    audit = {}
    for county in newrefs:
        slug = county['id']
        newids = {p for group in county['groups'] for p in group['new']}
        assert set(merged_census['counties'][slug]['precincts']) == newids
        assert set(merged_places['counties'][slug]['precincts']) == newids
        geo = read(project / f'dashboard/data/maps/{slug}.geojson')
        assert {f['properties']['precinct'] for f in geo['features']} == newids
        audit[slug] = {'precincts': len(newids), 'groups': len(county['groups']), 'years': {}}
        for year, vintage in [(2024, 'old'), (2026, 'new')]:
            universe = {p for group in county['groups'] for p in group[vintage]}
            cached = source / f'dashboard/data/cache/{slug}/{year}-series.json'
            days = read(cached)
            total = sum(sum(d['counts'].values()) for d in days)
            mapped = sum(sum(v for p, v in d['counts'].items() if p in universe) for d in days)
            unlocated = sum(sum(v for p, v in d['counts'].items() if p not in universe) for d in days)
            assert mapped + unlocated == total
            audit[slug]['years'][str(year)] = {'source_total': total, 'native_mapped': mapped,
                                               'unlocated': unlocated, 'cache_sha256': digest(cached)}
        for p, row in merged_places['counties'][slug]['precincts'].items():
            counts = row['counts']
            assert sum(counts[k] for k in ['city_vap', 'suburb_vap', 'fringe_vap', 'rural_vap', 'unclassified_vap']) == counts['vap']
    write(args.output / 'validation.json', audit)
    status['final_counties'] = len(refs)
    status['output_hashes'] = {str(p.relative_to(project)): digest(p)
                               for p in project.rglob('*.json') if p.is_file() and not p.is_symlink()}
    status['passed'] = True
    checkpoint(args, status)


def checkpoint(args, status):
    write(args.output / 'status.json', status)
    print(status['completed'][-1] if status['completed'] else 'Preparing retained inputs', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT.parent / 'texas-early-vote-2026-11-03')
    parser.add_argument('--output', type=Path, default=ROOT / 'analysis/county-recovery/admission')
    parser.add_argument('--counties', nargs='+', default=DEFAULT)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    status = {'started_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'passed': False,
              'completed': [], 'input_hashes': {}, 'method': 'Existing offline builders; isolated output; native normalization only; no vote allocation.'}
    try:
        run(args, status)
    except BaseException:
        status['error'] = traceback.format_exc()
        checkpoint(args, status)
        raise
