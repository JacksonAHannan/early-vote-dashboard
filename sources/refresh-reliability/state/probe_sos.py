#!/usr/bin/env python3
"""Read-only SOS roster availability probe; write aggregates/hashes only, never identities."""
import argparse
import base64
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import date, datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
from urllib.parse import urlencode

HOST = 'https://goelect.txelections.civixapps.com/api-ivis-system/api/v1/getFileByFormat'


def inspect_csv(payload):
    reader = csv.DictReader(io.StringIO(payload.decode('utf-8-sig')))
    required = {'ID_VOTER', 'VOTING_METHOD', 'PRECINCT'}
    if not required.issubset(reader.fieldnames or []):
        return {'availability': 'invalid_csv_schema', 'fields': reader.fieldnames}
    methods = Counter()
    seen = set()
    duplicates = blank = 0
    precincts = set()
    for row in reader:
        method = row['VOTING_METHOD'].strip()
        methods[method] += 1
        identity = row['ID_VOTER'].strip()
        blank += not bool(identity)
        if method == 'IN-PERSON':
            duplicates += identity in seen
            seen.add(identity)
            precincts.add(row['PRECINCT'].strip())
    availability = ('invalid_blank_id' if blank else 'invalid_repeated_id' if duplicates
                    else 'invalid_method' if set(methods) - {'IN-PERSON', 'MAIL-IN'}
                    else 'in_person_available' if methods['IN-PERSON'] else 'mail_only' if methods else 'empty_csv')
    return {'availability': availability, 'rows': sum(methods.values()), 'methods': dict(methods),
            'blank_ids': blank, 'repeated_in_person_ids': duplicates, 'in_person_precincts': len(precincts)}


def probe(reference, when):
    from curl_cffi import requests
    url = HOST + '?' + urlencode({'type': 'EVR_EARLYVOTING', 'electionId': '53815',
                                  'electionDate': when.strftime('%m/%d/%Y'),
                                  'county': reference['name'].upper(), 'countyId': reference['state_id'], 'format': 'csv'})
    result = {'county': reference['id'], 'date': when.isoformat(), 'source': url,
              'checked_at': datetime.now(timezone.utc).isoformat()}
    try:
        response = requests.get(url, impersonate='chrome', timeout=60)
        result.update(status=response.status_code, bytes=len(response.content),
                      response_sha256=hashlib.sha256(response.content).hexdigest(),
                      headers={k: v for k, v in response.headers.items() if k.lower() in
                               ('date', 'age', 'cache-control', 'etag', 'last-modified', 'x-cache', 'content-type')})
        response.raise_for_status()
        if not response.content:
            result['availability'] = 'empty_response'
            return result
        document = response.json()
        encoded = document.get('upload')
        if not isinstance(encoded, str):
            result['availability'] = 'missing_upload'
            return result
        payload = base64.b64decode(encoded.rsplit(',', 1)[-1], validate=True)
        result['csv_sha256'] = hashlib.sha256(payload).hexdigest()
        result.update(inspect_csv(payload))
    except Exception as error:
        # Avoid stringifying exceptions: third-party parsers may quote response rows.
        result.update(availability='probe_error', error_type=type(error).__name__)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--date', type=date.fromisoformat, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--counties', nargs='*')
    args = parser.parse_args()
    if args.reference.resolve() == args.output.resolve():
        parser.error('output must not replace references')
    references = json.loads(args.reference.read_text())
    if args.counties:
        references = [r for r in references if r['id'] in args.counties]
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for result in pool.map(lambda r: probe(r, args.date), references):
            results.append(result)
            print(result['county'], result['availability'], file=sys.stderr, flush=True)
    document = {'date': args.date.isoformat(), 'checked_at': datetime.now(timezone.utc).isoformat(),
                'summary': dict(Counter(r['availability'] for r in results)), 'counties': results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + '\n')
    print(json.dumps(document['summary']))


if __name__ == '__main__':
    main()
