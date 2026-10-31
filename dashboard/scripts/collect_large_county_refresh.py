#!/usr/bin/env python3
"""Recurring large-county native source discovery. Personal rows stay in memory."""
from __future__ import annotations

import argparse
import base64
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import io
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urljoin, urlparse
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_county_native as native
from collect_county_native import download, xlsx_rows

CAMERON_LANDING = 'https://www.cameroncountytx.gov/elections/results/'
DENTON_LANDING = 'https://www.votedenton.gov/early-voting-election-day-rosters/'
FIRST = date(2026, 10, 19)
LAST = date(2026, 10, 30)
HEADER = {'A': 'VUID', 'B': 'NAME', 'C': 'CHECK-IN', 'D': 'PRECINCT'}
DENTON_HEADER = {'A':'Name', 'B':'State ID', 'C':'Address', 'D':'Time', 'E':'Precinct', 'F':'Split', 'G':'Ballot Style'}


def discover_cameron(html, through):
    """Rediscover the dated county-wide IP workbook each run; no frozen IDs."""
    return discover_file(html, through, CAMERON_LANDING,
        r'/elections/wp-content/uploads/2026/\d{2}/01_Cameron_County(\d{1,2}-\d{1,2}-2026)\.xlsx', '%m-%d-%Y')


def discover_denton(html, through):
    if not FIRST <= through <= LAST:
        raise ValueError('Denton cutoff outside reviewed election calendar')
    # Denton replaces its only linked cumulative workbook each day. Its
    # publication date can be later than the requested observation cutoff;
    # the explicit Time column, checked below, determines included vote dates.
    published = min(datetime.now(ZoneInfo('America/Chicago')).date(), LAST)
    return discover_file(html, published, DENTON_LANDING,
        r'/wp-content/uploads/2026/\d{2}/1126_(\d{1,2}-\d{1,2})_Early-Voting-Roster\.xlsx', '%m-%d')


def discover_file(html, through, landing, pattern, date_format):
    candidates = defaultdict(set)
    for href in re.findall(r'href\s*=\s*["\']([^"\']+)', html, re.I):
        url = urljoin(landing, href.replace('&amp;', '&'))
        parsed = urlparse(unquote(url))
        if parsed.scheme != 'https' or parsed.hostname != urlparse(landing).hostname:
            continue
        match = re.fullmatch(pattern, parsed.path, re.I)
        if not match:
            continue
        value = match[1] if '%Y' in date_format else match[1] + '-2026'
        fmt = date_format if '%Y' in date_format else date_format + '-%Y'
        when = datetime.strptime(value, fmt).date()
        if FIRST <= when <= min(through, LAST):
            candidates[when].add(url)
    if not candidates:
        raise ValueError('no dated county-wide in-person workbook within requested cutoff')
    when = max(candidates)
    if len(candidates[when]) != 1:
        raise ValueError('ambiguous county workbook links for latest date')
    return when, next(iter(candidates[when]))


