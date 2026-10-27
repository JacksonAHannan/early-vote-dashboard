#!/usr/bin/env python3
"""Read-only, offline Texas county precinct methodology and source audit.

Arithmetic belongs to dashboard/scripts/audit_precinct_coverage.py. This command
adds the full 254-county catalog, source diagnostics and bounded review evidence.
It never downloads, changes source qualification, allocates votes or fills zeros.
"""
import argparse
from collections import Counter
from datetime import date, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
OWNER = ROOT / 'dashboard/scripts/audit_precinct_coverage.py'
spec = importlib.util.spec_from_file_location('precinct_coverage_owner', OWNER)
coverage_owner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coverage_owner)


def read(path):
    def no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate JSON object key: {key}')
            result[key] = value
        return result
    return json.loads(path.read_text(), object_pairs_hook=no_duplicates)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unique(rows, key, label):
    result = {}
    for row in rows:
        identity = row[key]
        if not isinstance(identity, str) or not identity or identity in result:
            raise ValueError(f'Duplicate/invalid {label} identity')
        result[identity] = row
    return result


def load_reviews(paths, catalog):
    output = {}
    for path in paths or []:
        document = read(path)
        rows = document['counties']
        for key in ['county_count', 'assignment_count', 'assigned_counties', 'reviewed_counties']:
            if key in document and document[key] != len(rows):
                raise ValueError(f'Review declared county count differs: {path}')
        for cid, row in unique(rows, 'county', 'review county').items():
            if cid not in catalog or cid in output:
                raise ValueError(f'Unknown/duplicate reviewed county: {cid}')
            output[cid] = {
                'path': str(path), 'sha256': sha(path),
                'baseline_generated_at': row.get('baseline_generated_at', document.get('baseline_generated_at', document.get('generated_at'))),
                'disposition': row.get('disposition'),
                'diagnosis': row.get('diagnosis'),
                'next_action': row.get('next_action'),
                'fresh_evidence': row.get('fresh_evidence'),
                'fresh_findings': row.get('fresh_findings'),
                'retained_evidence_only': row.get('retained_evidence_only'),
            }
    if paths and set(output) != set(catalog):
        raise ValueError('Review county coverage differs from complete catalog')
    return output


def source_diagnostic(source, universe, controls, days, origin):
    when = date.fromisoformat(source['date'])
    start = coverage_owner.START.get(when.year)
    in_window = bool(start and start <= when < start + timedelta(days=days))
    counts = source['counts']
    if any(not isinstance(p, str) or not isinstance(n, int) or isinstance(n, bool) or n < 0
           for p, n in counts.items()):
        raise ValueError('Malformed anonymous precinct count')
    unknown = ({p: n for p, n in counts.items() if p not in universe and n > 0}
               if universe is not None else None)
    quarantined = source.get('unavailable_precincts', [])
    measure = 'cumulative' if source.get('cumulative', False) else 'daily'
    checks = []
    for control in controls:
        if control.get('date') != source['date'] or control.get('scope') != 'in_person':
            continue
        target = control.get(measure)
        if target is None:
            continue
        checks.append({
            **control, 'measure': measure, 'source_total': sum(counts.values()),
            'difference': sum(counts.values()) - target,
            'exact_completed_match': bool(control.get('completed') and sum(counts.values()) == target),
        })
    valid_hash = bool(re.fullmatch(r'[0-9a-f]{64}', source['sha256']))
    certified = bool(valid_hash and source['source'].startswith('https://') and in_window and universe is not None and source.get('complete')
                     and not quarantined and not unknown and checks
                     and all(c['exact_completed_match'] for c in checks))
    return {
        'date': source['date'], 'measure': measure, 'method': 'in_person',
        'within_comparison_window': in_window, 'origin': origin,
        'total_votes': sum(counts.values()), 'observed_labels': len(counts),
        'unknown_positive_labels': unknown,
        'explicit_zero_labels': sorted(p for p, n in counts.items() if n == 0),
        'missing_native_labels': sorted(universe - counts.keys()) if universe is not None else None,
        'quarantined_precincts': sorted(quarantined),
        'qualified_complete_flag': bool(source.get('complete')),
        'omitted_zero_certified': certified,
        'allow_daily_difference': source.get('allow_daily_difference'),
        'zero_evidence': source.get('zero_evidence', []),
        'source': source['source'], 'sha256': source['sha256'],
        'valid_sha256': valid_hash,
        'retrieved_at': source.get('retrieved_at'), 'note': source.get('note'),
        'controls': checks,
    }


