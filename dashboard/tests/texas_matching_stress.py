"""Independent anonymous-data audit of Texas matching, classifications and OLS.

Uses saved aggregate API observations only; never refreshes official sources.
TURNOUT_TEST_URL=http://127.0.0.1:8743 python tests/texas_matching_stress.py
"""
from __future__ import annotations

import bisect
import json
import math
import os
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
BASE = os.environ.get('TURNOUT_TEST_URL', 'http://127.0.0.1:8743')
OUT = ROOT / 'analysis/texas-stress'
TAG = os.environ.get('TURNOUT_TEST_TAG', 'matching-api')


def get(path):
    with urlopen(BASE + path, timeout=120) as response:
        return json.load(response)


def start(year):
    return date(year, 10, 21 if year == 2024 else 19)


def precinct_id(value):
    label = value.strip().lstrip('\ufeff').upper()
    return label.lstrip('0') or ('0' if label else 'UNASSIGNED')


def resolve(sources, year, ids):
    """Compare explicit source presence, complete-roster zeros and arithmetic.

    A cumulative correction invalidates only that precinct's derived daily delta;
    it cannot delete its otherwise valid cumulative observation.
    """
    latest = {}
    for source in sources:
        if date.fromisoformat(source['date']).year != year:
            continue
        key = (source['date'], source.get('cumulative', False))
        prior = latest.get(key)
        if prior is None or source['retrieved_at'] >= prior['retrieved_at']:
            latest[key] = source
    def direct(day, cumulative):
        source = latest.get(((start(year) + timedelta(days=day)).isoformat(), cumulative))
        if source is None:
            return None
        assert all(type(value) is int and value >= 0 for value in source['counts'].values())
        unavailable = {precinct_id(p) for p in source.get('unavailable_precincts', [])}
        # A reconciled county total cannot locate voters with unproven labels.
        # Keep the actual reference universe fixed when inferring native zeros.
        certified = (source['complete'] and not unavailable
                     and not any(value > 0 and p not in ids for p, value in source['counts'].items()))
        return {p: source['counts'].get(p, 0) for p in ids
                if precinct_id(p) not in unavailable and (p in source['counts'] or certified)}
    cumulative = []
    daily = []
    for day in range(12):
        ev = direct(day, False)
        total = direct(day, True)
        if total is None and ev is not None:
            if day == 0:
                total = dict(ev)
            elif cumulative[-1] is not None:
                total = {p: ev[p] + cumulative[-1][p] for p in ev.keys() & cumulative[-1].keys()}
        if ev is None and total is not None:
            prior = cumulative[-1] if day else dict.fromkeys(ids, 0)
            if prior is not None:
                ev = {p: total[p] - prior[p] for p in total.keys() & prior.keys() if total[p] >= prior[p]}
        cumulative.append(total)
        daily.append(ev)
    return daily, cumulative


def check_resolver_contract():
    ids = {'1', '2'}
    def observation(day, counts, *, cumulative=False, unavailable=()):
        return {'date': f'2026-10-{18 + day}', 'counts': counts, 'complete': True,
                'retrieved_at': '', 'cumulative': cumulative, 'unavailable_precincts': list(unavailable)}
    first = observation(1, {'1': 10, '99999': 1})
    second = observation(2, {'1': 5})
    daily, cumulative = resolve([first, second], 2026, ids)
    assert daily[0] == {'1': 10} and cumulative[1] == {'1': 15}
    assert daily[1] == {'1': 5, '2': 0}
    daily, cumulative = resolve([observation(1, {'1': 10}), observation(2, {'1': 15, '99999': 1}, cumulative=True)], 2026, ids)
    assert cumulative[1] == {'1': 15} and daily[1] == {'1': 5}
    daily, cumulative = resolve([observation(1, {'1': 9, '2': 10}, unavailable=['001'])], 2026, ids)
    assert daily[0] == cumulative[0] == {'2': 10}
    daily, cumulative = resolve([observation(1, {'1': 10, '99999': 0})], 2026, ids)
    assert daily[0] == cumulative[0] == {'1': 10, '2': 0}
    return 5


def fit(points):
    if len(points) < 2 or len({p[0] for p in points}) < 2:
        return None
    if len({p[1] for p in points}) == 1:
        return points[0][1], 0.0, None
    mx = math.fsum(x for x, _ in points) / len(points)
    my = math.fsum(y for _, y in points) / len(points)
    slope = math.fsum((x - mx) * (y - my) for x, y in points) / math.fsum((x - mx) ** 2 for x, _ in points)
    intercept = my - slope * mx
    total = math.fsum((y - my) ** 2 for _, y in points)
    r2 = None if not total else max(0, min(1, 1 - math.fsum((y - intercept - slope * x) ** 2 for x, y in points) / total))
    return intercept, slope, r2


