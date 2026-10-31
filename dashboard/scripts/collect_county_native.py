#!/usr/bin/env python3
"""County in-person rosters to aggregate Daily JSON; personal rows stay in memory.

python dashboard/scripts/collect_county_native.py --county waller --through 2026-10-25
The county roster is a published administrative source, not independent proof
that every check-in has been reported. No missing date is interpreted as zero.
"""
from __future__ import annotations

import argparse
import base64
import collections
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote, unquote, urljoin, urlparse
import xml.etree.ElementTree as ET
import zipfile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
LANDINGS = {
    'waller': 'https://www.co.waller.tx.us/page/2026%20County%20and%20Entity%20Elections',
    'washington': 'https://www.co.washington.tx.us/page/washington.elections.information',
    'sanpatricio': 'https://www.sanpatriciocountytx.gov/page/elections.current',
}
STATE_IDS = {'waller': 237, 'washington': 239, 'sanpatricio': 205}
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


def download(url):
    result = subprocess.run(
        ['uv', 'run', '--with', 'curl-cffi==0.16.3', '--with', 'playwright',
         'python', str(ROOT / 'dashboard/scripts/transport.py')],
        input=json.dumps({'url': quote(url, safe=':/?&=%')}).encode(),
        capture_output=True, timeout=180,
    )
    if result.returncode or not result.stdout:
        raise ValueError('official response unavailable')
    return result.stdout


def pdf_text(raw):
    if not raw.startswith(b'%PDF'):
        raise ValueError('county response is not PDF')
    return subprocess.run(['pdftotext', '-layout', '-', '-'], input=raw,
                          capture_output=True, check=True, timeout=45).stdout.decode()


def parse_waller(text, when):
    """Return (identifier, raw residence precinct) pairs, never print rows."""
    headings = re.findall(r'Election date:\s*(\d+/\d+/\d+)\s*\|\s*Roster dates:\s*(\d+/\d+/\d+)', text)
    if not headings or any(e != '11/3/2026' or datetime.strptime(d, '%m/%d/%Y').date() != when
                           for e, d in headings):
        raise ValueError('Waller election/roster date mismatch')
    if 'Name of Early Voter' not in text or 'Residence Address' not in text:
        raise ValueError('Waller in-person roster headers unavailable')
    rows = []
    for line in text.splitlines():
        match = re.match(r'^\s*(\d{3})\s+(\d{10})\s+.+?\s+(\d{2}/\d{2}/\d{4})\s*$', line)
        if match:
            if datetime.strptime(match[3], '%m/%d/%Y').date() != when:
                raise ValueError('Waller row voting date mismatch')
            rows.append((match[2], match[1]))
        elif re.search(r'\b\d{10}\b', line):
            raise ValueError('unparsed Waller voter line')
        elif (blank := re.match(r'^\s*(\d{3})\s+\D.+\s+(\d{2}/\d{2}/\d{4})\s*$', line)):
            if datetime.strptime(blank[2], '%m/%d/%Y').date() != when:
                raise ValueError('Waller blank-ID row voting date mismatch')
            rows.append(('', blank[1]))
    if not rows:
        raise ValueError('empty Waller roster is not confirmed zero')
    return rows


def parse_sanpatricio(text, when):
    heading = f'{when:%A}, October {when.day}, {when.year}'
    normalized = ' '.join(text.split())
    if heading not in normalized or not all(word in normalized.upper() for word in ['VUID', 'VOTER NAME', 'PRECINCT']):
        raise ValueError('San Patricio date/roster headers unavailable')
    name_columns = {match.start() for line in text.splitlines()
                    if (match := re.search(r'VOTER\s+NAME', line, re.I))}
    rows = []
    for line in text.splitlines():
        match = re.match(r'^\s*(\d{10})\s+.+?\s+(\d{3}(?:-[A-Z0-9]+)?)\s*$', line)
        if match:
            rows.append((match[1], match[2]))
        elif re.match(r'^\s*\d{10}\b', line):
            raise ValueError('unparsed San Patricio voter line')
        elif (blank := re.match(r'^\s+[A-Za-z].+?\s+(\d{3}(?:-[A-Z0-9]+)?)\s*$', line)):
            # A footer such as "Page 101" is not a blank-ID voter. Genuine
            # candidates start in the name column with the VUID column empty.
            if re.fullmatch(r'\s*Page\s+\d+(?:\s+of\s+\d+)?\s*', line, re.I):
                continue
            if any(not line[:col].strip() and line[col:col + 1].isalpha()
                   for col in name_columns):
                rows.append(('', blank[1]))
    if not rows:
        raise ValueError('empty San Patricio roster is not confirmed zero')
    return rows


