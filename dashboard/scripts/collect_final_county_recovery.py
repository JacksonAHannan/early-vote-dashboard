#!/usr/bin/env python3
"""Fill SOS-missing Dimmit dates from exact dated county VRH batches.

Native records and all twelve dated SOS identity files stay in memory. Existing
positive SOS dates are never replaced; anonymous source proofs bind all inputs.
"""
from __future__ import annotations

import argparse
import base64
import collections
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import html
import io
import json
from pathlib import Path
import re
import sys
from urllib.parse import quote, urlencode, urljoin, urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'dashboard/scripts'))
import collect_county_native as native
from collect_panola import prove_aliases
from collect_tarrant_anchor import download as official_download

LANDING = 'https://dimmitcounty.org/government/departments/elections/index.php'
START = date(2026, 10, 19)
END = date(2026, 10, 30)
METHOD = 'dimmit-fixed-vrh-all-date-identity-v1'


def download(url):
    # Existing official transport verifies HTTP200 and preserves an empty body
    # as explicit source absence, distinct from a transport/schema failure.
    return official_download(url)[0]


def normalize(label):
    label = label.strip().lstrip('\ufeff').upper()
    return label.lstrip('0') or ('0' if label else 'UNASSIGNED')


def discover(page, through):
    if '2026-11-03' not in page:
        raise ValueError('Dimmit current general-election section missing')
    base = re.search(r'<base\b[^>]*href=["\x27]([^"\x27]+)["\x27]', page, re.I)
    base = urljoin(LANDING, html.unescape(base[1])) if base else LANDING
    links = {}
    for href, label in re.findall(r'<a\b[^>]*href=["\x27]([^"\x27]+)["\x27][^>]*>(.*?)</a>', page, re.I | re.S):
        label = ' '.join(html.unescape(re.sub('<[^>]+>', ' ', label)).split())
        match = re.fullmatch(r'EV Oct (\d{1,2}), 2026', label)
        if not match:
            continue
        when = date(2026, 10, int(match[1]))
        if not START <= when <= min(through, END):
            continue
        url = urljoin(base, html.unescape(href))
        parsed = urlparse(url)
        if (parsed.scheme != 'https' or parsed.hostname not in {'dimmitcounty.org', 'www.dimmitcounty.org'}
                or not parsed.path.lower().endswith('.txt')):
            raise ValueError('Dimmit native report changed host or format')
        if when in links:
            raise ValueError('Dimmit native report date ambiguous')
        links[when] = quote(url, safe=':/?&=%')
    if min(through, END) not in links:
        raise ValueError('Dimmit requested final native daily report is not advertised')
    return links


def parse_dimmit(raw, when):
    """Reviewed unwrapped 1090-column VRH layout; no names or addresses used."""
    lines = raw.decode('utf-8-sig').splitlines()
    if len(lines) < 3 or any(len(line) != 1090 for line in lines):
        raise ValueError('Dimmit fixed-width VRH record layout changed')
    header = re.fullmatch(r'HDIMMIT\s+064VRH\s+(\d{14}).*', lines[0])
    trailer = re.fullmatch(r'TDIMMIT\s+064(\d+)\s*', lines[-1])
    if not header or not trailer:
        raise ValueError('Dimmit native header/trailer scope changed')
    exported = datetime.strptime(header[1], '%Y%m%d%H%M%S').date()
    if not when <= exported <= datetime.now(ZoneInfo('America/Chicago')).date():
        raise ValueError('Dimmit native export predates the voting date or is future')
    rows = []
    for line in lines[1:-1]:
        if (line[:19] != 'DDIMMIT         064' or line[29:37] != ' ' * 8
                or line[37:42] != '53815'):
            raise ValueError('Dimmit native detail county/election schema changed')
        if line[677:686] != 'EV    EV ' or line[686:694] != when.strftime('%Y%m%d'):
            raise ValueError('Dimmit native detail method/date changed')
        if line[1003:1064] != '2' + ' ' * 60:
            raise ValueError('Dimmit native residence field marker changed')
        label = line[1064:].strip()
        if not re.fullmatch(r'[PS] \d+(?:\.\d+)?', label):
            raise ValueError('Dimmit native residence precinct missing or malformed')
        identifier = line[19:29].strip()
        if identifier and (len(identifier) != 10 or not identifier.isascii() or not identifier.isdigit()):
            raise ValueError('Dimmit malformed nonblank native VUID')
        rows.append((identifier, label.replace(' ', '')))
    if not rows or len(rows) != int(trailer[1]):
        raise ValueError('Dimmit native detail/trailer conservation failed')
    return rows, int(trailer[1])