def check_fit(actual, points):
    expected = fit(points)
    assert (actual is None) == (expected is None), ('fit presence', actual, expected)
    if expected is None:
        return
    for field, value in zip(['intercept', 'slope', 'r_squared'], expected):
        if value is None:
            assert actual[field] is None
        else:
            assert math.isclose(actual[field], value, rel_tol=1e-8, abs_tol=1e-8), (field, actual[field], value)


def party(reference, group):
    returns = [reference['presidential'].get(p) for p in group['old']]
    if any(value is None for value in returns):
        return 0, 0
    return sum(v['harris'] for v in returns), sum(v['trump'] for v in returns)


def metric_value(classification, metric, county, members):
    precincts = classification['counties'].get(county, {}).get('precincts', {})
    values = []
    for member in members:
        counts = precincts.get(member, {}).get('counts', {})
        n, d = counts.get(metric['numerator']), counts.get(metric['denominator'])
        if n is None or d is None or not math.isfinite(n) or not math.isfinite(d) or not 0 <= n <= d:
            return None
        values.append((n, d))
    numerator = math.fsum(v[0] for v in values)
    denominator = math.fsum(v[1] for v in values)
    return 100 * numerator / denominator if denominator else None


def run():
    oracle_contract_checks = check_resolver_contract()
    snapshot = get('/api/data')
    references = {value['id']: value for value in get('/api/reference')}
    counts = Counter()
    counts['oracle_contract_checks'] = oracle_contract_checks
    assert {county['id'] for county in snapshot['counties']} == set(references)
    errors = []
    seen_partial = []
    for county in snapshot['counties']:
        ref = references[county['id']]
        old_ids = {p for g in ref['groups'] for p in g['old']}
        new_ids = {p for g in ref['groups'] for p in g['new']}
        old = resolve(county['sources'], 2024, old_ids)
        new = resolve(county['sources'], 2026, new_ids)
        periods = {p['day']: p for p in county['periods']}
        for day in range(snapshot['days']):
            a, b = old[1][day], new[1][day]
            expected = []
            for native in ref['groups']:
                available = a is not None and b is not None and all(p in a for p in native['old']) and all(p in b for p in native['new'])
                expected.append(available)
            if not any(expected):
                assert day + 1 not in periods
                continue
            period = periods[day + 1]
            assert len(period['groups']) == len(expected)
            av = bv = 0
            for index, (actual, native, available) in enumerate(zip(period['groups'], ref['groups'], expected)):
                assert actual['available'] == available, ('availability', county['id'], day + 1, index)
                assert (actual['old'], actual['new']) == (native['old'], native['new'])
                votes = (sum(a[p] for p in native['old']), sum(b[p] for p in native['new'])) if available else (0, 0)
                assert (actual['votes_2024'], actual['votes_2026']) == votes
                av += votes[0]; bv += votes[1]
                presidential = party(ref, native)
                if (actual['harris'], actual['trump']) != presidential:
                    errors.append({'county': county['id'], 'day': day + 1, 'group': index,
                                   'issue': 'partial presidential returns imply a winner',
                                   'actual': [actual['harris'], actual['trump']], 'expected': list(presidential)})
                if available and presidential == (0, 0) and any(p not in ref['presidential'] for p in native['old']):
                    seen_partial.append((county['id'], day + 1, index))
                counts['group_comparisons'] += 1
            assert (period['county_2024'], period['county_2026']) == (av, bv)
            counts['county_periods'] += 1
    # Check each published partisan regression against independently calculated
    # common-geography presidential margins and the native matched turnout sums.
    county_by_id = {c['id']: c for c in snapshot['counties']}
    for regression in snapshot['regressions']:
        selected = snapshot['counties'] if regression['county'] == 'all' else [county_by_id[regression['county']]]
        points = []
        omitted = 0
        for county in selected:
            period = next((p for p in county['periods'] if p['day'] == regression['day']), None)
            ref = references[county['id']]
            exact_pairs = {tuple(pair) for pair in ref['exact_pairs']}
            for actual, native in zip(period['groups'] if period else [], ref['groups']):
                memberships = []
                for member in native['old']:
                    value = ref['presidential'].get(member)
                    if value is None or value['harris'] == value['trump']:
                        memberships.append(None)
                        continue
                    h, t = value['harris'], value['trump']
                    margin = 100 * abs(h - t)
                    band = 2 if margin >= 30 * (h + t) else 1 if margin >= 15 * (h + t) else 0
                    memberships.append(2 - band if h > t else 3 + band)
                bucket = memberships[0] if len(set(memberships)) == 1 else None
                assert actual['bucket'] == bucket
                unchanged = len(native['old']) == len(native['new']) == 1 and (native['old'][0], native['new'][0]) in exact_pairs and bucket is not None
                assert actual['unchanged'] == unchanged
                if not actual['available'] or (not unchanged if regression['cohort'] == 'unchanged' else bucket is None):
                    continue
                if actual['votes_2024'] == 0:
                    omitted += 1
                    continue
                h, t = party(ref, native)
                if h + t:
                    points.append((100 * h / (h + t), 100 * actual['votes_2026'] / actual['votes_2024']))
        assert regression['n'] == len(points)
        assert regression['omitted_zero_baseline'] == omitted
        check_fit(regression['fit'], points)
        counts['partisan_regression_fits'] += 1
    # Preserve all aggregate data even if the baseline contains the discovered issue.
    classifications = [('demographic', get('/api/demographics')), ('primary', get('/api/primary'))]
    for view_type, classification in classifications:
        for metric in classification['metrics']:
            cuts = [v for v in metric['cuts'] if 0 < v < 100]
            for cohort in ['matched', 'unchanged']:
                for day in range(1, snapshot['days'] + 1):
                    payload = get('/api/demographic-view?' + urlencode({'view': view_type, 'metric': metric['id'], 'day': day, 'cohort': cohort}))
                    assert payload['generated_at'] == snapshot['generated_at'], 'Audit snapshot changed'
                    points = []
                    buckets = [[0, 0, 0] for _ in range(len(cuts) + 1)]
                    for county in snapshot['counties']:
                        period = next((p for p in county['periods'] if p['day'] == day), None)
                        expected = {}
                        for index, group in enumerate(period['groups'] if period else []):
                            if not group['available'] or cohort == 'unchanged' and not group['unchanged']:
                                continue
                            x = metric_value(classification, metric, county['id'], group['new'])
                            if x is not None:
                                expected[index] = (group, x)
                        view = payload['views'][county['id']]
                        assert {p['group_index'] for p in view['points']} == set(expected)
                        local_points = []
                        for point in view['points']:
                            group, x = expected[point['group_index']]
                            assert math.isclose(point['x'], x, abs_tol=1e-10)
                            bucket = bisect.bisect_right(cuts, x)
                            assert point['bucket'] == bucket
                            assert (point['votes_2024'], point['votes_2026']) == (group['votes_2024'], group['votes_2026'])
                            y = 100 * group['votes_2026'] / group['votes_2024'] if group['votes_2024'] else None
                            assert point['y'] is None if y is None else math.isclose(point['y'], y, abs_tol=1e-9)
                            buckets[bucket][0] += 1; buckets[bucket][1] += group['votes_2024']; buckets[bucket][2] += group['votes_2026']
                            if y is not None:
                                local_points.append((x, y))
                            counts['demographic_point_comparisons'] += 1
                        check_fit(view['fit'], local_points)
                        assert view['n'] == len(local_points)
                        points.extend(local_points)
                        counts['county_demographic_fits'] += 1
                    overall = payload['views']['all']
                    for actual, expected in zip(overall['bins'], buckets):
                        assert (actual['groups'], actual['votes_2024'], actual['votes_2026']) == tuple(expected)
                        ratio = expected[2] / expected[1] if expected[1] else None
                        assert actual['ratio'] is None if ratio is None else math.isclose(actual['ratio'], ratio, abs_tol=1e-12)
                    assert overall['n'] == len(points)
                    check_fit(overall['fit'], points)
                    counts['aggregate_demographic_fits'] += 1
    assert get('/api/data')['generated_at'] == snapshot['generated_at']
    report = {'status': 'failed' if errors else 'passed', 'base_url': BASE,
              'snapshot_generated_at': snapshot['generated_at'], 'through': snapshot['through'],
              'precinct_counties': len(snapshot['counties']),
              'checks': dict(counts), 'unknown_presidential_available_group_dates': len(set(seen_partial)),
              'errors': errors}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f'{TAG}.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'errors'}, indent=2))
    assert not errors, f'{len(errors)} partial presidential group-date failures; see {OUT / (TAG + ".json")}'


if __name__ == '__main__':
    run()
