#!/usr/bin/env python3
"""Official Clark/Washoe early turnout. Voter rows are processed only in memory."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / 'sources/multistate/nv'
OUT = ROOT / 'dashboard/data/states/nv.json'
STARTS = {2024: '2024-10-19', 2026: '2026-10-17'}
COUNTIES = [{'id': '32003', 'fips': '32003', 'name': 'Clark County', 'harris': 520187, 'trump': 493052}, {'id': '32031', 'fips': '32031', 'name': 'Washoe County', 'harris': 130071, 'trump': 127443}]

def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'TurnoutResearch/1.0'}), timeout=20) as response:
        return response.read()

def parse_date(value):
    value = value.strip().split(' ')[0]
    if not value:
        return None
    for pattern in ('%m/%d/%Y', '%Y-%m-%d'):
        try:
            return dt.datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            pass
    raise ValueError('Unrecognized source date')

def csv_rows(raw):
    if raw.startswith(b'PK'):
        archive = zipfile.ZipFile(io.BytesIO(raw))
        members = [x for x in archive.namelist() if x.lower().endswith(('.csv', '.txt'))]
        if len(members) != 1:
            raise ValueError('Expected one data file in source archive')
        raw = archive.read(members[0])
    text = raw.decode('utf-8-sig', errors='replace')
    rows = csv.DictReader(io.StringIO(text))
    if not rows.fieldnames or not any('PRECINCT' == x.strip() for x in rows.fieldnames):
        raise ValueError('Not an official precinct turnout CSV')
    return rows

def aggregate(raw, kind, year):
    """Only geography, event date and registration-party counts survive parsing."""
    counts = Counter()
    parties = defaultdict(Counter)
    seen = set()
    raw_rows = duplicates = 0
    latest_date = None
    for row in csv_rows(raw):
        raw_rows += 1
        election_code = row.get('ELECTION CODE', row.get('ELECTION_CODE', '')).strip().upper()
        if election_code and election_code not in {f'{str(year)[2:]}G', f'{str(year)[2:]}GE'}:
            raise ValueError('Source contains a different election, not the general')
        if kind == 'clark_early':
            day = parse_date(row['ACTIVITY DATE'])
            identity = row['IDNUMBER'].strip()
            party = None  # PARTY in this file is ballot type, always NA in a general.
        elif kind == 'clark_mail':
            if row.get('RETURN_CODE', '').strip().upper() in {'UNDELIVERABLE', 'CANCELED', 'CANCELLED'}:
                continue
            day = parse_date(row['BALLOT_RECEIVE_DATE'])
            identity = row['IDNUMBER'].strip()
            party = row['VOTER_REG_PARTY'].strip() or 'Unknown'
        elif kind == 'washoe_early':
            day = parse_date(row['DATE_VOTED'])
            identity = row['VOTER_ID'].strip()
            party = row['VOTER_REG_PARTY'].strip() or 'Unknown'
        elif kind == 'washoe_mail':
            if row['BALLOT_STATUS'].strip().lower() not in {'accepted', 'returned', 'signature cure needed', 'contact county clerk'}:
                continue
            day = parse_date(row['BALLOT_RETURNED_DATE'])
            identity = row['VOTER_ID'].strip()
            party = row['VOTER_REG_PARTY'].strip() or 'Unknown'
        else:
            raise ValueError('Unknown collector kind')
        if day is None:
            continue
        if not day.startswith(str(year)):
            raise ValueError('Source contains turnout from another election year')
        if not identity:
            raise ValueError('Blank source voter identifier prevents deduplication')
        if identity in seen:
            duplicates += 1
            continue
        seen.add(identity)
        precinct = row['PRECINCT'].strip()
        if not re.fullmatch(r'[A-Za-z0-9 .-]+', precinct):
            raise ValueError('Invalid source precinct identifier')
        latest_date = max(latest_date or day, day)
        for geography in (None, precinct):
            counts[(day, geography)] += 1
            if party:
                parties[(day, geography)][party] += 1
    entries = [{'date': day, 'precinct': precinct, 'votes': votes, **({'breakdowns': {'party': dict(parties[(day, precinct)])}} if parties[(day, precinct)] else {})} for (day, precinct), votes in counts.items()]
    return {'rows': entries, 'raw_rows': raw_rows, 'duplicate_rows': duplicates, 'voters': len(seen), 'latest_event_date': latest_date}

def acquire(url, kind, year, use_cache=False):
    cache = STORE / 'aggregate-cache' / (hashlib.sha256(url.encode()).hexdigest() + '.json')
    if use_cache and cache.exists():
        return json.loads(cache.read_text())
    raw = fetch(url)
    data = aggregate(raw, kind, year)
    sha = hashlib.sha256(raw).hexdigest()
    data['source'] = {'url': url, 'retrieved_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'sha256': sha, 'description': {'clark_early': 'Clark County daily in-person early turnout, source voter rows aggregated in memory.', 'clark_mail': 'Clark County returned mail ballots, excluding undeliverable/canceled; includes acceptance and signature-pending returns.', 'washoe_early': 'Washoe County cumulative in-person turnout, aggregated in memory.', 'washoe_mail': 'Washoe County returned mail ballots: Accepted, Returned, Signature Cure Needed and Contact County Clerk statuses.'}[kind]}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data, separators=(',', ':')))
    (STORE / 'raw').mkdir(parents=True, exist_ok=True)
    # Raw voter files intentionally never touch disk. This is the public aggregate artifact.
    (STORE / 'raw' / (sha + '.json')).write_text(json.dumps(data, separators=(',', ':')))
    return data

def make_rows(data, county, year, method, through):
    """Event-dated reported counts; cumulative is available only for a complete prefix."""
    by_date = defaultdict(list)
    for row in data:
        if row['date'] <= through:
            by_date[row['date']].append(row)
    output = []
    cumulative = Counter()
    cumulative_parties = defaultdict(Counter)
    for day in sorted(by_date):
        for row in by_date[day]:
            base = {'year': year, 'date': day, 'county': county['id'], 'county_name': county['name'], 'precinct': row['precinct'], 'method': method}
            output.append({**base, 'measure': 'daily', 'votes': row['votes'], **({'breakdowns': row['breakdowns']} if row.get('breakdowns') else {})})
            cumulative[row['precinct']] += row['votes']
            cumulative_parties[row['precinct']].update(row.get('breakdowns', {}).get('party', {}))
        for precinct, votes in cumulative.items():
            base = {'year': year, 'date': day, 'county': county['id'], 'county_name': county['name'], 'precinct': precinct, 'method': method, 'measure': 'cumulative', 'votes': votes}
            if cumulative_parties[precinct]:
                base['breakdowns'] = {'party': dict(cumulative_parties[precinct])}
            output.append(base)
    return output

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--through', default=(dt.date.today() - dt.timedelta(days=1)).isoformat())
    args = parser.parse_args()
    through = dt.date.fromisoformat(args.through)
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    observations = {(r['year'], r['date'], r['county'], r['precinct'], r['method'], r['measure']): r for r in old.get('observations', [])}
    sources = {r['url']: r for r in old.get('sources', [])}
    reference_sources = STORE / 'reference-sources.json'
    if reference_sources.exists():
        for source in json.loads(reference_sources.read_text()):
            sources[source['url']] = source
    errors = []
    new_rows = []
    tasks = []
    for year in (2024, 2026):
        start = dt.date.fromisoformat(STARTS[year])
        for offset in range(14):
            day = start + dt.timedelta(days=offset)
            if year == 2026 and day > through:
                break
            tasks.append((f'https://elections.clarkcountynv.gov/VoterRequestsTV/EVMB/ev_{day:%Y%m%d}.zip', 'clark_early', year, day.isoformat()))
    early = defaultdict(dict)
    def load(task):
        url, kind, year, day = task
        try:
            data = acquire(url, kind, year, use_cache=year == 2024)
            if any(r['date'] != day for r in data['rows']):
                raise ValueError('Daily source contains a different event date')
            return task, data, None
        except Exception as error:
            return task, None, str(error)
    with ThreadPoolExecutor(max_workers=4) as executor:
        for (url, kind, year, day), data, error in executor.map(load, tasks):
            if error:
                errors.append({'url': url, 'error': error})
            else:
                sources[url] = data['source']
                early[year][day] = data['rows']
    for year, dates in early.items():
        start = dt.date.fromisoformat(STARTS[year])
        prefix = []
        for offset in range(14):
            day = (start + dt.timedelta(days=offset)).isoformat()
            if day not in dates:
                break
            prefix += dates[day]
        limit = args.through if year == 2026 else f'{year}-11-04'
        # Successful dates outside a missing prefix still retain independent daily counts.
        supported = make_rows(prefix, COUNTIES[0], year, 'in_person', limit)
        prefix_dates = {x['date'] for x in prefix}
        for day, rows in dates.items():
            if day not in prefix_dates:
                supported += [x for x in make_rows(rows, COUNTIES[0], year, 'in_person', limit) if x['measure'] == 'daily']
        new_rows += supported
    for year, filename in ((2024, 'mbreq24G.zip'), (2026, 'mbreq26GE.zip')):
        url = 'https://elections.clarkcountynv.gov/VoterRequestsTV/EVMB/' + filename
        try:
            data = acquire(url, 'clark_mail', year, use_cache=year == 2024)
            sources[url] = data['source']
            new_rows += make_rows(data['rows'], COUNTIES[0], year, 'mail', args.through if year == 2026 else f'{year}-11-04')
        except Exception as error:
            errors.append({'url': url, 'error': str(error)})
    # Washoe publishes separate dated cumulative snapshots; use the displayed report date,
    # never pretend a returned-date reconstruction is an archived acceptance snapshot.
    index_url = 'https://www.washoecounty.gov/voters/results/2026data.php'
    try:
        page = fetch(index_url).decode()
        candidates = []
        for block in re.findall(r'<tr\b[^>]*>(.*?)</tr>', page, re.S | re.I):
            date_match = re.search(r'(\d{1,2}/\d{1,2}/2026)', re.sub('<[^>]+>', ' ', block))
            if not date_match:
                continue
            report_date = parse_date(date_match[1])
            if report_date > args.through or report_date < '2026-10-01':
                continue
            for href in re.findall(r'href=["\']([^"\']+)["\']', block):
                if 'Mail-Ballot-Detail' in href or 'In-Person-Turnout' in href:
                    kind = 'washoe_mail' if 'Mail-Ballot-Detail' in href else 'washoe_early'
                    candidates.append((report_date, urllib.parse.urljoin(index_url, href), kind))
        def load_washoe(candidate):
            report_date, url, kind = candidate
            try:
                return candidate, acquire(url, kind, 2026, use_cache=report_date != max(x[0] for x in candidates)), None
            except Exception as error:
                return candidate, None, str(error)
        with ThreadPoolExecutor(max_workers=4) as executor:
            loaded_washoe = list(executor.map(load_washoe, candidates))
        for (report_date, url, kind), data, load_error in loaded_washoe:
            try:
                if load_error:
                    raise ValueError(load_error)
                sources[url] = data['source']
                method = 'mail' if kind == 'washoe_mail' else 'in_person'
                totals = Counter()
                party_totals = defaultdict(Counter)
                daily = []
                for row in data['rows']:
                    if row['date'] <= report_date:
                        totals[row['precinct']] += row['votes']
                        party_totals[row['precinct']].update(row.get('breakdowns', {}).get('party', {}))
                        if row['date'] == report_date:
                            daily += make_rows([row], COUNTIES[1], 2026, method, report_date)[:1]
                for precinct, votes in totals.items():
                    row = {'year': 2026, 'date': report_date, 'county': COUNTIES[1]['id'], 'county_name': COUNTIES[1]['name'], 'precinct': precinct, 'measure': 'cumulative', 'method': method, 'votes': votes}
                    if party_totals[precinct]:
                        row['breakdowns'] = {'party': dict(party_totals[precinct])}
                    new_rows.append(row)
                new_rows += daily
            except Exception as error:
                errors.append({'url': url, 'error': str(error)})
    except Exception as error:
        errors.append({'url': index_url, 'error': str(error)})
    # Combine methods only where both are actually present for the same geography/date.
    grouped = defaultdict(dict)
    for row in new_rows:
        grouped[(row['year'], row['date'], row['county'], row['precinct'], row['measure'])][row['method']] = row
    for (_, _, _, _, _), methods in grouped.items():
        if 'mail' in methods and 'in_person' in methods:
            mail, early_row = methods['mail'], methods['in_person']
            total = {k: v for k, v in mail.items() if k != 'breakdowns'}
            total['method'], total['votes'] = 'total', mail['votes'] + early_row['votes']
            if mail.get('breakdowns') and early_row.get('breakdowns'):
                party = Counter(mail['breakdowns']['party']) + Counter(early_row['breakdowns']['party'])
                total['breakdowns'] = {'party': dict(party)}
            new_rows.append(total)
    replaced_scopes = {(r['year'], r['date'], r['county'], r['method'], r['measure']) for r in new_rows}
    observations = {key: row for key, row in observations.items() if (row['year'], row['date'], row['county'], row['method'], row['measure']) not in replaced_scopes}
    for row in new_rows:
        observations[(row['year'], row['date'], row['county'], row['precinct'], row['method'], row['measure'])] = row
    output = {'schema_version': 1, 'id': 'nv', 'name': 'Nevada', 'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'through': args.through, 'election_dates': {'2024': '2024-11-05', '2026': '2026-11-03'}, 'start_dates': {str(k): v for k, v in STARTS.items()}, 'method_labels': {'mail': 'Mail returned', 'in_person': 'In person', 'total': 'Early + mail returned'}, 'observations': sorted(observations.values(), key=lambda r: (r['year'], r['date'], r['county'], r['precinct'] or '', r['method'], r['measure'])), 'counties': COUNTIES, 'sources': list(sources.values()), 'errors': errors, 'notes': ['Coverage is Clark and Washoe counties where reported, not statewide Nevada. County comparison dates use the same counties and voting methods in both cycles. Washoe 2024 daily history was not located, so Washoe contributes to current observations but not a fabricated year-over-year comparison.', 'Mail means returned ballots, including accepted returns and returns awaiting processing/signature resolution; excludes undeliverable, mailed-only, canceled and surrendered-to-in-person records. The 2024 Clark mail history is reconstructed from actual receipt dates in its mature return file; late corrections may revise those dated events.', 'Clark in-person general-election PARTY is ballot type (NA), not registration. No registration-party breakdown is inferred for those files, and mail registration splits are never assigned to combined Clark turnout.', 'Washoe dated cumulative reports use their published calendar date; daily values use that same date in the event-dated source. Precinct identifiers are retained, but precinct boundary equivalence across cycles has not been established.', 'Only public aggregate counts and source hashes are saved. Downloaded voter identities/addresses remain in memory and are not served or persisted.', 'Clark site-level controls and unaudited precinct rosters can differ: through October 23, 2026, the official site table reports 89,077 in person versus 88,925 in the dated voter rosters. October 18 differs in the opposite direction by one voter. The status/correction scope is unresolved; reported roster counts are retained consistently, and no difference is assigned to precincts.', '2024 county presidential counts are from the Nevada Secretary of State certified-results page, preserved in a UCSB archival PDF; Washoe independently confirmed by its official final summary.']}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUT.with_suffix('.tmp')
    temp.write_text(json.dumps(output, separators=(',', ':')))
    temp.replace(OUT)
    print(json.dumps({'state': 'nv', 'observations': len(output['observations']), 'sources': len(output['sources']), 'errors': errors}))

if __name__ == '__main__':
    main()
