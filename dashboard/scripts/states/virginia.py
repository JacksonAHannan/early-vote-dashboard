#!/usr/bin/env python3
"""Refresh locality aggregates published by the DAL metrics producer; no voter rows."""
import argparse
import csv
from collections import defaultdict
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import re
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / 'sources/multistate/va'
OUT = ROOT / 'dashboard/data/states/va.json'
STARTS = {2024: '2024-09-20', 2026: '2026-09-18'}

def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'TurnoutResearch/1.0'}), timeout=35) as response:
        return response.read()

def timestamp(value):
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        return dt.datetime.strptime(value, '%d-%b-%Y %H:%M:%S')

def parse_series(payload, year):
    """Morning DAL snapshots describe the preceding date; retain latest snapshot."""
    by_day = {}
    for row in csv.DictReader(io.StringIO(payload.decode('utf-8-sig'))):
        if row['FILEDATE'] == 'string':
            continue
        stamp = timestamp(row['FILEDATE'])
        day = (stamp.date() - dt.timedelta(days=1)).isoformat()
        values = {method: int(row[column]) for method, column in [('total', 'COUNTABLE'), ('mail', 'MAIL_IN'), ('in_person', 'ON_MACHINE')]}
        if any(v < 0 for v in values.values()):
            raise ValueError('Negative source turnout')
        if day not in by_day or stamp > by_day[day][0]:
            by_day[day] = (stamp, values)
    return {day: values for day, (_, values) in sorted(by_day.items()) if day < f'{year}-11-05'}

def locality_names():
    path = STORE / 'census-counties.txt'
    if not path.exists():
        url = 'https://www2.census.gov/geo/docs/maps-data/data/gazetteer/Gaz_counties_national.zip'
        raw = fetch(url)
        archive = zipfile.ZipFile(io.BytesIO(raw))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(archive.read(archive.namelist()[0]).decode('cp1252'))
    rows = csv.DictReader(io.StringIO(path.read_text()), delimiter='\t')
    return {r['NAME'].upper(): {'id': r['GEOID'], 'fips': r['GEOID'], 'name': r['NAME']} for r in rows if r['USPS'] == 'VA'}

def collect_archive(raw, year, through, names):
    archive = zipfile.ZipFile(io.BytesIO(raw))
    result = []
    for member in archive.namelist():
        if not member.startswith('byLOCALITY_NAME/') or member.count('/') != 4 or not member.endswith('.csv'):
            continue
        label = member.split('/')[1]
        if label not in names:
            raise ValueError(f'Unmapped locality: {label}')
        county = names[label]
        previous = {}
        last_date = None
        for day, values in parse_series(archive.read(member), year).items():
            if day < STARTS[year]:
                previous, last_date = values, day
                continue
            if year == 2026 and day > through:
                continue
            for method, votes in values.items():
                base = {'year': year, 'date': day, 'county': county['id'], 'county_name': county['name'], 'precinct': None, 'method': method}
                result.append({**base, 'measure': 'cumulative', 'votes': votes})
                if last_date is not None and (dt.date.fromisoformat(day) - dt.date.fromisoformat(last_date)).days == 1 and votes >= previous[method]:
                    result.append({**base, 'measure': 'daily', 'votes': votes - previous[method]})
            previous, last_date = values, day
    if len({r['county'] for r in result}) != 133:
        raise ValueError('Archive must cover all 133 Virginia localities')
    return result