def state_records(response):
    if not response.strip():
        return [], hashlib.sha256(response).hexdigest(), {}
    obj = json.loads(response)
    if not isinstance(obj, dict):
        raise ValueError('Dimmit SOS response envelope changed')
    if obj.get('error') or obj.get('errors') or obj.get('success') is False:
        raise ValueError('Dimmit SOS response reports an error')
    upload = obj.get('upload')
    if upload is None:
        return [], hashlib.sha256(response).hexdigest(), {}
    if not isinstance(upload, str):
        raise ValueError('Dimmit SOS upload envelope changed')
    raw = base64.b64decode(upload.rsplit(',', 1)[-1], validate=True)
    if not raw:
        return [], hashlib.sha256(raw).hexdigest(), {}
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    if reader.fieldnames:
        reader.fieldnames = [field.strip().lstrip('\ufeff') for field in reader.fieldnames]
    required = {'ID_VOTER', 'VOTING_METHOD', 'PRECINCT'}
    if not required <= set(reader.fieldnames or []) or any(reader.fieldnames.count(k) != 1 for k in required):
        raise ValueError('Dimmit SOS identity-source schema changed')
    rows = []
    methods = collections.Counter()
    seen = set()
    for row in reader:
        if None in row or any(row.get(field) is None for field in required):
            raise ValueError('Dimmit SOS row width changed')
        method = row['VOTING_METHOD'].strip()
        if not row['ID_VOTER'].strip():
            raise ValueError('Dimmit SOS blank voter identifier')
        if method not in {'IN-PERSON', 'MAIL-IN'}:
            raise ValueError('Dimmit SOS voting method changed')
        methods[method] += 1
        if method == 'IN-PERSON':
            identity = row['ID_VOTER'].strip()
            if len(identity) != 10 or not identity.isascii() or not identity.isdigit() or identity in seen:
                raise ValueError('Dimmit SOS invalid or duplicate in-person identity')
            seen.add(identity)
            rows.append((identity, normalize(row['PRECINCT'])))
    return rows, hashlib.sha256(raw).hexdigest(), dict(methods)


def unique_across_dates(series, owner):
    seen = set()
    for rows in series.values():
        for identity, _ in rows:
            if identity:
                if identity in seen:
                    raise ValueError(f'Dimmit repeated {owner} identity within/across dates')
                seen.add(identity)


def sos_url(when):
    return ('https://goelect.txelections.civixapps.com/api-ivis-system/api/v1/getFileByFormat?' +
            urlencode([('type', 'EVR_EARLYVOTING'), ('electionId', '53815'),
                       ('electionDate', f'{when:%m/%d/%Y}'), ('county', 'DIMMIT'),
                       ('countyId', '64'), ('format', 'csv')]))


