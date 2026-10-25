#!/usr/bin/env python3
"""Independent all-state API reconciliation against normalized official sources.

Uses only standard library. Run against an offline/frozen server:
python3 dashboard/tests/multistate_api.py --base-url http://127.0.0.1:8743
"""
import argparse
import collections
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
from functools import lru_cache
import json
import math
from pathlib import Path
import statistics
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / 'analysis/multistate/qa/api-verification.json'
ELECTION = {2024: dt.date(2024, 11, 5), 2026: dt.date(2026, 11, 3)}
ALLOWED_NATIVE = {'party', 'race', 'age', 'sex', 'ethnicity', 'white_nonwhite', 'nonwhite'}


def shifted(date, days):
    return (dt.date.fromisoformat(date) + dt.timedelta(days=days)).isoformat()


def previous(date):
    return shifted(date, -1)


def historical(date):
    return (ELECTION[2024] - (ELECTION[2026] - dt.date.fromisoformat(date))).isoformat()


def combine(a, b, subtract=False):
    result = {}
    for dimension in a.keys() & b.keys():
        target = {}
        for label in a[dimension].keys() & b[dimension].keys():
            value = a[dimension][label] + (-1 if subtract else 1) * b[dimension][label]
            if value < 0:
                target = None
                break
            target[label] = value
        if target is not None:
            result[dimension] = target
    return result


class Sources:
    def __init__(self, state):
        self.data = json.loads((ROOT / f'dashboard/data/states/{state}.json').read_text())
        self.reference = json.loads((ROOT / f'dashboard/data/states/{state}-reference.json').read_text())
        self.exact = {}
        self.observation_count = len(self.data['observations'])
        for row in self.data['observations']:
            if row.get('precinct') is not None:
                continue
            key = (row['year'], row['date'], row['county'], row['method'], row['measure'])
            assert key not in self.exact, f'{state}: duplicate normalized observation {key}'
            assert isinstance(row['votes'], int) and row['votes'] >= 0
            assert row['date'].startswith(str(row['year']))
            self.exact[key] = (row['votes'], row.get('breakdowns', {}))
        self.metadata = {r['county']: {'id': r['county'], 'name': r.get('county_name', '')}
                         for r in self.data['observations'] if r.get('precinct') is None}
        self.metadata.update({row['id']: dict(row) for row in self.data.get('counties', [])})
        refs = self.reference['counties']
        def canonical(name):
            return ''.join(x for x in name.lower().replace(' county', '') if x.isascii() and x.isalnum())
        for id_, row in self.metadata.items():
            ref = refs.get(row.get('fips', id_))
            if ref is None:
                ref = next((value for value in refs.values()
                            if canonical(value['name']) == canonical(row['name'])), None)
            if ref:
                for key in ('fips', 'demographics', 'counts', 'harris', 'trump'):
                    if key in ref:
                        row.setdefault(key, ref[key])
            harris, trump = row.get('harris'), row.get('trump')
            row['harris_share'] = (100 * harris / (harris + trump)
                                   if harris is not None and trump is not None and harris + trump else None)
        self.counties = sorted(self.metadata)
        self.dimensions = sorted({k for row in self.data['observations'] for k in row.get('breakdowns', {})})
        self.methods = sorted({row['method'] for row in self.data['observations']})
        if 'mail' in self.methods and 'in_person' in self.methods and 'total' not in self.methods:
            self.methods.append('total')

    @lru_cache(maxsize=None)
    def value(self, year, date, county, method, measure):
        # Resolve source observations independently, retaining unknowns. Exact
        # measures take precedence; snapshots are never substituted across dates.
        if year == 2026 and date > self.data['through']:
            return None
        key = (year, date, county, method, measure)
        if key in self.exact:
            return self.exact[key]
        if method == 'total':
            components = [self.value(year, date, county, m, measure) for m in ('in_person', 'mail')]
            if any(row is None for row in components):
                return None
            a, b = components
            return a[0] + b[0], combine(a[1], b[1])
        if measure == 'daily':
            a = self.exact.get((year, date, county, method, 'cumulative'))
            b = self.exact.get((year, previous(date), county, method, 'cumulative'))
            if a is None or b is None or a[0] < b[0]:
                return None
            return a[0] - b[0], combine(a[1], b[1], subtract=True)
        first = self.data['start_dates'][str(year)]
        cursor, tail = date, []
        while cursor >= first:
            anchor = self.exact.get((year, cursor, county, method, 'cumulative'))
            if anchor is not None:
                count, breakdowns = anchor
                for increment, groups in reversed(tail):
                    count += increment
                    breakdowns = combine(breakdowns, groups)
                return count, breakdowns
            increment = self.exact.get((year, cursor, county, method, 'daily'))
            if increment is None:
                return None
            tail.append(increment)
            cursor = previous(cursor)
        if not tail:
            return None
        count, breakdowns = tail.pop()
        for increment, groups in reversed(tail):
            count += increment
            breakdowns = combine(breakdowns, groups)
        return count, breakdowns

    def amount(self, year, date, county, method, measure, dimension=None):
        value = self.value(year, date, county, method, measure)
        if value is None:
            return None
        return value[0] if dimension is None else value[1].get(dimension[0], {}).get(dimension[1])

    def point(self, date, counties, method, measure, dimension=None):
        future = date > self.data['through']
        old, new, reported = 0, 0, 0
        members, reported_members = [], []
        for county in sorted(counties):
            a = self.amount(2024, historical(date), county, method, measure, dimension)
            b = self.amount(2026, date, county, method, measure, dimension)
            if b is not None:
                reported += b
                reported_members.append(county)
            if a is not None and (b is not None or future):
                old += a
                new += 0 if b is None else b
                members.append(county)
        return (old if members else None, new if members and not future else None,
                members, reported if reported_members else None)


