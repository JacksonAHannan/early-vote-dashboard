"""Independently audit maximal same-geography reported turnout subsets.

No network sources or voter records are acquired. The test reads the dashboard's
anonymous observations and reconstructs which precincts are known at every date.
TURNOUT_TEST_URL=http://127.0.0.1:8743 python tests/matched_api.py
"""
from __future__ import annotations

import json
import math
import os
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
BASE = os.environ.get('TURNOUT_TEST_URL', 'http://127.0.0.1:8743')
OUT = ROOT / 'analysis/completeness/qa'


def get(path):
    with urlopen(BASE + path, timeout=120) as response:
        return json.load(response)


def start(year):
    return date(year, 10, 21 if year == 2024 else 19)


def source_counts(source, universe):
    if source is None:
        return None
    counts = source['counts']
    assert all(isinstance(value, int) and value >= 0 for value in counts.values())
    return {p: counts.get(p, 0) for p in universe if p in counts or source.get('complete', False)}


def resolve(sources, year, universe):
    """Known membership is explicit presence, or documented complete-source zero.

    A summed cumulative precinct must be known on every contributing daily date.
    An exact dated cumulative snapshot can establish its own known precincts.
    """
    by_cutoff = {}
    for source in sources:
        if date.fromisoformat(source['date']).year != year:
            continue
        key = (source['date'], source.get('cumulative', False))
        assert key not in by_cutoff
        by_cutoff[key] = source
    daily, cumulative = [], []
    for i in range(12):
        d = (start(year) + timedelta(days=i)).isoformat()
        direct = source_counts(by_cutoff.get((d, False)), universe)
        daily.append(direct)
        exact = source_counts(by_cutoff.get((d, True)), universe)
        if exact is not None:
            cumulative.append(exact)
        elif direct is not None and i == 0:
            cumulative.append(dict(direct))
        elif direct is not None and cumulative[i - 1] is not None:
            previous = cumulative[i - 1]
            cumulative.append({p: previous[p] + direct[p] for p in previous.keys() & direct.keys()})
        else:
            cumulative.append(None)
    for i in range(12):
        if daily[i] is not None:
            continue
        d = (start(year) + timedelta(days=i)).isoformat()
        previous_day = (start(year) + timedelta(days=i - 1)).isoformat()
        previous = source_counts(by_cutoff.get((previous_day, True)), universe) if i else dict.fromkeys(universe, 0)
        current = source_counts(by_cutoff.get((d, True)), universe)
        if current is not None and previous is not None:
            daily[i] = {p: current[p] - previous[p] for p in current.keys() & previous.keys() if current[p] >= previous[p]}
    return {'daily': daily, 'cumulative': cumulative}


def match(group, old, new):
    return old is not None and new is not None and all(p in old for p in group['old']) and all(p in new for p in group['new'])


def party_bucket(reference, group):
    returns = reference['presidential']
    if not all(p in returns for p in group['old']):
        return None
    memberships = []
    for p in group['old']:
        h, t = returns[p]['harris'], returns[p]['trump']
        if h == t:
            return None
        margin = 100 * abs(h - t)
        band = 2 if margin >= 30 * (h + t) else 1 if margin >= 15 * (h + t) else 0
        memberships.append(2 - band if h > t else 3 + band)
    return memberships[0] if len(set(memberships)) == 1 else None


def demographic_bucket(data, metric, county, group):
    precincts = data['counties'].get(county, {}).get('precincts', {})
    numerator = denominator = 0
    for p in group['new']:
        counts = precincts.get(p, {}).get('counts', {})
        n, d = counts.get(metric['numerator']), counts.get(metric['denominator'])
        if n is None or d is None or not math.isfinite(n) or not math.isfinite(d) or d < 0 or not 0 <= n <= d:
            return None
        numerator += n
        denominator += d
    if denominator <= 0:
        return None
    share = 100 * numerator / denominator
    return sum(share >= cut for cut in metric['cuts'])