def stage(files, state, universe, manifest):
    unique_across_dates({day: file['rows'] for day, file in files.items()}, 'native')
    unique_across_dates(state, 'SOS')
    # Even an ID reported on a different native and SOS date invalidates the
    # mixed-source proof. Never silently place the same person in two dates.
    native_dates = {identity: day for day, file in files.items() for identity, _ in file['rows'] if identity}
    for when, rows in state.items():
        if any(identity in native_dates and native_dates[identity] != when for identity, _ in rows):
            raise ValueError('Dimmit cross-source identity has conflicting vote dates')
    aliases, proof, targets = prove_aliases(files, state, universe)
    manifest = dict(manifest, method=METHOD, aliases=proof)
    evidence = json.dumps(manifest, sort_keys=True, separators=(',', ':'))
    for file in files.values():
        file['native_sha256'] = file['sha256']
        file['alias_proof'] = evidence
        file['sha256'] = hashlib.sha256(json.dumps(dict(native_sha256=file['native_sha256'], manifest=manifest), sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    output = native.aggregate('dimmit', files, universe, aliases)
    fallback = []
    for daily in output:
        when = date.fromisoformat(daily['date'])
        labels = {label for _, label in files[when]['rows']}
        affected = {target for label in labels if label not in aliases
                    for target in targets.get(label, ()) if target in universe}
        daily['unavailable_precincts'] = sorted(set(daily['unavailable_precincts']) | affected)
        for target in affected:
            daily['counts'].pop(target, None)
        # These labels are optional metadata in Daily. Rust ignores them; all
        # unresolved positive rows are also preserved in UNASSIGNED.
        daily['note'] += (f' Fixed VRH county064, election53815, EV/EV, exact dated detail records and explicit trailer {files[when]["trailer"]}. '
                          f'Native source SHA256 {files[when]["native_sha256"]}. All native and SOS identities checked within and across all requested dates, including cross-source date consistency. '
                          'Only SOS-missing dates are admitted; all existing positive SOS observations remain unchanged. No positive county aggregate or omitted row is allocated to precincts.')
        if not state.get(when) and any(p in universe for p in daily['counts']):
            fallback.append(daily)
    return fallback, manifest


def collect(through, downloader=download):
    if not START <= through <= END or through >= datetime.now(ZoneInfo('America/Chicago')).date():
        raise ValueError('Dimmit request is not a completed early-voting date')
    references = json.loads((ROOT / 'dashboard/data/reference.json').read_text())
    reference = next(r for r in references if r['id'] == 'dimmit')
    universe = {p for group in reference['groups'] for p in group['new']}
    page = downloader(LANDING)
    links = discover(page.decode(), through)
    files, native_failures = {}, []
    def get_native(item):
        when, url = item
        raw = None
        try:
            raw = downloader(url)
            rows, trailer = parse_dimmit(raw, when)
            return when, dict(rows=rows, source=url, sha256=hashlib.sha256(raw).hexdigest(), trailer=trailer), None
        except Exception as error:
            message = str(error) if isinstance(error, ValueError) and str(error).startswith('Dimmit') else type(error).__name__
            return when, None, dict(date=when.isoformat(), source=url,
                                   sha256=hashlib.sha256(raw).hexdigest() if raw is not None else None,
                                   error=message)
    with ThreadPoolExecutor(max_workers=3) as pool:
        for when, file, failure in pool.map(get_native, sorted(links.items())):
            if file is not None:
                files[when] = file
            else:
                native_failures.append(failure)
    state, sources = {}, []
    def get_state(when):
        url = sos_url(when)
        response = downloader(url)
        rows, digest, methods = state_records(response)
        status = 'positive_in_person' if rows else 'no_in_person_rows'
        if not response.strip():
            status = 'empty_http_200_body'
        elif not json.loads(response).get('upload'):
            status = 'missing_upload_http_200'
        elif not rows and methods.get('MAIL-IN'):
            status = 'mail_only_csv'
        return when, rows, dict(date=when.isoformat(), source=quote(url, safe=':/?&=%'), sha256=digest,
                               transport_sha256=hashlib.sha256(response).hexdigest(), methods=methods,
                               availability=status, zero_certified=False,
                               counts=dict(sorted(collections.Counter(p for _, p in rows).items())))
    requested = [START + timedelta(days=i) for i in range((through - START).days + 1)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        for when, rows, source in pool.map(get_state, requested):
            state[when] = rows
            sources.append(source)
    manifest = dict(landing_source=LANDING, landing_sha256=hashlib.sha256(page).hexdigest(),
                    retrieved_at=datetime.now(timezone.utc).isoformat(), through=through.isoformat(),
                    state_sources=sources, rejected_native_sources=native_failures,
                    unadvertised_native_dates=[str(day) for day in requested if day not in links],
                    native_sources=[dict(date=when.isoformat(), source=file['source'], sha256=file['sha256'], trailer_total=file['trailer'])
                                    for when, file in sorted(files.items())])
    # These are the exact SOS editions used by the identity proof, returned
    # directly so a second Rust download cannot race a publisher revision.
    unique_across_dates(state, 'SOS')
    sos_reports = [dict(county='dimmit', date=source['date'], counts=source['counts'],
                        source=source['source'], sha256=source['sha256'],
                        retrieved_at=manifest['retrieved_at'], complete=False,
                        cumulative=False, unavailable_precincts=[],
                        note='Daily state IN-PERSON roster; mail excluded. Separate limited/provisional flags are not supplied. Date semantics were independently checked during the October 23 source audit. This exact dated CSV edition also participates in the in-memory cross-date native fallback identity proof.')
                   for source in sources if source['counts']]
    try:
        fallback, proof = stage(files, state, universe, manifest)
    except ValueError as error:
        # Reject the native proof without revoking independently valid SOS
        # positives. No native observations escape a failed identity proof.
        fallback = []
        proof = dict(manifest, method=METHOD, native_recovery_error=str(error))
    proof['fallback_dates'] = [report['date'] for report in fallback]
    return sorted(sos_reports + fallback, key=lambda report: report['date']), proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--county', choices=['dimmit'], default='dimmit')
    parser.add_argument('--through', required=True, type=date.fromisoformat)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--proof-output', type=Path)
    args = parser.parse_args()
    try:
        reports, proof = collect(args.through)
    except Exception as error:
        message = str(error) if isinstance(error, ValueError) and str(error).startswith('Dimmit') else type(error).__name__
        print(json.dumps(dict(county='dimmit', status='unavailable', error=message)), file=sys.stderr)
        return 1
    if args.proof_output:
        args.proof_output.parent.mkdir(parents=True, exist_ok=True)
        args.proof_output.write_text(json.dumps(proof, indent=2) + '\n')
    encoded = json.dumps(reports, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    else:
        print(encoded, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