def get_json(base, path, query=None):
    if query:
        path += '?' + urllib.parse.urlencode(query)
    with urllib.request.urlopen(base.rstrip('/') + path, timeout=55) as response:
        return json.load(response)


class Check:
    def __init__(self):
        self.checks = collections.Counter()
        self.failures = []

    def eq(self, actual, expected, context, category='values'):
        self.checks[category] += 1
        if actual != expected:
            if len(self.failures) < 30:
                self.failures.append({'context': context, 'actual': actual, 'expected': expected})

    def close(self, actual, expected, context, category='regression'):
        self.checks[category] += 1
        if actual is None or not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-8):
            if len(self.failures) < 30:
                self.failures.append({'context': context, 'actual': actual, 'expected': expected})


def check_series(check, source, series, counties, method, context, dimension=None):
    for row in series:
        date = row['date_2026']
        location = f'{context}/{date}'
        check.eq(row['date_2024'], historical(date), location + '/calendar', 'calendar')
        check.eq(row['days_before_election'], (ELECTION[2026] - dt.date.fromisoformat(date)).days,
                 location + '/days_before_election', 'calendar')
        check.eq(row['future'], date > source.data['through'], location + '/future', 'calendar')
        for measure in ('daily', 'cumulative'):
            old, new, members, reported = source.point(date, counties, method, measure, dimension)
            check.eq(row[measure + '_2024'], old, location + '/' + measure + '_2024', 'series_values')
            check.eq(row[measure + '_2026'], new, location + '/' + measure + '_2026', 'series_values')
            check.eq(row[measure + '_members'], members, location + '/' + measure + '_members', 'memberships')
            check.eq(row['reported_' + measure + '_2026'], reported,
                     location + '/reported_' + measure + '_2026', 'reported_values')
            if old is None or new is None:
                check.checks['unknown_cells_verified'] += 1
            if old == 0 or new == 0:
                check.checks['zero_cells_verified'] += 1
            if row['future']:
                check.eq(new, None, location + '/' + measure + '/future_current', 'future_cells')
                if old is not None:
                    check.checks['future_baselines_retained'] += 1


def check_metadata(check, source, view):
    check.eq(sorted(row['id'] for row in view['counties']), source.counties, 'county roster', 'metadata')
    for row in view['counties']:
        native = source.metadata[row['id']]
        check.eq(row.get('fips'), native.get('fips'), row['id'] + '/fips', 'metadata')
        for key in ('harris', 'trump', 'counts'):
            if key in native:
                check.eq(row.get(key), native[key], row['id'] + '/' + key, 'metadata')
        for key, value in native.get('demographics', {}).items():
            check.close(row.get('demographics', {}).get(key), value, row['id'] + '/demographics/' + key, 'metadata')
        if native['harris_share'] is None:
            check.eq(row['harris_share'], None, row['id'] + '/unknown_partisanship', 'metadata')
        else:
            check.close(row['harris_share'], native['harris_share'], row['id'] + '/share', 'metadata')
        ref = source.reference['counties'].get(row.get('fips', ''))
        if ref:
            counts, demographics = ref['counts'], ref['demographics']
            for metric, value in demographics.items():
                denominator = counts['population'] if metric == 'under18' else counts['vap']
                check.close(value, 100 * counts[metric] / denominator, row['id'] + '/census/' + metric, 'census')
            check.eq(counts['non_white_vap'] + counts['white_nh_vap'], counts['vap'],
                     row['id'] + '/census/nonwhite_identity', 'census')


