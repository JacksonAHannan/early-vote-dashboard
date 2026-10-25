#!/usr/bin/env python3
"""Refresh Georgia SOS public turnout aggregates without saving voter records.

python3 dashboard/scripts/states/georgia.py --through 2026-10-23
Anonymous read-session credentials stay in memory. Prior output survives failures.
"""
import argparse
import base64
import collections
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import socket
import ssl
import struct
import sys
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / 'sources/multistate/ga/raw'
OUTPUT = ROOT / 'dashboard/data/states/ga.json'
HUB = 'https://d11khjvhu86vzz.cloudfront.net'
APP_PATH = '/DH.ELECTION2024'
CENSUS = 'https://www2.census.gov/geo/docs/reference/codes2020/national_county2020.txt'
RETURNS = ('https://results.sos.ga.gov/results/public/api/elections/Georgia/'
           '2024NovGen/data/ballot-item/01000000-d884-2e72-6367-08dcda4b86b5')
ELECTIONS = {2024: '2024-11-05', 2026: '2026-11-03'}
STARTS = {2024: '2024-10-15', 2026: '2026-10-13'}
METHODS = {'Early In-Person': 'in_person', 'Absentee by mail': 'mail',
           'Electronic Ballot Delivery': 'mail'}
BREAKDOWNS = {'race': 'RACE_DESC', 'sex': 'Gender_Clean', 'age': 'Age Group'}
ACCEPTED = 'SUM(Ballots_Accepted_Counter)+SUM(ExtraBallotCounter)'


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()


class Archive:
    def __init__(self):
        self.sources = []

    def save(self, url, content, description, suffix='json', **details):
        digest = hashlib.sha256(content).hexdigest()
        RAW.mkdir(parents=True, exist_ok=True)
        path = RAW / f'{digest}.{suffix}'
        if not path.exists():
            path.write_bytes(content)
        self.sources.append(dict(url=url, retrieved_at=now(), sha256=digest,
                                 description=description,
                                 path=str(path.relative_to(ROOT)), **details))

    def get(self, url, description, suffix='json'):
        request = urllib.request.Request(url, headers={'User-Agent': 'TurnoutResearch/1.0'})
        with urllib.request.urlopen(request, timeout=60) as response:
            content = response.read()
        self.save(url, content, description, suffix)
        return content


