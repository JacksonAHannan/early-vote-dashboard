"""Read-only Texas geography, Census and primary reference integrity audit.

Extends the count/partition oracles in verify_demographics.py, verify_primary.py
and expansion.py to all 215 precinct counties plus all 254 county references.
No geospatial package, source refresh, vote allocation or API is used.

TURNOUT_AUDIT_ROOT=/tmp/turnout-texas-audit-20261025 python dashboard/tests/texas_reference_stress.py
Raw public source files can reside separately in TURNOUT_AUDIT_SOURCE_ROOT.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
from collections import Counter
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
ROOT = Path(os.environ.get('TURNOUT_AUDIT_ROOT', PROJECT))
SOURCE_ROOT = Path(os.environ.get('TURNOUT_AUDIT_SOURCE_ROOT', PROJECT))
OUT = PROJECT / 'analysis/texas-stress/reference-integrity.json'
FIELDS = {'population': 'total', 'vap': 'vap', 'hispanic': 'hisp',
          'white_nh': 'anglo', 'black': 'black', 'asian': 'asian',
          'hispanic_vap': 'hispvap', 'white_nh_vap': 'anglovap',
          'black_vap': 'blackvap', 'asian_vap': 'asianvap',
          'non_white': 'nanglo', 'non_white_vap': 'nanglovap'}
# Existing independently checked county ballot-control oracle (verify_primary.py).
PRIMARY_TOTALS = {'dallas': (791, 280326, 103818), 'montgomery': (121, 31510, 80092),
                  'hays': (88, 33914, 18643), 'ellis': (60, 18894, 25994),
                  'mclennan': (95, 15093, 23727), 'madison': (4, 419, 1887)}


def load(path):
    return json.loads(path.read_text())


def normalize(value):
    return re.sub(r'[^a-z0-9]', '', value.lower())


def run():
    counts = Counter()
    flags = []
    inputs = {}
    source_paths = {}
    def check(value, context):
        counts['assertions'] += 1
        assert value, context
    def read(name):
        path = ROOT / 'dashboard/data' / name
        raw = path.read_bytes()
        inputs[name] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)
    def provenance(source):
        check(isinstance(source.get('sha256'), str) and re.fullmatch('[0-9a-f]{64}', source['sha256']), ('source hash', source))
        relative = Path(source['path'])
        check(not relative.is_absolute() and '..' not in relative.parts, ('source path', source))
        path = ROOT / relative
        if not path.exists():
            path = SOURCE_ROOT / relative
        check(path.is_file(), ('retained aggregate source missing', str(relative)))
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        check(digest == source['sha256'], ('retained source changed', str(relative)))
        if 'bytes' in source:
            check(path.stat().st_size == source['bytes'], ('source size', str(relative)))
        counts['source_hashes'] += 1
        source_paths[source['path']] = path
        return path
    def census_counts(row, context):
        check(all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in row.values()), (context, 'nonnegative integer Census counts'))
        for key in FIELDS:
            denominator = row['vap'] if key.endswith('_vap') else row['population']
            check(row[key] <= denominator, (context, 'bounded', key))
        check(row['under18'] + row['vap'] == row['population'], (context, 'adult/child complement'))
        check(row['non_white'] + row['white_nh'] == row['population'], (context, 'nonwhite complement'))
        check(row['non_white_vap'] + row['white_nh_vap'] == row['vap'], (context, 'adult nonwhite complement'))
        counts['census_rows'] += 1
    refs = {r['id']: r for r in read('reference.json')}
    census = read('demographics.json')
    county_ref = read('county-reference.json')
    primary = read('primary.json')
    check(len(refs) == 215, '215 precinct-reference counties')
    check(set(refs) == set(census['counties']), 'Census/precinct county universe')
    check(len(county_ref['counties']) == 254, '254 direct county references')
    check(set(refs) <= set(county_ref['counties']), 'every precinct county has direct county reference')
    check(set(primary['counties']) <= set(refs), 'primary has no foreign county')
    for source in county_ref['sources'] + census['sources'] + primary['sources']:
        provenance(source)
    county_census_source = next(s for s in county_ref['sources'] if s['path'].endswith('counties_pop.txt'))
    with source_paths[county_census_source['path']].open(newline='') as stream:
        raw_census = {'48' + row['FIPS'].zfill(3): row for row in csv.DictReader(stream)}
    raw_results = load(source_paths[next(s['path'] for s in county_ref['sources'] if s['path'].endswith('County.json'))])
    state_results = load(source_paths[next(s['path'] for s in county_ref['sources'] if s['path'].endswith('Federal.json'))])
    state_presidential = next(r for r in state_results['Races'] if r['id'] == 1001)
    state_candidates = {str(c['ID']): c for c in state_presidential['Candidates']}
    check(len(raw_census) == len(raw_results) == 254, '254 native county source rows')
    direct_fips = set()
    for county_id, county in county_ref['counties'].items():
        fips = county['fips']
        check(fips not in direct_fips, ('duplicate county FIPS', county_id)); direct_fips.add(fips)
        native_census = raw_census[fips]
        native_result = raw_results[fips]
        check(normalize(county['name']) == normalize(native_census['FENAME']) == normalize(native_result['N']), ('county identity', county_id))
        census_counts(county['counts'], county_id)
        for field, source_field in FIELDS.items():
            check(county['counts'][field] == int(native_census[source_field]), ('native county Census', county_id, field))
            counts['direct_county_census_cells'] += 1
        race = native_result['Races']['1001']
        for party, key in [('harris', '340860'), ('trump', '9240')]:
            check(county[party] == race['C'][key]['V'], ('official whole-county presidential result', county_id, party))
            check(county[party] >= 0, ('county presidential nonnegative', county_id, party))
            counts['official_county_presidential_cells'] += 1
        check(county['harris'] + county['trump'] > 0, ('county presidential denominator', county_id))
    for party, key in [('harris', '340860'), ('trump', '9240')]:
        check(sum(c[party] for c in county_ref['counties'].values()) == state_candidates[key]['V'], ('official statewide presidential control', party))
    for county_id, ref in refs.items():
        old = [p for g in ref['groups'] for p in g['old']]
        new = [p for g in ref['groups'] for p in g['new']]
        check(len(old) == len(set(old)) and len(new) == len(set(new)), ('geography partition', county_id))
        check(all(g['old'] and g['new'] for g in ref['groups']), ('nonempty groups', county_id))
        check(all(isinstance(p, str) and p for p in old + new), ('native precinct identifiers', county_id))
        old_group = {p: i for i, g in enumerate(ref['groups']) for p in g['old']}
        new_group = {p: i for i, g in enumerate(ref['groups']) for p in g['new']}
        exact = [tuple(pair) for pair in ref['exact_pairs']]
        check(len(exact) == len(set(exact)), ('unique exact pairs', county_id))
        for a, b in exact:
            check(a in old_group and b in new_group and old_group[a] == new_group[b], ('exact pair common component', county_id, a, b))
            group = ref['groups'][old_group[a]]
            if len(group['old']) != 1 or len(group['new']) != 1:
                counts['exact_pairs_in_larger_components'] += 1
        check(len({a for a, b in exact}) == len(exact) and len({b for a, b in exact}) == len(exact), ('exact pair one-to-one IDs', county_id))
        for source in ref['references'].values():
            if isinstance(source, dict) and 'path' in source and 'sha256' in source:
                provenance(source)
        pres_source = provenance(ref['references']['presidential'])
        with pres_source.open(newline='') as stream:
            pres_rows = list(csv.DictReader(stream))
        check(len({r['precinct'] for r in pres_rows}) == len(pres_rows), ('presidential duplicate native IDs', county_id))
        native_pres = {r['precinct']: {'harris': int(r['harris']), 'trump': int(r['trump'])} for r in pres_rows}
        check(native_pres == ref['presidential'], ('presidential reference equals retained source', county_id))
        check(set(native_pres) <= set(old), ('presidential source foreign native geography', county_id))
        check(all(isinstance(n, int) and n >= 0 for values in native_pres.values() for n in values.values()), ('presidential nonnegative', county_id))
        totals = {p: sum(v[p] for v in native_pres.values()) for p in ['harris', 'trump']}
        official = {p: county_ref['counties'][county_id][p] for p in totals}
        if totals != official:
            counts['presidential_reference_not_whole_county'] += 1
            qualification = ref['references']['presidential'].get('qualification')
            if not qualification or any(totals[p] > official[p] for p in totals):
                flags.append({'county': county_id, 'issue': 'precinct presidential source differs from whole-county certified scope',
                              'precinct_source': totals, 'official_county': official, 'qualification': qualification,
                              'classification': 'documented upstream retabulation variance' if qualification else 'missing inline qualification; inspect existing source documentation'})
        counts['presidential_precinct_rows'] += len(native_pres)
        data = census['counties'][county_id]
        check(set(data['precincts']) == set(new), ('Census native precinct membership', county_id))
        for precinct, record in data['precincts'].items():
            census_counts(record['counts'], (county_id, precinct))
        for kind in ['assigned_totals', 'census_totals']:
            census_counts(data[kind], (county_id, kind))
        for field in data['assigned_totals']:
            check(sum(p['counts'][field] for p in data['precincts'].values()) == data['assigned_totals'][field], ('precinct count partition', county_id, field))
            check(data['assigned_totals'][field] == data['census_totals'][field] == county_ref['counties'][county_id]['counts'][field], ('precinct/direct county Census totals', county_id, field))
            counts['precinct_county_census_cells'] += 1
        coverage = data['coverage']
        check(coverage['source_blocks'] == coverage['assigned_blocks'] + coverage['unmatched_blocks'], ('block coverage accounting', county_id))
        check(coverage['source_population'] == coverage['assigned_population'] == data['assigned_totals']['population'], ('population coverage accounting', county_id))
        check(coverage['unmatched_populated_blocks'] == 0 and coverage['population_coverage_pct'] == 100, ('complete assigned population', county_id))
        check(coverage['precincts'] == len(new), ('demographic coverage precinct count', county_id))
        geo = read(f'maps/{county_id}.geojson')
        check(geo['type'] == 'FeatureCollection' and geo['county'] == county_id, ('map county identity', county_id))
        check(str(geo['census_fips']) == county_ref['counties'][county_id]['fips'], ('map explicit Census FIPS', county_id))
        features = geo['features']
        check(len(features) == len(new) == len({f['id'] for f in features}), ('map feature/native partition size', county_id))
        check({f['properties']['precinct'] for f in features} == set(new), ('map exact native coverage', county_id))
        bbox = geo['bbox']
        for feature in features:
            props = feature['properties']
            check(feature['id'] == props['id'] == f"{county_id}:{props['precinct']}" and props['county'] == county_id, ('stable linked map ID', county_id))
            check(props['group'] == new_group[props['precinct']], ('linked map common-geography group', county_id, props['precinct']))
            geometry = feature['geometry']
            check(geometry['type'] in ['Polygon', 'MultiPolygon'], ('polygon map geometry', county_id))
            polygons = geometry['coordinates'] if geometry['type'] == 'MultiPolygon' else [geometry['coordinates']]
            check(bool(polygons), ('nonempty map geometry', county_id))
            for polygon in polygons:
                for ring in polygon:
                    check(len(ring) >= 4 and ring[0] == ring[-1], ('closed polygon ring', county_id, props['precinct']))
                    for point in ring:
                        check(len(point) == 2 and all(math.isfinite(v) for v in point) and -180 <= point[0] <= 180 and -90 <= point[1] <= 90, ('finite geographic coordinates', county_id))
                        check(bbox[0] - 1e-5 <= point[0] <= bbox[2] + 1e-5 and bbox[1] - 1e-5 <= point[1] <= bbox[3] + 1e-5, ('county map bbox', county_id))
                        counts['map_coordinate_pairs'] += 1
            counts['map_features'] += 1
        counts['old_precincts'] += len(old); counts['new_precincts'] += len(new); counts['geography_groups'] += len(ref['groups'])
    supported = set()
    for county_id, county in primary['counties'].items():
        native = {p for g in refs[county_id]['groups'] for p in g['new']}
        precincts = county['precincts']; coverage = county['coverage']
        check(set(precincts) <= native, ('primary native precinct match', county_id))
        check(set(coverage['missing_precincts']) == native - set(precincts), ('primary explicit missing IDs', county_id))
        check(coverage['included_precincts'] == len(precincts) and coverage['expected_precincts'] == len(native), ('primary coverage accounting', county_id))
        totals = Counter()
        for precinct, row in precincts.items():
            values = row['counts']
            check(all(isinstance(n, int) and n >= 0 for n in values.values()), ('primary count domain', county_id, precinct))
            check(values['primary_dem'] + values['primary_rep'] == values['primary_total'], ('primary denominator', county_id, precinct))
            check(row['quality']['all_voting_modes'] and row['quality']['election_date'] == '2026-03-03', ('primary declared source scope', county_id))
            totals.update(values); counts['primary_precinct_rows'] += 1
        if not precincts:
            check(coverage['status'] == 'unavailable', ('absent primary is unknown', county_id))
            continue
        supported.add(county_id)
        n, dem, rep = PRIMARY_TOTALS[county_id]
        check((len(precincts), totals['primary_dem'], totals['primary_rep']) == (n, dem, rep), ('independently controlled primary totals', county_id))
        check(dict(totals) == county['assigned_totals'], ('primary assigned totals', county_id))
        complete_groups = sum(all(p in precincts for p in g['new']) for g in refs[county_id]['groups'])
        check(coverage['complete_groups'] == complete_groups, ('primary complete-group membership', county_id))
        check(coverage['status'] == ('complete' if set(precincts) == native else 'partial'), ('primary honest complete/partial status', county_id))
    check(supported == set(PRIMARY_TOTALS), 'only six supported primary counties, no invented coverage')
    for path, digest in inputs.items():
        check(hashlib.sha256((ROOT / 'dashboard/data' / path).read_bytes()).hexdigest() == digest, ('audit input unchanged', path))
    report = {'status': 'passed', 'root': str(ROOT), 'source_root': str(SOURCE_ROOT), 'counts': dict(counts),
              'precinct_counties': len(refs), 'direct_counties': len(county_ref['counties']),
              'primary_supported_counties': sorted(supported), 'primary_unsupported_counties': len(refs) - len(supported),
              'reference_scope_flags': flags, 'sha256_inputs': inputs,
              'limitations': ['Coordinate/ring checks verify rendered identifier linkage and basic bounds; they do not independently recompute polygon topology, block assignment or geographic overlap.',
                              'TLC-derived precinct presidential sources are partial/retabulated in some counties; certified whole-county totals remain a separate official source and are never allocated to precincts.']}
    OUT.parent.mkdir(parents=True, exist_ok=True); OUT.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'sha256_inputs'}, indent=2))


if __name__ == '__main__':
    run()
