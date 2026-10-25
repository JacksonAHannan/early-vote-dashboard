"""Independent completed-data API acceptance; no downloads or cache mutations.

TURNOUT_TEST_URL=http://127.0.0.1:8743 python tests/completeness_api.py
"""
from __future__ import annotations

import hashlib
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
    with urlopen(BASE + path, timeout=90) as response:
        return json.load(response)


def close(actual, expected):
    return actual == expected or expected > 1 and abs(actual - expected) <= 1


def start(year):
    return date(year, 10, 21 if year == 2024 else 19)


def total(counts):
    assert all(isinstance(value, int) and value >= 0 for value in counts.values())
    return sum(counts.values())


def cumulative(sources, year, day):
    cutoff = (start(year) + timedelta(days=day - 1)).isoformat()
    direct = [source for source in sources if source['date'] == cutoff and source.get('cumulative', False)]
    assert len(direct) <= 1
    if direct:
        return direct[0]['counts']
    selected = [source for source in sources if not source.get('cumulative', False) and start(year).isoformat() <= source['date'] <= cutoff]
    if len(selected) != day or len({source['date'] for source in selected}) != day:
        return None
    counts = Counter()
    for source in selected:
        counts.update(source['counts'])
    return counts


def fit(points):
    if len(points) < 2 or len({x for x, _ in points}) < 2:
        return None
    mx = math.fsum(x for x, _ in points) / len(points)
    my = math.fsum(y for _, y in points) / len(points)
    slope = math.fsum((x - mx) * (y - my) for x, y in points) / math.fsum((x - mx) ** 2 for x, _ in points)
    intercept = my - slope * mx
    sst = math.fsum((y - my) ** 2 for _, y in points)
    r2 = 1 - math.fsum((y - intercept - slope * x) ** 2 for x, y in points) / sst if sst else None
    return {'slope': slope, 'intercept': intercept, 'r_squared': r2, 'x_min': min(x for x, _ in points), 'x_max': max(x for x, _ in points)}