def main():
    snapshot = get('/api/data')
    refs = {r['id']: r for r in get('/api/reference')}
    demo = get('/api/demographics')
    primary = get('/api/primary')
    counties = {c['id']: c for c in snapshot['counties']}
    assert len(counties) == len(refs) == 215
    observed = snapshot['days']
    assert observed == (date.fromisoformat(snapshot['through']) - start(2026)).days + 1
    assert 1 <= observed <= 12
    resolved = {}
    groups_available = source_checks = periods = groups_checked = missing_excluded = 0
    period_counts = {}
    for county_id, county in counties.items():
        ref = refs[county_id]
        universes = {2024: {p for g in ref['groups'] for p in g['old']}, 2026: {p for g in ref['groups'] for p in g['new']}}
        for source in county['sources']:
            universes[date.fromisoformat(source['date']).year].update(source['counts'])
        for source in county['sources']:
            assert 'complete' in source, 'Final matching binary must expose complete-source zero qualification'
            assert source['county'] == county_id
            source_checks += 1
        resolved[county_id] = {year: resolve(county['sources'], year, universes[year]) for year in [2024, 2026]}
        by_day = {p['day']: p for p in county['periods']}
        period_counts[county_id] = len(by_day)
        for i in range(observed):
            old = resolved[county_id][2024]['cumulative'][i]
            new = resolved[county_id][2026]['cumulative'][i]
            expected = [match(g, old, new) for g in ref['groups']]
            if not any(expected):
                if i + 1 in by_day:
                    assert not any(g['available'] for g in by_day[i + 1]['groups'])
                continue
            assert i + 1 in by_day, ('Reported matched subset discarded', county_id, i + 1, sum(expected))
            p = by_day[i + 1]
            assert len(p['groups']) == len(ref['groups'])
            assert p['coverage']['available_groups'] == sum(expected)
            assert p['coverage']['total_groups'] == len(expected)
            old_sum = new_sum = 0
            for index, (group, native, available) in enumerate(zip(p['groups'], ref['groups'], expected)):
                assert group['old'] == native['old'] and group['new'] == native['new']
                assert group['available'] == available, ('Membership mismatch', county_id, i + 1, index)
                if available:
                    expected_old = sum(old[p] for p in native['old'])
                    expected_new = sum(new[p] for p in native['new'])
                    assert group['votes_2024'] == expected_old and group['votes_2026'] == expected_new
                    old_sum += expected_old
                    new_sum += expected_new
                    groups_available += 1
                else:
                    assert group['votes_2024'] == group['votes_2026'] == 0
                    missing_excluded += 1
                groups_checked += 1
            assert p['county_2024'] == old_sum and p['county_2026'] == new_sum, ('County precinct comparison uses unmatched totals', county_id, i + 1)
            assert p['coverage']['available_baseline_votes_2024'] == old_sum
            assert p['coverage']['available_precincts'] == sum(len(g['new']) for g, present in zip(ref['groups'], expected) if present)
            assert p['coverage']['total_precincts'] == sum(len(g['new']) for g in ref['groups'])
            assert p['coverage']['reported_votes_2024'] == sum(old.values()) and p['coverage']['reported_votes_2026'] == sum(new.values())
            periods += 1
    assert periods > 100 and groups_available and missing_excluded, 'Exercise broad restored coverage and missing-precinct exclusion'
    for county in ['tarrant', 'harris', 'collin', 'fortbend']:
        assert period_counts[county] > 0, ('Available county suppressed', county)
    fort_bend_sources = [s for s in counties['fortbend']['sources'] if s['date'].startswith('2026') and not s.get('cumulative', False)]
    assert sum(sum(s['counts'].values()) for s in fort_bend_sources) == 134784
    assert all('county-wide completion is not established' in s['note'] for s in fort_bend_sources)

    statewide = get('/api/statewide')
    county_calendar_cells = matched_county_observations = 0
    assert len(statewide['counties']) == 254
    for county in statewide['counties']:
        assert len(county['days']) == 12
        for row in county['days']:
            i = row['day'] - 1
            for measure, key in [('daily', 'votes'), ('cumulative', 'cumulative')]:
                old_value, new_value = row[f'{key}_2024'], row[f'{key}_2026']
                if i >= observed:
                    assert new_value is None
                else:
                    assert (old_value is None) == (new_value is None)
                    if county['id'] in refs:
                        ref = refs[county['id']]
                        old = resolved[county['id']][2024][measure][i]
                        new = resolved[county['id']][2026][measure][i]
                        included = [g for g in ref['groups'] if match(g, old, new)]
                        if included:
                            assert row['coverage'][f'{measure}_scope'] == 'matched_precincts'
                            assert row['coverage'][measure]['available_groups'] == len(included)
                            assert old_value == sum(old[p] for g in included for p in g['old'])
                            assert new_value == sum(new[p] for g in included for p in g['new'])
                            matched_county_observations += 1
                county_calendar_cells += 2
    regression_summaries = 0
    for regression in snapshot['regressions']:
        n = omitted = 0
        for county in counties.values():
            if regression['county'] not in ['all', county['id']]:
                continue
            period = next((p for p in county['periods'] if p['day'] == regression['day']), None)
            for g in period['groups'] if period else []:
                if not g['available'] or not (g['unchanged'] if regression['cohort'] == 'unchanged' else g['bucket'] is not None):
                    continue
                omitted += g['votes_2024'] == 0
                n += g['votes_2024'] > 0 and g['harris'] + g['trump'] > 0
        assert regression['n'] == n and regression['omitted_zero_baseline'] == omitted
        regression_summaries += 1

    demographic_views = demographic_points = 0
    for cohort in ['matched', 'unchanged']:
        for view_type, classification, metric in [('primary', primary, primary['metrics'][0])] + [('demographic', demo, metric) for metric in demo['metrics']]:
            payload = get('/api/demographic-view?' + urlencode({'view': view_type, 'metric': metric['id'], 'cohort': cohort, 'day': observed}))
            assert payload['generated_at'] == snapshot['generated_at']
            for county_id, county in counties.items():
                view = payload['views'][county_id]
                period = next((p for p in county['periods'] if p['day'] == observed), None)
                expected = {}
                for index, g in enumerate(period['groups'] if period else []):
                    if not g['available'] or cohort == 'unchanged' and not g['unchanged']:
                        continue
                    bucket = demographic_bucket(classification, metric, county_id, g)
                    if bucket is not None:
                        expected[index] = (g, bucket)
                assert {p['group_index'] for p in view['points']} == set(expected), ('Demographic point availability mismatch', county_id, cohort, metric['id'])
                for point in view['points']:
                    group, bucket = expected[point['group_index']]
                    assert point['votes_2024'] == group['votes_2024'] and point['votes_2026'] == group['votes_2026'] and point['bucket'] == bucket
                    demographic_points += 1
                demographic_views += 1

    views = trend_cells = memberships = 0
    classifiers = [('partisan', None, None), ('primary', primary, primary['metrics'][0])] + [('demographic', demo, metric) for metric in demo['metrics']]
    scopes = ['all', 'travis', 'dallas', 'montgomery', 'fortbend', 'tarrant', 'harris', 'collin', 'bexar']
    for scope in scopes:
        selected = list(counties) if scope == 'all' else [scope]
        for cohort in ['matched', 'unchanged']:
            for view_type, data, metric in classifiers:
                metric_id = 'partisan' if metric is None else metric['id']
                view = get('/api/trends?' + urlencode({'county': scope, 'cohort': cohort, 'view': view_type, 'metric': metric_id}))
                assert view['generated_at'] == snapshot['generated_at'], 'Snapshot changed during acceptance'
                for measure in ['daily', 'cumulative']:
                    for i in range(observed):
                        expected = [[0, 0, []] for _ in view['buckets']]
                        for county_id in selected:
                            ref = refs[county_id]
                            old = resolved[county_id][2024][measure][i]
                            new = resolved[county_id][2026][measure][i]
                            exact = {tuple(pair) for pair in ref['exact_pairs']}
                            for index, group in enumerate(ref['groups']):
                                if not match(group, old, new):
                                    continue
                                party = party_bucket(ref, group)
                                unchanged = len(group['old']) == len(group['new']) == 1 and (group['old'][0], group['new'][0]) in exact and party is not None
                                if cohort == 'unchanged' and not unchanged:
                                    continue
                                bucket = party if metric is None else demographic_bucket(data, metric, county_id, group)
                                if bucket is None:
                                    continue
                                expected[bucket][0] += sum(old[p] for p in group['old'])
                                expected[bucket][1] += sum(new[p] for p in group['new'])
                                expected[bucket][2].append(f'{county_id}:{index}')
                        for index, bucket in enumerate(view['buckets']):
                            row = bucket['days'][i]
                            a, b, ids = expected[index]
                            for year, value in [(2024, a), (2026, b)]:
                                actual = row[f'{measure}_{year}']
                                assert actual == (value if ids else None), ('Trend matched-subset mismatch', scope, cohort, metric_id, measure, i + 1, index, year, actual, value, len(ids))
                                trend_cells += 1
                            assert row[f'{measure}_groups'] == len(ids), ('Trend membership count mismatch', scope, cohort, metric_id, measure, i + 1, index)
                            expected_counties = len({identifier.split(':', 1)[0] for identifier in ids})
                            assert row[f'{measure}_counties'] == expected_counties
                            memberships += len(ids)
                for bucket in view['buckets'] + [view['totals']]:
                    for row in bucket['days'][observed:]:
                        assert row['daily_2026'] is None and row['cumulative_2026'] is None
                views += 1
    report = {
        'status': 'passed', 'base_url': BASE, 'snapshot_generated_at': snapshot['generated_at'],
        'reported_sources_checked': source_checks, 'matched_periods_checked': periods,
        'group_availability_checks': groups_checked, 'available_group_comparisons': groups_available,
        'unavailable_groups_excluded': missing_excluded, 'period_counts': period_counts,
        'county_calendar_cells': county_calendar_cells, 'matched_county_observations': matched_county_observations,
        'regression_summaries': regression_summaries, 'demographic_county_views': demographic_views, 'demographic_points': demographic_points,
        'trend_views': views, 'observed_trend_cells': trend_cells, 'matched_trend_memberships': memberships,
        'checks': ['explicit source presence versus independently complete-source zeros', 'cumulative precinct known on every contributing day', 'exact cumulative snapshots and adjacent differences', 'all common geography members required in both years', 'unavailable groups do not enter county totals', 'restored Tarrant/Harris/Collin/Fort Bend reported subsets', '134784 native Fort Bend observations with coverage caveats', 'daily and cumulative trend bucket reconstruction across all classifiers/cohorts', 'future current-cycle values remain unavailable'],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'matched-api-verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