def xlsx_rows(raw):
    """Stream worksheet XML from an in-memory ZIP; preserve sparse columns."""
    with zipfile.ZipFile(io.BytesIO(raw)) as book:
        shared = []
        if 'xl/sharedStrings.xml' in book.namelist():
            for _, element in ET.iterparse(book.open('xl/sharedStrings.xml'), events=('end',)):
                if element.tag == NS + 'si':
                    shared.append(''.join(element.itertext()))
                    element.clear()
        for _, element in ET.iterparse(book.open('xl/worksheets/sheet1.xml'), events=('end',)):
            if element.tag != NS + 'row':
                continue
            row = {}
            for cell in element.findall(NS + 'c'):
                col = re.sub(r'\d', '', cell.attrib['r'])
                value = cell.find(NS + 'v')
                text = value.text or '' if value is not None else ''
                if cell.get('t') == 's' and text:
                    text = shared[int(text)]
                elif cell.get('t') == 'inlineStr':
                    text = ''.join(cell.find(NS + 'is').itertext())
                row[col] = text.strip()
            if any(row.values()):
                yield row
            element.clear()


def parse_washington(raw, when):
    rows = []
    layout = None
    location = 'EV-EV Washington County Courthouse Annex'
    for row in xlsx_rows(raw):
        if not row.get('B') or not row.get('C'):
            raise ValueError('Washington headerless workbook schema changed')
        if not set(row) - set('ABCDE') and row.get('D') == location:
            current_layout, precinct = 'original', row['C']
        elif (not set(row) - set('ABCDEF') and row.get('E') == location
              and re.fullmatch(r'[PS]\s+\d+(?:\.\d+)?', row.get('D', ''))):
            # The independently dated Oct28 publication adds one descriptive
            # column before precinct. The exact reviewed EV location moves to
            # E; full P/S residence codes are in D. Ignore descriptive fields,
            # never infer a precinct from names, addresses or ballot styles.
            current_layout, precinct = 'expanded', row['D']
        else:
            raise ValueError('Washington source is not the reviewed early-voting location')
        if layout is not None and current_layout != layout:
            raise ValueError('Washington workbook mixes unreviewed column layouts')
        layout = current_layout
        identifier = row.get('A', '')
        if identifier and not re.fullmatch(r'\d{10}', identifier):
            raise ValueError('Washington identifier format changed')
        # P/S prefixes and split suffixes are deliberately retained here.
        rows.append((identifier, precinct))
    if not rows:
        raise ValueError('empty Washington roster is not confirmed zero')
    return rows


def discover(county, page):
    """Only follow daily roster links actually advertised by the official page."""
    output = {}
    ambiguous = set()
    for href, label in re.findall(r'<a\b[^>]*href=[\"\']([^\"\']+)[\"\'][^>]*>(.*?)</a>', page, re.I | re.S):
        url = urljoin(LANDINGS[county], href.replace('&amp;', '&'))
        if urlparse(url).hostname != urlparse(LANDINGS[county]).hostname:
            continue
        plain = unquote(url)
        if county == 'waller':
            match = re.search(r'/October (\d+)\.26 In Person\.pdf$', plain, re.I)
        elif county == 'sanpatricio':
            match = re.search(r'/2026/General Election/Voting Rosters/.*October (\d+).*\.pdf$', plain, re.I)
            if 'Ballots received' in plain:
                continue
        else:
            if '/2026/2026 11 03/' not in plain or not plain.lower().endswith('.xlsx'):
                continue
            match = re.search(r'October\s+(\d+)', re.sub('<[^>]+>', '', label), re.I)
        if not match:
            continue
        day = int(match[1])
        if not 19 <= day <= 30:
            continue
        if county == 'washington':
            # There is no voting date column in these headerless files. Require
            # the official link label and the dated filename to agree.
            filename = urlparse(plain).path.rsplit('/', 1)[-1]
            file_days = set(re.findall(r'(?<!\d)10(\d{2})(?:2026|26)(?!\d)', filename))
            if file_days != {f'{day:02}'}:
                continue
        when = date(2026, 10, day)
        if when in ambiguous:
            continue
        if when in output and output[when] != url:
            # One bad/ambiguous day must not discard other completed dates.
            output.pop(when)
            ambiguous.add(when)
            print(json.dumps(dict(county=county, date=when.isoformat(),
                                  status='ambiguous-source-links')), file=sys.stderr)
            continue
        output[when] = url
    return output