class QlikSocket:
    """Small RFC6455 client for the public read-only JSON-RPC engine endpoint."""
    def __init__(self, url, token):
        parsed = urllib.parse.urlparse(url)
        self.socket = ssl.create_default_context().wrap_socket(
            socket.create_connection((parsed.hostname, 443), timeout=60),
            server_hostname=parsed.hostname)
        key = base64.b64encode(os.urandom(16)).decode()
        target = parsed.path + ('?' + parsed.query if parsed.query else '')
        request = (f'GET {target} HTTP/1.1\r\nHost: {parsed.hostname}\r\n'
                   'Upgrade: websocket\r\nConnection: Upgrade\r\n'
                   f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n'
                   f'Authorization: Bearer {token}\r\nOrigin: {HUB}\r\n\r\n')
        self.socket.sendall(request.encode())
        header = b''
        while b'\r\n\r\n' not in header:
            header += self.exact(1)
            if len(header) > 65536:
                raise ValueError('Oversized Qlik WebSocket handshake')
        lines = header.decode().split('\r\n')
        if not lines[0].startswith('HTTP/1.1 101'):
            raise ValueError('Qlik WebSocket handshake rejected: ' + lines[0])
        headers = {line.split(':', 1)[0].lower(): line.split(':', 1)[1].strip()
                   for line in lines[1:] if ':' in line}
        expected = base64.b64encode(hashlib.sha1(
            (key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
        if headers.get('sec-websocket-accept') != expected:
            raise ValueError('Invalid Qlik WebSocket accept signature')
        self.ident = 0

    def exact(self, size):
        content = bytearray()
        while len(content) < size:
            chunk = self.socket.recv(size - len(content))
            if not chunk:
                raise ConnectionError('Qlik session closed')
            content.extend(chunk)
        return bytes(content)

    def send(self, payload, opcode=1):
        if isinstance(payload, str):
            payload = payload.encode()
        size = len(payload)
        header = bytes([128 | opcode])
        if size < 126:
            header += bytes([128 | size])
        elif size < 65536:
            header += bytes([128 | 126]) + struct.pack('!H', size)
        else:
            header += bytes([128 | 127]) + struct.pack('!Q', size)
        mask = os.urandom(4)
        self.socket.sendall(header + mask + bytes(
            value ^ mask[index % 4] for index, value in enumerate(payload)))

    def receive(self):
        content = bytearray()
        while True:
            first, second = self.exact(2)
            size = second & 127
            if size == 126:
                size = struct.unpack('!H', self.exact(2))[0]
            elif size == 127:
                size = struct.unpack('!Q', self.exact(8))[0]
            if size + len(content) > 64 * 1024 * 1024:
                raise ValueError('Oversized Qlik aggregate response')
            mask = self.exact(4) if second & 128 else b''
            payload = self.exact(size)
            if mask:
                payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
            opcode = first & 15
            if opcode == 9:
                self.send(payload, 10)
                continue
            if opcode == 10:
                continue
            if opcode == 8:
                raise ConnectionError('Qlik closed the aggregate session')
            if opcode not in (0, 1):
                raise ValueError('Unexpected Qlik frame type')
            content.extend(payload)
            if first & 128:
                return json.loads(content)

    def call(self, handle, method, params=None):
        self.ident += 1
        ident = self.ident
        self.send(json.dumps(dict(jsonrpc='2.0', id=ident, handle=handle,
                                  method=method, params=params or [])))
        while True:
            response = self.receive()
            if response.get('id') == ident:
                if 'error' in response:
                    raise ValueError(f"Qlik {method}: {response['error']}")
                return response['result']

    def close(self):
        self.socket.close()


def qlik_date(value):
    return (dt.date.fromisoformat(value) - dt.date(1899, 12, 30)).days


def parse_date(value):
    return None if not value or value == '-' else dt.datetime.strptime(value, '%m/%d/%Y').date().isoformat()


def integer(value):
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or int(value) != value:
        raise ValueError(f'Invalid aggregate ballot count {value!r}')
    return int(value)


def cube(ws, app, dimensions, expression=ACCEPTED):
    definition = {'qInfo': {'qType': 'turnout-research-aggregate'}, 'qHyperCubeDef': {
        'qDimensions': [{'qDef': {'qFieldDefs': [field]}, 'qNullSuppression': False}
                        for field in dimensions],
        'qMeasures': [{'qDef': {'qDef': expression}}],
        'qSuppressZero': True, 'qSuppressMissing': True, 'qInitialDataFetch': []}}
    created = ws.call(app, 'CreateSessionObject', [definition])['qReturn']
    handle = created['qHandle']
    try:
        layout = ws.call(handle, 'GetLayout')['qLayout']['qHyperCube']
        if layout.get('qError'):
            raise ValueError(f"Qlik aggregate calculation failed: {layout['qError']}")
        width, height = layout['qSize']['qcx'], layout['qSize']['qcy']
        if width != len(dimensions) + 1 or height > 500000:
            raise ValueError('Unexpected aggregate cube dimensions')
        pages = []
        page_height = 10000 // width
        for top in range(0, height, page_height):
            request = dict(qLeft=0, qTop=top, qWidth=width, qHeight=min(page_height, height - top))
            pages.extend(ws.call(handle, 'GetHyperCubeData', ['/qHyperCubeDef', [request]])['qDataPages'])
        rows = [row for page in pages for row in page['qMatrix']]
        total = integer(layout['qGrandTotalRow'][0]['qNum'])
        if sum(integer(row[-1]['qNum']) for row in rows) != total:
            raise ValueError('Aggregate rows do not reconcile to official cube total')
        return dict(dimensions=dimensions, expression=expression, layout=layout, pages=pages, total=total)
    finally:
        ws.call(app, 'DestroySessionObject', [created['qGenericId']])


def rows(data):
    for page in data['pages']:
        for row in page['qMatrix']:
            yield [cell.get('qText', '-') for cell in row[:-1]], integer(row[-1]['qNum'])


def census_counties(raw):
    result = {}
    for row in csv.DictReader(io.StringIO(raw.decode()), delimiter='|'):
        if row['STATEFP'] == '13':
            name = row['COUNTYNAME'].removesuffix(' County')
            fips = row['STATEFP'] + row['COUNTYFP']
            result[name.upper()] = dict(id=fips, name=name, fips=fips)
    if len(result) != 159:
        raise ValueError('Expected all 159 Georgia Census counties')
    return result


def county_key(name):
    return re.sub(r'[^A-Z]', '', name.upper().removesuffix(' COUNTY'))


def enrich_returns(counties, data):
    lookup = {county_key(key): value for key, value in counties.items()}
    ballot = data['ballotItemWithBreakdown']
    totals, found = collections.Counter(), set()
    for row in ballot['breakdownResults']:
        county = lookup[county_key(row['locality']['name'][0]['text'])]
        if county['id'] in found:
            raise ValueError('Duplicate official county return')
        found.add(county['id'])
        for option in row['ballotOptions']:
            name = option['name'][0]['text']
            field = 'harris' if 'Harris' in name else 'trump' if 'Trump' in name else None
            if field:
                county[field] = integer(option['voteCount'])
                totals[field] += county[field]
    if len(found) != 159 or totals != {'harris': 2548017, 'trump': 2663117}:
        raise ValueError(f'Certified county returns failed statewide reconciliation: {dict(totals)}')


def category(kind, value):
    if value in ('-', '', 'Unknown', 'UNKNOWN'):
        return 'Unknown'
    if kind == 'age':
        match = re.fullmatch(r'(\d+)-(\d+)', value)
        if match and int(match[1]) >= 35:
            return f'{match[1]}-{int(match[2]) - 1}'
    return value


def normalize(year, county_lookup, base, demographics, through):
    """Accepted-date daily series plus same-data cumulative prefixes.

    Full aggregate cubes suppress actual zeros; those known zeros are expanded
    inside observed date coverage only. Pre-opening mail enters Day1 cumulative.
    """
    by_key, latest = {}, None
    labels = {kind: sorted({category(kind, dims[-1]) for dims, _ in rows(data)})
              for kind, data in demographics.items()}
    def in_window(date, method):
        earliest = STARTS[year] if method == 'in_person' else (
            dt.date.fromisoformat(ELECTIONS[year]) - dt.timedelta(days=60)).isoformat()
        return date is not None and earliest <= date < ELECTIONS[year]
    for dims, count in rows(base):
        name, date_text, style = dims
        method, date = METHODS.get(style), parse_date(date_text)
        if method is None or not in_window(date, method):
            continue
        if year == 2026 and date > through:
            continue
        latest = max(latest or date, date)
        key = (county_lookup[county_key(name)]['id'], date, method)
        by_key.setdefault(key, {'votes': 0, 'breakdowns': {}})['votes'] += count
    if not latest:
        raise ValueError(f'No accepted Georgia ballots for {year}')
    for kind, data in demographics.items():
        check = collections.Counter()
        for dims, count in rows(data):
            name, date_text, style, native_category = dims
            method, date = METHODS.get(style), parse_date(date_text)
            if method is None or not in_window(date, method):
                continue
            if year == 2026 and date > through:
                continue
            key = (county_lookup[county_key(name)]['id'], date, method)
            if key not in by_key:
                raise ValueError('Demographic observation absent from county aggregate')
            bucket = by_key[key]['breakdowns'].setdefault(kind, {})
            label = category(kind, native_category)
            bucket[label] = bucket.get(label, 0) + count
            check[key] += count
        if any(check[key] != value['votes'] for key, value in by_key.items()):
            raise ValueError(f'{year} {kind} counts do not reconcile to county/date/method totals')
    dates, day = [], dt.date.fromisoformat(min(date for _, date, _ in by_key))
    while day.isoformat() <= latest:
        dates.append(day.isoformat())
        day += dt.timedelta(days=1)
    result = []
    for county in sorted(county_lookup.values(), key=lambda item: item['id']):
        cumulative = {method: {'votes': 0, 'breakdowns': {}} for method in ('in_person', 'mail', 'total')}
        for date in dates:
            daily = {method: by_key.get((county['id'], date, method), {'votes': 0, 'breakdowns': {}})
                     for method in ('in_person', 'mail')}
            daily['total'] = {'votes': sum(value['votes'] for value in daily.values()), 'breakdowns': {}}
            for method in ('in_person', 'mail'):
                for kind, groups in daily[method]['breakdowns'].items():
                    target = daily['total']['breakdowns'].setdefault(kind, {})
                    for label, count in groups.items():
                        target[label] = target.get(label, 0) + count
            for method in ('in_person', 'mail', 'total'):
                current, running = daily[method], cumulative[method]
                running['votes'] += current['votes']
                for kind, groups in current['breakdowns'].items():
                    target = running['breakdowns'].setdefault(kind, {})
                    for label, count in groups.items():
                        target[label] = target.get(label, 0) + count
                if date < STARTS[year]:
                    continue
                for measure, value in (('daily', current), ('cumulative', running)):
                    for kind, categories in labels.items():
                        groups = value['breakdowns'].setdefault(kind, {})
                        for label in categories:
                            groups.setdefault(label, 0)
                    result.append(dict(year=year, date=date, county=county['id'], county_name=county['name'],
                                       precinct=None, measure=measure, method=method, votes=value['votes'],
                                       breakdowns=json.loads(json.dumps(value['breakdowns']))))
    return result


def collect(through, skip_demographics=False):
    archive = Archive()
    config = archive.get(HUB + '/shared-config.js', 'SOS public dashboard host configuration', 'js').decode()
    variables = archive.get(HUB + APP_PATH + '/js/vars.js', 'SOS public unofficial turnout app configuration', 'js').decode()
    tenant = re.search(r'var tenant\s*=\s*"([^"]+)"', config)[1]
    app_id = re.search(r'var appId\s*=\s*"([^"]+)"', variables)[1]
    with urllib.request.urlopen(HUB + '/qlik-oauth-create-user', timeout=60) as response:
        token = json.load(response)['access_token']
    ws = QlikSocket(tenant.replace('https://', 'wss://') + '/app/' + app_id, token)
    observations = []
    try:
        app = ws.call(-1, 'OpenDoc', [app_id])['qReturn']['qHandle']
        layout = ws.call(app, 'GetAppLayout')
        archive.save(tenant + '/app/' + app_id, encode(layout), 'Official unofficial-turnout app reload metadata')
        county_data = census_counties(archive.get(CENSUS, 'Census official county FIPS names', 'txt'))
        enrich_returns(county_data, json.loads(archive.get(RETURNS, 'Georgia certified 2024 presidential county returns')))
        lookup = {county_key(key): value for key, value in county_data.items()}
        date_field = ws.call(app, 'GetField', ['Election Date'])['qReturn']['qHandle']
        for year in (2024, 2026):
            ws.call(app, 'ClearAll')
            selected = ws.call(date_field, 'SelectValues', [[{
                'qIsNumeric': True, 'qNumber': qlik_date(ELECTIONS[year])}], False, False])
            if not selected.get('qReturn'):
                raise ValueError(f'Official app does not contain the {year} general election')
            dimensions = ['County', 'Ballot Accepted Date', 'Ballot Style']
            base = cube(ws, app, dimensions)
            archive.save(tenant + '/app/' + app_id, encode(base),
                         f'{year} accepted ballots by county, acceptance date and method',
                         election_date=ELECTIONS[year], dimensions=dimensions, expression=ACCEPTED)
            demographics = {}
            if not skip_demographics:
                for kind, field in BREAKDOWNS.items():
                    data = cube(ws, app, dimensions + [field])
                    archive.save(tenant + '/app/' + app_id, encode(data),
                                 f'{year} accepted ballots by county, date, method and {kind}',
                                 election_date=ELECTIONS[year], dimensions=dimensions + [field], expression=ACCEPTED)
                    demographics[kind] = data
            observations.extend(normalize(year, lookup, base, demographics, through))
            print(f"Georgia {year}: {base['total']:,} accepted ballots in source; normalized {len(observations):,} rows", flush=True)
        final_layout = ws.call(app, 'GetAppLayout')
        if layout['qLayout']['qLastReloadTime'] != final_layout['qLayout']['qLastReloadTime']:
            raise ValueError('Official app reloaded during extraction; retry for a consistent snapshot')
    finally:
        ws.close()
    return dict(schema_version=1, id='ga', name='Georgia', generated_at=now(), through=through,
                election_dates={str(key): value for key, value in ELECTIONS.items()},
                start_dates={str(key): value for key, value in STARTS.items()},
                source_updated_at=layout['qLayout']['qLastReloadTime'], observations=observations,
                counties=sorted(county_data.values(), key=lambda item: item['id']), sources=archive.sources,
                errors=[], notes=[
                    'Official unofficial accepted-ballot aggregates by acceptance date; later county uploads may revise prior dates.',
                    'Mail combines Absentee by mail and Electronic Ballot Delivery; rejected/requested/outstanding ballots and Election Day are excluded.',
                    'Day1 cumulative includes accepted mail from before in-person voting opened. Both cycles align by days since in-person opening.',
                    '2024 retains future baseline dates; 2026 ends at the requested date or latest source acceptance date, whichever is earlier.',
                    'Race, age and sex are actual voter aggregate categories from the SOS hub, not Census estimates. Other/Unknown remains unknown for non-white classification.',
                    'Georgia does not register voters by party. General-election ballot style is not party registration or 2026 primary participation.',
                    'The public aggregate app has no precinct dimension; county geography is the most granular supported turnout comparison.',
                    'Malformed/out-of-cycle acceptance dates are excluded from dated curves, never reassigned. Mail date window is 60 days before Election Day; in-person begins at the official opening.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--through', required=True)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--skip-demographics', action='store_true')
    args = parser.parse_args()
    dt.date.fromisoformat(args.through)
    if not '2026-10-13' <= args.through < '2026-11-03':
        parser.error('--through must be within the 2026 general-election advance-voting period')
    try:
        data = collect(args.through, args.skip_demographics)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + '.tmp')
        temporary.write_bytes(encode(data))
        os.replace(temporary, args.output)
        print(f"Wrote {args.output} ({len(data['observations']):,} observations)")
    except Exception as error:
        print(f'Georgia refresh failed; prior file retained: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