def classification(reference, snapshot_county):
    if reference is None:
        return {'native_universe_known': False, 'missing_native_2024_ids': None,
                'tied_native_2024_ids': None, 'mixed_margin_native_2026_ids': None}
    ids = {p for group in reference['groups'] for p in group['old']}
    presidential = reference.get('presidential', {})
    missing = sorted(ids - presidential.keys())
    tied = sorted(p for p in ids & presidential.keys()
                  if presidential[p]['harris'] == presidential[p]['trump'])
    mixed = sorted({p for group in (snapshot_county or {}).get('reference_groups', [])
                    if group.get('reason') == 'Mixed margin bands' for p in group['new']})
    return {'native_universe_known': True, 'missing_native_2024_ids': missing,
            'tied_native_2024_ids': tied, 'mixed_margin_native_2026_ids': mixed,
            'note': 'Missing native returns, explicitly tied returns and mixed historical margin groups are distinct; none is an inferred turnout zero.'}


def view_coverage(documents, cid, universe):
    result = {}
    for name, (document, path, denominator) in documents.items():
        county = document.get('counties', {}).get(cid, {})
        records = county.get('precincts', {})
        wanted = universe if universe is not None else set(records)
        present = wanted & records.keys()
        values = [records[p].get('counts', {}).get(denominator) for p in present]
        valid = [n for n in values if isinstance(n, (int, float)) and not isinstance(n, bool) and n >= 0]
        result[name] = {
            'file_present': path.exists(), 'path': str(path),
            'native_universe_known': universe is not None,
            'expected_precincts': len(universe) if universe is not None else None,
            'records_present': len(present),
            'missing_records': len(wanted - records.keys()) if universe is not None else None,
            'positive_denominator': sum(n > 0 for n in valid),
            'zero_denominator': sum(n == 0 for n in valid),
            'missing_or_invalid_denominator': len(values) - len(valid),
            'denominator': denominator,
            'published_coverage': county.get('coverage'),
        }
    return result