def sos_url(county, when):
    name = 'SAN PATRICIO' if county == 'sanpatricio' else county.upper()
    return ('https://goelect.txelections.civixapps.com/api-ivis-system/api/v1/getFileByFormat'
            f'?type=EVR_EARLYVOTING&electionId=53815&electionDate={when:%m/%d/%Y}'
            f'&county={name}&countyId={STATE_IDS[county]}&format=csv')


def derive_aliases(native_rows, sos_raw, universe):
    """Prove label equivalence by exact identity joins between two official files.

    No string-based split/prefix transformation is used. Every observed native
    label must point to one unique known SOS residence precinct. Ambiguous native
    identities or conflicting official mappings invalidate that alias.
    """
    import csv
    native = collections.defaultdict(set)
    for identifier, precinct in native_rows:
        if identifier:
            native[identifier].add(precinct)
    obj = json.loads(sos_raw)
    raw = base64.b64decode(obj['upload'].split(',')[-1])
    associations = collections.defaultdict(set)
    votes = collections.Counter()
    for row in csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))):
        if row['VOTING_METHOD'] != 'IN-PERSON':
            continue
        labels = native.get(row['ID_VOTER'].strip(), set())
        if len(labels) != 1:
            continue
        label = next(iter(labels))
        precinct = row['PRECINCT'].strip()
        precinct = str(int(precinct)) if precinct.isdigit() else precinct
        associations[label].add(precinct)
        votes[(label, precinct)] += 1
    aliases = {label: next(iter(targets)) for label, targets in associations.items()
               if len(targets) == 1 and next(iter(targets)) in universe}
    # Retain foreign single targets too: a later dated source can disprove an
    # earlier native alias without having two targets within that one file.
    proof = [{'native': label, 'precinct': next(iter(targets)),
              'matched_rows': votes[(label, next(iter(targets)))]}
             for label, targets in sorted(associations.items()) if len(targets) == 1]
    proof += [{'native': label, 'conflicting_targets': sorted(targets)}
              for label, targets in sorted(associations.items()) if len(targets) > 1]
    return aliases, proof, hashlib.sha256(raw).hexdigest()


def aggregate(county, files, universe, aliases=None):
    aliases = aliases or {}
    seen = {}
    quarantine = collections.defaultdict(set)
    diagnostics = collections.defaultdict(collections.Counter)
    normalized = {}
    for when, file in sorted(files.items()):
        current = []
        for identifier, raw_precinct in file['rows']:
            precinct = raw_precinct if raw_precinct in universe else aliases.get(raw_precinct, raw_precinct)
            current.append((identifier, precinct))
            diagnostics[when]['rows'] += 1
            if not identifier:
                quarantine[when].add(precinct)
                diagnostics[when]['blank_ids'] += 1
                continue
            location = (when, precinct)
            if identifier in seen:
                old = seen[identifier]
                if old == location:
                    diagnostics[when]['deduplicated'] += 1
                else:
                    quarantine[old[0]].add(old[1])
                    quarantine[when].add(precinct)
                    diagnostics[when]['conflicting_ids'] += 1
            else:
                seen[identifier] = location
        normalized[when] = current
    output = []
    for when, file in sorted(files.items()):
        counts = collections.Counter()
        ids = set()
        unknown = set()
        for identifier, precinct in normalized[when]:
            if identifier and identifier not in ids and precinct not in quarantine[when]:
                if precinct not in universe:
                    unknown.add(precinct)
                counts[precinct if precinct in universe else 'UNASSIGNED'] += 1
                ids.add(identifier)
        d = diagnostics[when]
        unknown = sorted(unknown)
        note = (f'Official county daily in-person roster; {d["rows"]} source rows, '
                f'{d["deduplicated"]} same-date/same-precinct identity copies removed, '
                f'{d["blank_ids"]} blank-ID rows, {d["conflicting_ids"]} conflicting identities. '
                f'{len(quarantine[when])} affected precinct/date cells withheld. '
                'Raw voter rows and identities were processed only in memory. '
                'Published roster coverage; not independently certified against county check-in totals. '
                'Absent precincts are not filled with zero. Voters with unproven precinct labels '
                'are retained in UNASSIGNED and cannot certify native precinct zeros. '
                f'Unproven source precinct labels: {json.dumps(unknown)}.')
        if file.get('alias_proof'):
            note += ' Precinct aliases verified by exact voter-ID joins to official SOS residence-precinct records: ' + file['alias_proof']
        output.append(dict(county=county, date=when.isoformat(), counts=dict(sorted(counts.items())),
                           source=file['source'], sha256=file['sha256'],
                           retrieved_at=datetime.now(timezone.utc).isoformat(),
                           note=note, cumulative=False, complete=False,
                           unavailable_precincts=sorted(quarantine[when]), unmapped_precincts=unknown))
    return output