def bucket_members(source, classification, metric):
    members = [[] for _ in range(6 if classification == 'partisan' else 5)]
    for id_, row in source.metadata.items():
        if classification == 'partisan':
            share = row['harris_share']
            if share is None or share == 50:
                continue
            margin = abs(2 * share - 100)
            band = 0 if margin >= 30 else 1 if margin >= 15 else 2
            members[band if share > 50 else 5 - band].append(id_)
        else:
            value = row.get('demographics', {}).get(metric)
            if value is not None:
                members[min(int(value // 20), 4)].append(id_)
    return [sorted(group) for group in members]


def check_regression(check, source, view, counties):
    selected = view['date']
    expected = {}
    for id_ in counties:
        meta = source.metadata[id_]
        x = (meta.get('demographics', {}).get(view['metric']) if view['classification'] == 'demographic'
             else meta['harris_share'])
        old, new, members, _ = source.point(selected, [id_], view['method'], 'cumulative')
        if x is None or old is None or new is None or old == 0:
            continue
        expected[id_] = (x, 100 * new / old, old, new)
    check.eq(sorted(row['id'] for row in view['points']), sorted(expected), 'regression point identities', 'regression')
    for point in view['points']:
        if point['id'] not in expected:
            continue
        x, y, old, new = expected[point['id']]
        check.close(point['x'], x, point['id'] + '/x')
        check.close(point['y'], y, point['id'] + '/y')
        check.eq((point['votes_2024'], point['votes_2026']), (old, new), point['id'] + '/regression_votes', 'regression')
    values = list(expected.values())
    xs, ys = [v[0] for v in values], [v[1] for v in values]
    fit = view['fit']
    if len(values) < 2 or max(xs) == min(xs):
        check.eq(fit, None, 'insufficient regression support', 'regression')
        return
    mx, my = statistics.mean(xs), statistics.mean(ys)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    intercept = my - slope * mx
    sst = sum((y - my) ** 2 for y in ys)
    sse = sum((y - intercept - slope * x) ** 2 for x, y in zip(xs, ys))
    check.close(fit['slope'], slope, 'fit slope')
    check.close(fit['intercept'], intercept, 'fit intercept')
    check.close(fit['x_min'], min(xs), 'fit minimum')
    check.close(fit['x_max'], max(xs), 'fit maximum')
    if sst:
        check.close(fit['r_squared'], min(1, max(0, 1 - sse / sst)), 'fit R2')
    else:
        check.eq(fit['r_squared'], None, 'constant outcome R2', 'regression')


def check_view(source, view, full_table=False):
    check = Check()
    classification, metric, method = view['classification'], view['metric'], view['method']
    scope = source.counties
    check.eq(view['generated_at'], source.data['generated_at'], 'frozen dataset generation', 'snapshot')
    check.eq(view['through'], source.data['through'], 'source cutoff', 'snapshot')
    check.eq(view['election_dates'], {'2024': '2024-11-05', '2026': '2026-11-03'}, 'election dates', 'calendar')
    check_series(check, source, view['series'], scope, method, 'statewide')
    if full_table:
        check_metadata(check, source, view)
        for row in view['counties']:
            check_series(check, source, row['series'], [row['id']], method, 'table/' + row['id'])
            selected = next((day for day in row['series'] if day['date_2026'] == view['date']), None)
            check.eq(row['selected'], selected, row['id'] + '/selected', 'table_selected')
    if classification in ('partisan', 'demographic'):
        expected = bucket_members(source, classification, metric)
        check.eq(len(view['buckets']), len(expected), 'bucket count', 'bucket_memberships')
        for bucket, counties in zip(view['buckets'], expected):
            check.eq(bucket['members'], counties, bucket['label'] + '/members', 'bucket_memberships')
            check_series(check, source, bucket['series'], counties, method, 'bucket/' + bucket['label'])
    else:
        labels = sorted({label for row in source.data['observations']
                         for label in row.get('breakdowns', {}).get(classification, {})})
        check.eq([bucket['label'] for bucket in view['buckets']], labels, 'native bucket labels', 'bucket_memberships')
        for bucket in view['buckets']:
            check_series(check, source, bucket['series'], scope, method,
                         'native/' + bucket['label'], (classification, bucket['label']))
    check_regression(check, source, view, scope)
    return check


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8743')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--states', nargs='+', default=['ga', 'nc', 'va', 'nv'])
    args = parser.parse_args()
    started = time.monotonic()
    result = {'base_url': args.base_url, 'verified_at': dt.datetime.now(dt.timezone.utc).isoformat(),
              'states': {}, 'failures': [], 'checks': {}}
    total = collections.Counter()
    catalog = {row['id']: row for row in get_json(args.base_url, '/api/states')['states']}
    sources, jobs = {}, []
    for state in args.states:
        if catalog.get(state, {}).get('status') != 'available':
            result['states'][state] = {'status': 'unavailable', 'catalog': catalog.get(state)}
            continue
        source = sources[state] = Sources(state)
        methods = sorted(set(source.methods))
        for method in methods:
            jobs.append((state, {'method': method, 'classification': 'partisan'}, True))
        metric = source.reference['metrics'][0]['id']
        jobs.append((state, {'method': 'in_person' if 'in_person' in methods else methods[0],
                             'classification': 'demographic', 'metric': metric}, False))
        for dimension in source.dimensions:
            if dimension in ALLOWED_NATIVE:
                jobs.append((state, {'method': 'in_person' if 'in_person' in methods else methods[0],
                                     'classification': dimension}, False))
        result['states'][state] = {'status': 'pending', 'generation': source.data['generated_at'],
                                  'source_observations': source.observation_count, 'counties': len(source.counties),
                                  'native_breakdowns': source.dimensions, 'methods': methods, 'views': []}
    def fetch(job):
        state, query, full = job
        return job, get_json(args.base_url, '/api/states/' + state, query)
    with ThreadPoolExecutor(max_workers=3) as pool:
        pending = {pool.submit(fetch, job): job for job in jobs}
        for future in as_completed(pending):
            try:
                (state, query, full), view = future.result()
                check = check_view(sources[state], view, full)
                total.update(check.checks)
                tagged = [{'state': state, 'query': query, **failure} for failure in check.failures]
                result['failures'].extend(tagged)
                result['states'][state]['views'].append({'query': query, 'checks': dict(check.checks),
                                                        'failures': len(check.failures), 'points': len(view['points'])})
                print(state, query, sum(check.checks.values()), 'checks,', len(check.failures), 'failures', flush=True)
            except Exception as error:
                state, query, _ = pending[future]
                result['failures'].append({'state': state, 'query': query, 'request_error': str(error)})
                print('REQUEST/CHECK ERROR:', error, flush=True)
    for state, source in sources.items():
        try:
            geometry = get_json(args.base_url, '/api/states/' + state + '/map')
        except Exception as error:
            result['failures'].append({'state': state, 'request_error': str(error), 'path': 'map'})
            result['states'][state]['status'] = 'failed'
            continue
        ids = [feature['properties']['GEOID'] for feature in geometry['features']]
        refs = source.reference['counties']
        check = Check()
        check.eq(len(ids), len(set(ids)), state + '/unique map FIPS', 'maps')
        check.eq(sorted(ids), sorted(refs), state + '/map/reference FIPS', 'maps')
        for id_, meta in source.metadata.items():
            if 'fips' in meta:
                check.eq(meta['fips'] in refs, True, id_ + '/reference membership', 'maps')
                check.eq(meta['fips'] in ids, True, id_ + '/map membership', 'maps')
        total.update(check.checks)
        result['failures'].extend([{'state': state, **failure} for failure in check.failures])
        result['states'][state]['map_counties'] = len(ids)
        result['states'][state]['status'] = ('failed' if any(f.get('state') == state for f in result['failures']) else 'passed')
    result['checks'], result['requests'], result['elapsed_seconds'] = dict(total), len(jobs), round(time.monotonic() - started, 2)
    result['status'] = 'failed' if result['failures'] else 'passed'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'requests': len(jobs), 'checks': sum(total.values()),
                      'failures': len(result['failures']), 'elapsed_seconds': result['elapsed_seconds'],
                      'output': str(args.output)}, indent=2))
    if result['failures']:
        print(json.dumps(result['failures'][:10], indent=2))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