def aggregate_cameron(rows, through, source, sha256, retrieved_at):
    """Validate each dated section independently, with global identity quarantine."""
    if not FIRST <= through <= LAST:
        raise ValueError('Cameron cutoff outside reviewed election calendar')
    rows = iter(rows)
    if next(rows, {}).get('A') != 'Cameron County General Election' or next(rows, {}).get('A') != 'For the November 3, 2026 Election':
        raise ValueError('Cameron county/election title changed')
    counts = defaultdict(Counter)
    identities = {}
    quarantine = set()
    invalid = set()
    ordinary = Counter()
    header_dates = set()
    current = None
    for row in rows:
        row = {k: str(v).strip() for k, v in row.items()}
        if not any(row.values()):
            continue
        value = row.get('A', '')
        if not any(row.get(k) for k in ['B','C','D']):
            try:
                current = datetime.strptime(value, '%A, %B %d, %Y').date()
                if not FIRST <= current <= LAST:
                    raise ValueError('Cameron heading outside election window')
                continue
            except ValueError:
                if value in {'VOTER LIST OF EACH JURISDICTION THAT THIS OFFICE IS CONDUCTING', '* Updated'}:
                    continue
                if current is None:
                    raise ValueError('Cameron undated workbook structure changed')
                invalid.add(current)
                continue
        if row == HEADER:
            if current is None:
                raise ValueError('Cameron header has no explicit dated section')
            header_dates.add(current)
            continue
        if current is None:
            raise ValueError('Cameron voter row has no dated section')
        if current > through:
            continue
        try:
            when = datetime.strptime(row.get('C', ''), '%m/%d/%Y').date()
        except ValueError:
            invalid.add(current)
            continue
        if when != current or current not in header_dates or set(row) - set(HEADER):
            invalid.add(current)
            continue
        ordinary[when] += 1
        raw_precinct = row.get('D', '').upper()
        precinct = str(int(raw_precinct)) if raw_precinct.isdigit() else raw_precinct or 'UNASSIGNED'
        identity = row.get('A', '')
        cell = (when, precinct)
        if not re.fullmatch(r'\d{10}', identity):
            quarantine.add(cell)
            continue
        if identity in identities:
            if identities[identity] != cell:
                quarantine.update((identities[identity], cell))
            continue
        identities[identity] = cell
        counts[when][precinct] += 1
    result = []
    for when in sorted(counts):
        if when in invalid:
            continue
        unavailable = sorted(p for d, p in quarantine if d == when)
        for precinct in unavailable:
            counts[when].pop(precinct, None)
        if not counts[when]:
            continue
        result.append(dict(county='cameron', date=str(when), counts=dict(sorted(counts[when].items())),
            source=source, sha256=sha256, retrieved_at=retrieved_at, cumulative=False,
            complete=False, unavailable_precincts=unavailable,
            note=f'Official Cameron county-wide in-person roster, rediscovered from the current election results landing on each refresh. CHECK-IN dates validated against individually dated workbook sections; native residence PRECINCT preserved. {ordinary[when]} source rows on {when}. Global identity deduplication; blank/conflicting identity cells withheld. Mail excluded by source selection; no separate limited/provisional flag supplied. Omitted cells and invalid or absent dates remain unavailable, never zero. Personal rows processed only in memory.'))
    if not result:
        raise ValueError('no usable Cameron dated native observations')
    return result


def collect_cameron(through, downloader=download):
    cutoff, source = discover_cameron(downloader(CAMERON_LANDING).decode(), through)
    raw = downloader(source)
    return aggregate_cameron(xlsx_rows(raw), cutoff, source, hashlib.sha256(raw).hexdigest(), datetime.now(timezone.utc).isoformat())


def parse_denton(rows, through, source, sha256, published_through=None):
    if not FIRST <= through <= LAST:
        raise ValueError('Denton cutoff outside reviewed election calendar')
    published_through = published_through or through
    if not FIRST <= published_through <= LAST:
        raise ValueError('Denton publication outside reviewed election calendar')
    rows = iter(rows)
    if next(rows, None) != DENTON_HEADER:
        raise ValueError('Denton in-person workbook schema changed')
    files = {}
    for row in rows:
        if not any(row.values()):
            continue
        if set(row) - set(DENTON_HEADER):
            raise ValueError('Denton workbook has unexpected columns')
        # Time is the complete Excel date/time serial, not time-of-day alone.
        # No date is inferred from the filename, fetch timestamp or row order.
        try:
            serial = Decimal(row.get('D', ''))
            if not serial.is_finite():
                raise ValueError('nonfinite timestamp')
            when = date(1899, 12, 30) + timedelta(days=int(serial))
        except (ValueError, InvalidOperation, OverflowError) as error:
            raise ValueError('Denton row has no usable explicit voting date') from error
        if not FIRST <= when <= published_through:
            raise ValueError('Denton row date outside published workbook window')
        if when > through:
            continue
        raw_precinct = row.get('E', '').strip().upper()
        precinct = str(int(raw_precinct)) if raw_precinct.isdigit() else raw_precinct or 'UNASSIGNED'
        identity = row.get('B', '').strip()
        if not re.fullmatch(r'\d{10}', identity):
            identity = ''
        files.setdefault(when, dict(rows=[], source=source, sha256=sha256))['rows'].append((identity, precinct))
    if not files:
        raise ValueError('no usable Denton dated native observations')
    return files


