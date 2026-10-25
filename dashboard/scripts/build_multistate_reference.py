#!/usr/bin/env python3
"""Retain Census county geometry and ACS adult composition for added states."""
import argparse
import csv
import hashlib
import io
import json
import re
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / 'sources/multistate/reference'
OUT = ROOT / 'dashboard/data/states'
STATES = {'ga': ('13', 159), 'nc': ('37', 100), 'va': ('51', 133), 'nv': ('32', 17)}
CENSUS = 'https://www2.census.gov/programs-surveys/decennial/rdo/datasets/2024/2024-cvap/CVAP_2020-2024_ACS_csv_files.zip'
MAP = 'https://tigerweb.geo.census.gov/arcgis/rest/services/Census2020/tigerWMS_Census2020/MapServer/82/query'
VA_RETURNS = 'https://va2.elstats.civera.com/api/download_contest/161256_table.csv?split_party=false'


def acquire(name, url, offline):
    p = RAW / name
    if not p.exists():
        if offline:
            raise FileNotFoundError(p)
        data = urllib.request.urlopen(url, timeout=90).read()
        p.write_bytes(data)
    return p


def source(p, url):
    return {'url': url, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
            'path': str(p.relative_to(ROOT)), 'retrieved_at': datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat()}


def build(offline=False):
    RAW.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    archive = acquire('CVAP_2020-2024_ACS_csv_files.zip', CENSUS, offline)
    with zipfile.ZipFile(archive) as z:
        rows = list(csv.DictReader(io.StringIO(z.read('County.csv').decode('utf-8-sig'))))
    census = {}
    for row in rows:
        fips = row['geoid'].split('US')[1]
        if fips[:2] in {v[0] for v in STATES.values()}:
            census.setdefault(fips, {})[int(row['lnnumber'])] = row

    def one(item):
        state, (fips, expected) = item
        url = MAP + '?' + urllib.parse.urlencode({'where': f"STATE='{fips}'", 'outFields': 'GEOID,NAME,STATE,COUNTY', 'f': 'geojson', 'outSR': 4326, 'geometryPrecision': 3, 'maxAllowableOffset': .005})
        geometry_path = acquire(f'{state}-counties.geojson', url, offline)
        geometry = json.loads(geometry_path.read_text())
        assert len(geometry['features']) == expected
        counties = {}
        for feature in geometry['features']:
            props = feature['properties']
            geoid = props['GEOID']
            assert geoid.startswith(fips) and geoid in census
            lines = census[geoid]
            def count(line, field='adu_est'):
                return int(lines[line][field])
            vap = count(1)
            population = count(1, 'tot_est')
            counts = {'vap': vap, 'population': population,
                      'white_nh_vap': count(7), 'black_nh_vap': count(5),
                      'asian_nh_vap': count(4), 'hispanic_vap': count(13),
                      'non_white_vap': vap - count(7), 'under18': population - vap}
            assert 0 < vap <= population
            metrics = {k: 100 * counts[k] / (population if k == 'under18' else vap)
                       for k in ('non_white_vap', 'white_nh_vap', 'black_nh_vap', 'asian_nh_vap', 'hispanic_vap', 'under18')}
            assert all(0 <= x <= 100 for x in metrics.values())
            counties[geoid] = {'id': geoid, 'fips': geoid,
                               'name': lines[1]['geoname'].split(',')[0],
                               'counts': counts, 'demographics': metrics}
        result = {'state': state, 'counties': counties, 'metrics': [
            {'id': k, 'label': label} for k, label in [
                ('non_white_vap', 'Total non-white'), ('hispanic_vap', 'Hispanic'),
                ('black_nh_vap', 'Black non-Hispanic'), ('asian_nh_vap', 'Asian non-Hispanic'),
                ('white_nh_vap', 'White non-Hispanic'), ('under18', 'Under 18')]],
            'vintage': '2020–2024 ACS · age 18+ (Under 18 uses total population)',
            'sources': [source(archive, CENSUS), source(geometry_path, url)]}
        if state == 'va':
            returns = acquire('va-president-2024.csv', VA_RETURNS, offline)
            data = list(csv.reader(io.StringIO(returns.read_text())))
            assert data[0][2:4] == ['Kamala D. Harris', 'Donald J. Trump']
            def canonical(name):
                return re.sub('[^a-z0-9]', '', name.lower().replace(' county', ''))
            localities = {canonical(row[1]): (int(row[2]), int(row[3])) for row in data if row[0] == 'Locality'}
            assert len(localities) == 133
            for county in counties.values():
                county['harris'], county['trump'] = localities[canonical(county['name'])]
            state_row = next(row for row in data if row[0] == 'State')
            assert sum(c['harris'] for c in counties.values()) == int(state_row[2]) == 2335395
            assert sum(c['trump'] for c in counties.values()) == int(state_row[3]) == 2075085
            result['sources'].append(source(returns, VA_RETURNS))
        (OUT / f'{state}-reference.json').write_text(json.dumps(result, indent=2) + '\n')
        (OUT / f'{state}-map.json').write_text(json.dumps(geometry, separators=(',', ':')) + '\n')
        return state, len(counties)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = dict(pool.map(one, STATES.items()))
    print(json.dumps(results))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true')
    build(parser.parse_args().offline)