def main():
    registry = get('/api/completeness')
    statewide = get('/api/statewide')
    snapshot = get('/api/data')
    demographic = get('/api/demographics')
    primary = get('/api/primary')
    assert registry['schema_version'] == snapshot['schema_version'] == 1
    assert len(snapshot.get('completeness_sha256', '')) == 64, 'Snapshot lacks its completion-registry identity; restart final QA binary'
    # Rust hashes its typed registry in declared field order; the JSON API may
    # reorder object keys. Recreate the wire content, including optional nulls.
    fields = ['county', 'year', 'date', 'daily', 'cumulative', 'source', 'sha256', 'retrieved_at', 'scope', 'completed', 'note', 'precinct_total', 'precinct_source', 'precinct_sha256']
    canonical = {'schema_version': registry['schema_version'], 'generated_at': registry['generated_at'], 'controls': [{key: row.get(key) for key in fields} for row in registry['controls']]}
    serialized = json.dumps(canonical, separators=(',', ':'), ensure_ascii=False).encode()
    assert snapshot['completeness_sha256'] == hashlib.sha256(serialized).hexdigest(), 'Snapshot/registry mismatch'
    controls = {}
    for control in registry['controls']:
        key = (control['county'], control['year'], control['date'])
        assert key not in controls
        assert date.fromisoformat(control['date']).year == control['year']
        assert len(control['sha256']) == 64 and control['source'] and control['retrieved_at']
        controls[key] = control

    def control(county, year, day):
        result = controls.get((county, year, (start(year) + timedelta(days=day - 1)).isoformat()))
        return result if result and result['completed'] and result['scope'] == 'in_person' else None

    through = date.fromisoformat(snapshot['through'])
    observed = (through - start(2026)).days + 1
    assert observed == snapshot['days'] and 1 <= observed <= 12
    assert statewide['through'] == snapshot['through']
    county_rows = {county['id']: county for county in statewide['counties']}
    assert len(county_rows) == 254
    statewide_cells = known_pairs = unknown_pairs = future_cells = 0
    for county in county_rows.values():
        assert len(county['days']) == 12
        for day in county['days']:
            i = day['day']
            assert day['date_2024'] == (start(2024) + timedelta(days=i - 1)).isoformat()
            assert day['date_2026'] == (start(2026) + timedelta(days=i - 1)).isoformat()
            for measure, field in [('votes', 'daily'), ('cumulative', 'cumulative')]:
                expected = {}
                for year in [2024, 2026]:
                    c = control(county['id'], year, i)
                    expected[year] = None if year == 2026 and i > observed else c[field] if c else None
                if i <= observed and any(value is None for value in expected.values()):
                    expected = {2024: None, 2026: None}
                for year in [2024, 2026]:
                    assert day[f'{measure}_{year}'] == expected[year], (county['id'], i, measure, year, day[f'{measure}_{year}'], expected[year])
                    statewide_cells += 1
                    if i > observed and year == 2026:
                        future_cells += 1
                if i <= observed:
                    if expected[2024] is None:
                        unknown_pairs += 1
                    else:
                        known_pairs += 1
    assert known_pairs and unknown_pairs and future_cells, 'Acceptance must exercise completed, unknown and future observations'
    # Native authoritative totals replace the specifically misleading SOS feed.
    assert observed >= 5
    for county, expected in [('fortbend', 134890), ('bexar', 222633), ('harris', 479409)]:
        assert county_rows[county]['days'][4]['cumulative_2026'] == expected
    assert county_rows['fortbend']['days'][4]['cumulative_2026'] != 90997
    assert county_rows['bexar']['days'][4]['cumulative_2026'] != 193507

    counties = {county['id']: county for county in snapshot['counties']}
    assert len(counties) == 215 and set(counties) <= set(county_rows)
    source_checks = periods = group_checks = 0
    available = defaultdict(dict)
    for county in counties.values():
        seen = set()
        for source in county['sources']:
            d = date.fromisoformat(source['date'])
            i = (d - start(d.year)).days + 1
            assert 1 <= i <= 12 and source['county'] == county['id']
            key = (source['date'], source.get('cumulative', False))
            assert key not in seen
            seen.add(key)
            c = control(county['id'], d.year, i)
            assert c is not None, ('unqualified source exposed', county['id'], source['date'])
            expected = c['cumulative' if source.get('cumulative', False) else 'daily']
            assert expected is not None and close(total(source['counts']), expected), (county['id'], source['date'], total(source['counts']), expected)
            source_checks += 1
        expected_days = set()
        for day in range(1, observed + 1):
            paired = {}
            for year in [2024, 2026]:
                counts = cumulative(county['sources'], year, day)
                c = control(county['id'], year, day)
                if counts is not None and c and (c['cumulative'] is None or close(total(counts), c['cumulative'])):
                    paired[year] = counts
            if len(paired) == 2:
                expected_days.add(day)
                available[county['id']][day] = paired
        assert {p['day'] for p in county['periods']} == expected_days, ('period qualification mismatch', county['id'])
        for period in county['periods']:
            periods += 1
            paired = available[county['id']][period['day']]
            assert period['county_2024'] == total(paired[2024]) and period['county_2026'] == total(paired[2026])
            assert period['through_2024'] == (start(2024) + timedelta(days=period['day'] - 1)).isoformat()
            assert period['through_2026'] == (start(2026) + timedelta(days=period['day'] - 1)).isoformat()
            for group in period['groups']:
                assert group['votes_2024'] == sum(paired[2024].get(precinct, 0) for precinct in group['old'])
                assert group['votes_2026'] == sum(paired[2026].get(precinct, 0) for precinct in group['new'])
                group_checks += 1
    assert periods and group_checks
    assert not counties['fortbend']['periods'] and not counties['bexar']['periods'], 'Incomplete precinct rosters must remain out of every precinct comparison'

    regression_checks = plotted_points = 0
    for summary in snapshot['regressions']:
        points = []
        omitted = 0
        for county in counties.values():
            if summary['county'] not in ('all', county['id']):
                continue
            period = next((p for p in county['periods'] if p['day'] == summary['day']), None)
            for group in period['groups'] if period else []:
                if not (group['unchanged'] if summary['cohort'] == 'unchanged' else group['bucket'] is not None):
                    continue
                omitted += group['votes_2024'] == 0
                if group['votes_2024'] > 0 and group['harris'] + group['trump'] > 0:
                    points.append((100 * group['harris'] / (group['harris'] + group['trump']), 100 * group['votes_2026'] / group['votes_2024']))
        assert summary['n'] == len(points) and summary['omitted_zero_baseline'] == omitted
        expected_fit = fit(points)
        if expected_fit is None:
            assert summary['fit'] is None
        else:
            assert summary['fit'] is not None
            for key, value in expected_fit.items():
                actual = summary['fit'][key]
                assert actual is None if value is None else actual is not None and math.isclose(actual, value, rel_tol=1e-9, abs_tol=1e-8), (summary['county'], summary['day'], key, actual, value)
        regression_checks += 1
        plotted_points += len(points)

    views = trend_cells = trend_known = 0
    classifiers = [('partisan', 'partisan'), ('primary', primary['metrics'][0]['id'])] + [('demographic', metric['id']) for metric in demographic['metrics']]
    assert len(classifiers) == 8
    for selected in ['all', 'travis', 'dallas', 'montgomery', 'bexar', 'fortbend']:
        for cohort in ['matched', 'unchanged']:
            for view_type, metric in classifiers:
                view = get('/api/trends?' + urlencode({'county': selected, 'cohort': cohort, 'view': view_type, 'metric': metric}))
                assert view['observed_days'] == observed and view['county'] == selected and view['cohort'] == cohort and view['metric'] == metric
                assert view['generated_at'] == snapshot['generated_at'], 'Snapshot changed during QA'
                for county_id in view['coverage']['included_counties']:
                    assert available[county_id], ('Unqualified county in trends', selected, metric, county_id)
                for bucket in view['buckets'] + [view['totals']]:
                    assert len(bucket['days']) == 12
                    for row in bucket['days']:
                        for measure in ['daily', 'cumulative']:
                            old, new = row[f'{measure}_2024'], row[f'{measure}_2026']
                            if row['day'] <= observed:
                                assert (old is None) == (new is None), ('Unpaired observed trend', selected, cohort, metric, bucket['id'], row['day'], measure)
                                trend_known += old is not None
                            else:
                                assert new is None, ('Invented future turnout', selected, metric, row['day'])
                            trend_cells += 2
                            if selected in ['bexar', 'fortbend'] and row['day'] <= observed:
                                assert old is None and new is None, ('Incomplete native precinct visual', selected, metric, row['day'])
                views += 1
    assert trend_known, 'At least one verified precinct timeline must remain populated'
    final_registry = get('/api/completeness')
    assert final_registry == registry, 'Completion controls changed during audit'
    report = {
        'status': 'passed',
        'base_url': BASE,
        'snapshot_generated_at': snapshot['generated_at'],
        'controls_generated_at': registry['generated_at'],
        'completeness_sha256': snapshot['completeness_sha256'],
        'registry_controls': len(controls),
        'county_calendar_cells': statewide_cells,
        'observed_known_pairs': known_pairs,
        'observed_unavailable_pairs': unknown_pairs,
        'future_2026_cells': future_cells,
        'qualified_precinct_sources': source_checks,
        'qualified_precinct_periods': periods,
        'qualified_group_comparisons': group_checks,
        'independently_checked_regressions': regression_checks,
        'qualified_regression_points_across_summaries': plotted_points,
        'trend_views': views,
        'trend_cells': trend_cells,
        'known_observed_trend_pairs': trend_known,
        'checks': ['all 254 county calendars against completed in-person control registry', 'observed pair masks for daily and cumulative totals', 'future current-cycle nulls with historical baseline preserved', 'native Fort Bend/Bexar/Harris control totals', 'all 215 geographic county source/period gates', 'prefix and exact-cutoff source reconciliation', 'native group vote reconstruction', 'every regression point count and OLS', '96 trend scope/cohort/classifier combinations', 'Bexar and Fort Bend unverified precinct comparisons withheld'],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'api-verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