def collect(county, through, downloader=download):
    references = json.loads((ROOT / 'dashboard/data/reference.json').read_text())
    reference = next(c for c in references if c['id'] == county)
    universe = {p for group in reference['groups'] for p in group['new']}
    sources = discover(county, downloader(LANDINGS[county]).decode())
    last_completed = datetime.now(ZoneInfo('America/Chicago')).date() - timedelta(days=1)
    sources = {when: url for when, url in sources.items()
               if date(2026, 10, 19) <= when <= min(through, last_completed, date(2026, 10, 30))}
    def fetch_file(item):
        when, url = item
        try:
            raw = downloader(url)
            if county == 'washington':
                rows = parse_washington(raw, when)
            elif county == 'waller':
                rows = parse_waller(pdf_text(raw), when)
            else:
                rows = parse_sanpatricio(pdf_text(raw), when)
            return when, dict(rows=rows, source=quote(url, safe=':/?&=%'), sha256=hashlib.sha256(raw).hexdigest())
        except Exception as error:
            print(json.dumps(dict(county=county, date=when.isoformat(), status='unavailable',
                                  error=type(error).__name__)), file=sys.stderr)
            return when, None
    # A single slow source must not serially delay every other completed day.
    # Bound official-host concurrency; results retain deterministic date order.
    with ThreadPoolExecutor(max_workers=3) as pool:
        files = {when: file for when, file in pool.map(fetch_file, sorted(sources.items())) if file is not None}
    aliases, proof_notes = {}, []
    targets = collections.defaultdict(set)
    unknown_labels = {p for file in files.values() for _, p in file['rows'] if p not in universe}
    # Review same-date official identity joins until observed labels have proof.
    # Unavailable SOS files leave unproven labels outside matched geography.
    proof_days = sorted(files, key=lambda d: (d != date(2026, 10, 21), d))
    if county in ('washington', 'sanpatricio'):
        def fetch_proof(proof_day):
            try:
                source = sos_url(county, proof_day)
                found, proof, sha = derive_aliases(files[proof_day]['rows'], downloader(source), universe)
                return source, proof, sha
            except Exception as error:
                print(json.dumps(dict(county=county, date=proof_day.isoformat(),
                                      status='alias-proof-unavailable', error=type(error).__name__)), file=sys.stderr)
                return None
        # Recheck every advertised completed date on every refresh. Stopping
        # once labels look resolved freezes a crosswalk before new evidence.
        with ThreadPoolExecutor(max_workers=3) as pool:
            proofs = list(pool.map(fetch_proof, proof_days)) if unknown_labels else []
        for result in proofs:
            if result is not None:
                source, proof, sha = result
                for item in proof:
                    targets[item['native']].update(item.get('conflicting_targets', [item.get('precinct')]))
                aliases = {label: next(iter(values)) for label, values in targets.items()
                           if len(values) == 1 and next(iter(values)) in universe}
                proof_notes.append(json.dumps(dict(source=quote(source, safe=':/?&=%'), sha256=sha,
                                                   aliases=proof), separators=(',', ':')))
    for file in files.values():
        file['alias_proof'] = ' '.join(proof_notes)
        # Alias evidence changes the aggregate even when the roster itself is
        # unchanged, so it must also change the derived input identity.
        file['native_sha256'] = file['sha256']
        manifest = dict(native_sha256=file['sha256'], alias_evidence=proof_notes,
                        method='all-completed-date-exact-identity-alias-v2')
        file['sha256'] = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    output = aggregate(county, files, universe, aliases)
    for daily in output:
        when = date.fromisoformat(daily['date'])
        labels = {label for _, label in files[when]['rows']}
        affected = {target for label in labels if label not in aliases
                    for target in targets.get(label, ()) if target in universe}
        daily['unavailable_precincts'] = sorted(set(daily['unavailable_precincts']) | affected)
        for target in affected:
            daily['counts'].pop(target, None)
        daily['note'] += ' Native roster SHA256 ' + files[when]['native_sha256'] + '; derived SHA256 also binds all completed-date alias evidence.'
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--county', choices=sorted(LANDINGS), required=True)
    parser.add_argument('--through', type=date.fromisoformat, required=True)
    args = parser.parse_args()
    if args.through.year != 2026:
        parser.error('native alternatives support the 2026 general election only')
    try:
        rows = collect(args.county, args.through)
        print(json.dumps(rows, separators=(',', ':')))
        return 0
    except Exception as error:
        print(json.dumps(dict(county=args.county, status='unavailable', error=type(error).__name__)), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