def write_precinct_shards(raw, through, names, source):
    """Current-cycle published residence labels; no boundary or alias matching."""
    archive = zipfile.ZipFile(io.BytesIO(raw))
    by_county = defaultdict(list)
    sorted_names = sorted(names, key=len, reverse=True)
    for member in archive.namelist():
        if not member.startswith('byLOCALITY_PRECINCT_NAME/') or member.count('/') != 4 or not member.endswith('.csv'):
            continue
        native_label = member.split('/')[1]
        locality = next((name for name in sorted_names if native_label.startswith(name + ' ')), None)
        if locality is None:
            raise ValueError('Unmapped native precinct locality')
        label = native_label[len(locality) + 1:]
        if not re.fullmatch(r'[0-9]+[A-Za-z]? - .+', label):
            raise ValueError('Unverified native precinct code/name label')
        by_county[locality].append((label, member))
    destination = STORE / 'precincts'
    destination.mkdir(parents=True, exist_ok=True)
    generated = dt.datetime.now(dt.timezone.utc).isoformat()
    index = []
    for locality, members in by_county.items():
        county = names[locality]
        observations = []
        for label, member in members:
            previous = {}
            last_date = None
            for day, values in parse_series(archive.read(member), 2026).items():
                if day < STARTS[2026]:
                    previous, last_date = values, day
                    continue
                if day > through:
                    continue
                for method, votes in values.items():
                    base = {'year': 2026, 'date': day, 'county': county['id'], 'county_name': county['name'], 'precinct': label, 'method': method, 'scope': 'reported_residence_precinct', 'comparable': False}
                    observations.append({**base, 'measure': 'cumulative', 'votes': votes})
                    if last_date and (dt.date.fromisoformat(day) - dt.date.fromisoformat(last_date)).days == 1 and votes >= previous[method]:
                        observations.append({**base, 'measure': 'daily', 'votes': votes - previous[method]})
                previous, last_date = values, day
        latest_date = max((r['date'] for r in observations), default=None)
        payload = {'schema_version': 1, 'state': 'va', 'county': county['id'], 'county_name': county['name'], 'generated_at': generated, 'through': latest_date, 'requested_through': through, 'scope': 'reported_residence_precinct', 'comparable': False, 'observations': observations}
        path = destination / (county['id'] + '.json')
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(payload, separators=(',', ':')))
        temp.replace(path)
        index.append({'id': county['id'], 'name': county['name'], 'path': 'precincts/' + path.name, 'precincts': len(members), 'observations': len(observations), 'latest_date': latest_date})
    payload = {'schema_version': 1, 'state': 'va', 'generated_at': generated, 'through': max((r['latest_date'] for r in index if r['latest_date']), default=None), 'requested_through': through, 'scope': 'reported_residence_precinct', 'comparable': False, 'counties': index, 'sources': [source], 'notes': ['2026 published precinct code/name labels are retained separately, including names that share a numeric code. No aliases, historical boundaries, ratios or map geometry are inferred. Morning source timestamps describe the preceding calendar date. The published precinct series can stop earlier than the locality series; only actually dated precinct snapshots are emitted and stale dates are never carried forward.']}
    path = STORE / 'precinct-daily.json'
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(payload, separators=(',', ':')))
    temp.replace(path)
    return payload

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--through', default=(dt.date.today() - dt.timedelta(days=1)).isoformat())
    args = parser.parse_args()
    dt.date.fromisoformat(args.through)
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    observations = {(r['year'], r['date'], r['county'], r['precinct'], r['method'], r['measure']): r for r in old.get('observations', [])}
    sources = {r['url']: r for r in old.get('sources', [])}
    errors = []
    names = locality_names()
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for year in (2024, 2026):
        url = f'https://digitalpollwatchers.org/files/DALTracker/{year}_November_General/metrics/{year}_November_General-DAL-metrics.zip'
        try:
            raw = fetch(url)
            rows = collect_archive(raw, year, args.through, names)
            sha = hashlib.sha256(raw).hexdigest()
            raw_path = STORE / 'raw' / f'{sha}.zip'
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_bytes(raw)
            observations = {key: value for key, value in observations.items() if key[0] != year}
            for row in rows:
                observations[(row['year'], row['date'], row['county'], row['precinct'], row['method'], row['measure'])] = row
            sources[url] = {'url': url, 'retrieved_at': now, 'sha256': sha, 'description': f'EPEC published aggregate metrics from Virginia ELECT Daily Absentee List, {year}; independent republisher, not official transport.'}
            if year == 2026:
                write_precinct_shards(raw, args.through, names, sources[url])
        except Exception as error:
            errors.append({'url': url, 'error': str(error)})
    observed_ids = {r['county'] for r in observations.values()}
    old_counties = {r['id']: r for r in old.get('counties', [])}
    counties = [{**old_counties.get(r['id'], {}), **r} for r in names.values() if r['id'] in observed_ids]
    output = {'schema_version': 1, 'id': 'va', 'name': 'Virginia', 'generated_at': now, 'through': args.through, 'election_dates': {'2024': '2024-11-05', '2026': '2026-11-03'}, 'start_dates': {str(k): v for k, v in STARTS.items()}, 'observations': sorted(observations.values(), key=lambda r: (r['year'], r['date'], r['county'], r['method'], r['measure'])), 'counties': counties, 'sources': list(sources.values()), 'errors': errors, 'notes': ['Virginia ELECT does not publish live aggregate turnout on its certified-turnout page. Locality series here are EPEC published aggregate metrics derived from official Daily Absentee List files, with source hashes retained.', 'Morning DAL file dates are assigned to the preceding calendar day. Values describe the reporting snapshot, which can revise prior records; daily turnout is a nonnegative difference between consecutive dated snapshots, not a reconstructed final ballot-return history.', 'COUNTABLE is total; MAIL_IN is mail and ON_MACHINE is in person. Total can include separately countable federal/provisional ballots, so the two method subtotals may not exhaust total.', 'No party registration is available in Virginia. Precinct boundary comparability has not been established; aggregate precinct files are preserved in the source archives but only locality comparisons are published.']}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUT.with_suffix('.tmp')
    temp.write_text(json.dumps(output, separators=(',', ':')))
    temp.replace(OUT)
    print(json.dumps({'state': 'va', 'observations': len(output['observations']), 'counties': len(counties), 'errors': errors}))

if __name__ == '__main__':
    main()