def build(root, snapshot, reviews=None, staged=None):
    root = Path(root)
    data = root / 'dashboard/data'
    catalog = read(data / 'county-reference.json')['counties']
    if not isinstance(catalog, dict) or len(catalog) != 254:
        raise ValueError('Texas county catalog must contain exactly 254 counties')
    if any(not cid or not row.get('name') or not re.fullmatch(r'48\d{3}', row.get('fips', ''))
           for cid, row in catalog.items()) or len({r['fips'] for r in catalog.values()}) != 254:
        raise ValueError('Invalid/duplicate county catalog identity or FIPS')
    counties = unique(snapshot['counties'], 'id', 'snapshot county')
    if not set(counties) <= catalog.keys():
        raise ValueError('Snapshot contains unknown counties')
    days = snapshot['days']
    if not isinstance(days, int) or not 1 <= days <= 12:
        raise ValueError('Unsupported comparison day count')
    if snapshot.get('through') and date.fromisoformat(snapshot['through']) != coverage_owner.START[2026] + timedelta(days=days - 1):
        raise ValueError('Snapshot cutoff does not match comparison calendar')
    references = unique(read(data / 'reference.json'), 'id', 'reference county')
    if not set(references) <= catalog.keys():
        raise ValueError('Reference contains unknown counties')
    staged_refs = {}
    for path in staged or []:
        for cid, row in unique(read(path), 'id', 'staged reference county').items():
            if cid not in catalog or cid in staged_refs:
                raise ValueError('Unknown/duplicate staged county reference')
            staged_refs[cid] = row
    review_map = load_reviews(reviews, catalog)
    documents = {}
    for name, path, denominator in [
        ('demographics', data / 'demographics.json', 'vap'),
        ('primary', root / 'dashboard/primary/2026.json' if (root / 'dashboard/primary/2026.json').exists() else data / 'primary.json', 'primary_total'),
        ('place', root / 'dashboard/places/texas.json', 'vap'),
    ]:
        documents[name] = (read(path) if path.exists() else {}, path, denominator)
    controls_path = data / 'completeness.json'
    controls = read(controls_path)['controls'] if controls_path.exists() else []
    # Preserve the established independent reconstruction and its published checks.
    arithmetic = coverage_owner.audit(snapshot, days=days, verify_published=True)
    by_coverage = {}
    for row in arithmetic['counties']:
        by_coverage.setdefault(row['county'], []).append(row)
    unavailable = Counter(row['county'] for row in arithmetic['unavailable_groups'])
    output = []
    for cid, catalog_row in sorted(catalog.items()):
        county = counties.get(cid)
        reference = references.get(cid) if county else staged_refs.get(cid)
        if county and reference is None:
            raise ValueError(f'Admitted county missing native reference: {cid}')
        universes = ({year: {p for g in reference['groups'] for p in g[key]}
                      for year, key in [(2024, 'old'), (2026, 'new')]}
                     if reference else {})
        source_paths = []
        if county:
            sources = county['sources']
            origin = 'qualified_snapshot'
        else:
            sources = []
            origin = 'retained_cache_unqualified'
            for year in [2024, 2026]:
                path = data / f'cache/{cid}/{year}-series.json'
                if path.exists():
                    source_paths.append({'path': str(path), 'sha256': sha(path)})
                    sources.extend(read(path))
        local_controls = [c for c in controls if c['county'] == cid]
        source_rows = [source_diagnostic(s, universes.get(int(s['date'][:4])),
                                         local_controls, days, origin) for s in sources]
        review = review_map.get(cid)
        fresh = bool(review and (review.get('fresh_evidence') or review.get('fresh_findings')))
        cv = by_coverage.get(cid, [])
        missing_dates = {}
        for year, start in coverage_owner.START.items():
            present = {s['date'] for s in sources if not s.get('cumulative', False)}
            missing_dates[str(year)] = [str(start + timedelta(days=i)) for i in range(days)
                                        if str(start + timedelta(days=i)) not in present]
        cls = classification(reference, county)
        views = view_coverage(documents, cid, universes.get(2026))
        view_gaps = [name for name, value in views.items()
                     if not value['native_universe_known'] or not value['file_present']
                     or value['missing_records'] or value['missing_or_invalid_denominator']
                     or value['zero_denominator']]
        disposition = (review or {}).get('disposition') or (
            'unadmitted_source_gap' if not county else 'real_source_gap' if unavailable[cid]
            or cls['missing_native_2024_ids'] else 'healthy')
        output.append({
            'county': cid, 'name': catalog_row['name'], 'fips': catalog_row['fips'],
            'admitted': county is not None,
            'native_reference_origin': 'admitted_reference' if county else 'explicit_staged_reference' if reference else None,
            'coverage_by_day': cv, 'classification': cls,
            'missing_daily_source_dates': missing_dates,
            'sources': source_rows, 'retained_source_paths': source_paths,
            'independent_controls': local_controls,
            'turnout_disposition': disposition,
            'disposition': 'view_source_gap' if disposition == 'healthy' and view_gaps else disposition,
            'view_coverage': views, 'view_gaps': view_gaps,
            'all_views_complete': bool(county and not unavailable[cid] and not view_gaps
                                       and not cls['missing_native_2024_ids']
                                       and not cls['tied_native_2024_ids']
                                       and not cls['mixed_margin_native_2026_ids']),
            'next_action': (review or {}).get('next_action') or (
                'Obtain an official native precinct relationship and a valid same-day common group before admission.' if not county
                else 'Investigate attributed missing date/precinct observations and certified native presidential references; preserve known daily subsets.' if disposition != 'healthy'
                else 'Continue dated ordinary in-person source/control checks.'),
            'evidence_freshness': 'freshly_verified_review' if fresh else 'retained_only',
            'review': review,
        })
    return {
        'schema_version': 1, 'snapshot_generated_at': snapshot['generated_at'],
        'through': snapshot.get('through'), 'days': days,
        'county_count': len(output), 'admitted_counties': len(counties),
        'catalog_sha256': sha(data / 'county-reference.json'),
        'reference_sha256': sha(data / 'reference.json'),
        'completeness_sha256': sha(controls_path) if controls_path.exists() else None,
        'view_sources': {name: {'path': str(path), 'sha256': sha(path) if path.exists() else None}
                         for name, (_, path, _) in documents.items()},
        'coverage_arithmetic_owner': str(OWNER.relative_to(ROOT)),
        'published_coverage_reconciled': arithmetic['verified_against_published'],
        'summaries': arithmetic['summaries'], 'counties': output,
        'limitations': [
            'Offline retained anonymous aggregates only; freshly verified means an explicitly attached county review, not a network request by this command.',
            'Daily source counts and cumulative paired coverage are distinct. Future comparison dates are flagged and excluded by the arithmetic owner.',
            'Unknown or quarantined precinct observations never imply zero. Control agreement alone does not promote a source complete flag.',
            'Unadmitted counties remain listed; native identity diagnostics are undefined unless an explicit staged reference is supplied.',
            'Demographic/Census, primary and place coverage separately distinguish absent records from recorded zero denominators; no healthy turnout label certifies all views.',
            'Presidential reference diagnostics use the supplied root reference edition. Review baseline generations are preserved separately from current coverage.',
            'Mail is excluded from these precinct observations unless a future analytical contract explicitly supports matching mail dates/geography.',
        ],
    }