def denton_aliases(files, universe, downloader):
    """Recheck every posted date, including newest, for contradictory targets."""
    frequencies = Counter(identity for file in files.values() for identity, _ in file['rows'] if identity)
    targets = defaultdict(set)
    manifests = []
    failures = []
    def fetch_proof(when):
        source = ('https://goelect.txelections.civixapps.com/api-ivis-system/api/v1/getFileByFormat'
            f'?type=EVR_EARLYVOTING&electionId=53815&electionDate={when:%m/%d/%Y}&county=DENTON&countyId=61&format=csv')
        try:
            response = downloader(source)
            raw = base64.b64decode(json.loads(response)['upload'].rsplit(',', 1)[-1], validate=True)
            reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
            if not {'ID_VOTER','VOTING_METHOD','PRECINCT'} <= set(reader.fieldnames or []):
                raise ValueError('Denton official identity-source schema changed')
            seen = set()
            for row in reader:
                if row['VOTING_METHOD'] not in {'IN-PERSON','MAIL-IN'}:
                    raise ValueError('Denton official identity-source method changed')
                if row['VOTING_METHOD'] == 'IN-PERSON':
                    identity = row['ID_VOTER'].strip()
                    if not identity or identity in seen:
                        raise ValueError('Denton official identity-source ambiguous identity')
                    seen.add(identity)
            unique_rows = [(identity, label) for identity, label in files[when]['rows'] if frequencies[identity] == 1]
            _, proof, digest = native.derive_aliases(unique_rows, response, universe)
            return dict(date=str(when), source=source, sha256=digest, aliases=proof)
        except Exception as error:
            print(json.dumps(dict(county='denton', date=str(when), status='alias-proof-unavailable', error=type(error).__name__)), file=sys.stderr)
            return None
    with ThreadPoolExecutor(max_workers=3) as pool:
        for manifest in pool.map(fetch_proof, sorted(files)):
            if manifest is None:
                failures.append(True)
                continue
            manifests.append(manifest)
            for proof in manifest['aliases']:
                targets[proof['native']].update(proof.get('conflicting_targets', [proof.get('precinct')]))
    # An unavailable proof date might contain the contradiction that invalidates
    # a previously unique alias. Keep the prior successful aggregate via the
    # refresh engine instead of silently certifying aliases from fewer sources.
    if failures:
        raise ValueError('Denton dated identity proof incomplete; retain last successful native observation')
    aliases = {label:next(iter(values)) for label, values in targets.items() if len(values) == 1 and next(iter(values)) in universe}
    return aliases, targets, manifests


def collect_denton(through, downloader=download):
    through = min(through, datetime.now(ZoneInfo('America/Chicago')).date() - timedelta(days=1))
    cutoff, source = discover_denton(downloader(DENTON_LANDING).decode(), through)
    raw = downloader(source)
    raw_hash = hashlib.sha256(raw).hexdigest()
    files = parse_denton(xlsx_rows(raw), through, source, raw_hash, published_through=cutoff)
    reference = json.loads((Path(__file__).resolve().parents[1] / 'data/reference.json').read_text())
    county = next(item for item in reference if item['id'] == 'denton')
    universe = {p for group in county['groups'] for p in group['new']}
    aliases, targets, manifests = denton_aliases(files, universe, downloader)
    manifest = dict(method='denton-all-date-exact-identity-alias-v2', native_source=source, native_sha256=raw_hash,
                    publication_date=str(cutoff), observation_cutoff=str(through), identity_sources=manifests)
    evidence = json.dumps(manifest, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(evidence.encode()).hexdigest()
    for file in files.values():
        file['sha256'] = digest
        file['alias_proof'] = evidence
    output = native.aggregate('denton', files, universe, aliases)
    for daily in output:
        when = date.fromisoformat(daily['date'])
        labels = {label for _, label in files[when]['rows']}
        affected = {target for label in labels if label not in aliases for target in targets.get(label, ()) if target in universe}
        daily['unavailable_precincts'] = sorted(set(daily['unavailable_precincts']) | affected)
        for target in affected:
            daily['counts'].pop(target, None)
        daily['note'] += (' Official Denton Daily In-Person Early Voting Roster rediscovered on each refresh. Explicit Excel Time dates. '
            'Full residence subdivision labels are mapped only using globally unique native identities and same-date official SOS identities; '
            'every available date is rechecked for conflicting or foreign targets. No label truncation. '
            f'Workbook publication {cutoff}; only explicit completed voting dates through {through} are included. '
            f'Native workbook SHA256 {raw_hash}; derived SHA256 binds all dated exact-identity proof hashes. Separate limited/provisional flags unavailable.')
    if not any(p in universe and value > 0 for daily in output for p, value in daily['counts'].items()):
        raise ValueError('Denton native source has no exact-identity-proved native precincts')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--county', choices=['cameron', 'denton'], required=True)
    parser.add_argument('--through', type=date.fromisoformat, required=True)
    args = parser.parse_args()
    print(json.dumps({'cameron':collect_cameron, 'denton':collect_denton}[args.county](args.through), separators=(',', ':')))


if __name__ == '__main__':
    main()