def markdown(result):
    lines = ['# Texas precinct methodology audit', '',
             f"Snapshot `{result['snapshot_generated_at']}` · {result['county_count']} counties · {result['admitted_counties']} admitted · through {result['through']}", '',
             '| County | Day 1 paired | Latest paired | Missing / tied native returns | Disposition | Next action |',
             '|---|---:|---:|---:|---|---|']
    for row in result['counties']:
        cv = row['coverage_by_day']
        pair = lambda c: f"{c.get('available_precincts', 0)}/{c['total_precincts']}"
        cls = row['classification']
        counts = ('—' if cls['missing_native_2024_ids'] is None else
                  f"{len(cls['missing_native_2024_ids'])} / {len(cls['tied_native_2024_ids'])}")
        action = row['next_action']
        if isinstance(action, list):
            action = ' '.join(action)
        action = ' '.join(str(action).split()).replace('|', '/')
        if row['view_gaps']:
            action = 'View gaps: ' + ', '.join(row['view_gaps']) + '. ' + action
        if len(action) > 220:
            action = action[:217].rsplit(' ', 1)[0] + '…'
        lines.append(f"| {row['name']} | {pair(cv[0]) if cv else 'not admitted'} | {pair(cv[-1]) if cv else 'not admitted'} | {counts} | {row['disposition']} | {action} |")
    lines.extend(['', '## Methodology and source guards', ''])
    lines.extend('- ' + limitation for limitation in result['limitations'])
    return '\n'.join(lines) + '\n'


def validate_output_paths(root, outputs, inputs):
    protected = [(root / 'dashboard/data').resolve(), (root / 'dashboard/places').resolve()]
    exact = {p.resolve() for p in inputs if p is not None}
    for output in outputs:
        if output is None:
            continue
        path = output.resolve()
        if path in exact or any(path == folder or folder in path.parents for folder in protected):
            raise ValueError('Audit output must not overwrite source data or an input artifact')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--markdown', type=Path)
    parser.add_argument('--reviews', type=Path, nargs='+')
    parser.add_argument('--staged-reference', type=Path, action='append')
    args = parser.parse_args()
    snapshot_path = args.snapshot or args.root / 'dashboard/data/latest.json'
    validate_output_paths(args.root, [args.output, args.markdown],
                          [snapshot_path, *(args.reviews or []), *(args.staged_reference or [])])
    snapshot = read(snapshot_path)
    result = build(args.root, snapshot, args.reviews, args.staged_reference)
    result['snapshot_path'] = str(snapshot_path)
    result['snapshot_sha256'] = sha(snapshot_path)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown(result))
    print(json.dumps({'counties': result['county_count'], 'admitted': result['admitted_counties'],
                      'published_coverage_reconciled': result['published_coverage_reconciled'],
                      'dispositions': dict(Counter(r['disposition'] for r in result['counties']))}))


if __name__ == '__main__':
    main()
