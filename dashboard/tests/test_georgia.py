"""Georgia aggregate semantics and reconciliation; no network calls."""
import collections
import importlib.util
import json
import io
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('georgia', ROOT / 'dashboard/scripts/states/georgia.py')
ga = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ga)


def fixture(entries):
    return {'pages': [{'qMatrix': [[{'qText': value} for value in dims] + [{'qNum': count}]
                                 for dims, count in entries]}]}


class GeorgiaTests(unittest.TestCase):
    def test_acceptance_dates_methods_preopening_mail_and_known_zeros(self):
        counties = {'APPLING': {'id': '13001', 'name': 'Appling'},
                    'ATKINSON': {'id': '13003', 'name': 'Atkinson'}}
        base = fixture([
            (['APPLING', '10/12/2026', 'Absentee by mail'], 4),
            (['APPLING', '10/13/2026', 'Early In-Person'], 10),
            (['APPLING', '10/13/2026', 'Electronic Ballot Delivery'], 2),
            (['APPLING', '10/14/2026', 'Early In-Person'], 20),
            (['APPLING', '10/15/2026', 'Early In-Person'], 30),
            (['APPLING', '10/13/2026', 'Election Day'], 100),
            (['APPLING', '10/13/1926', 'Absentee by mail'], 99),
        ])
        race = fixture([(dims + ['White'], count)
                        for dims, count in ga.rows(base)])
        result = ga.normalize(2026, counties, base, {'race': race}, '2026-10-14')
        lookup = {(row['county'], row['date'], row['method'], row['measure']): row for row in result}
        self.assertEqual(len(result), 24)
        self.assertEqual(lookup['13001', '2026-10-13', 'total', 'daily']['votes'], 12)
        self.assertEqual(lookup['13001', '2026-10-13', 'total', 'cumulative']['votes'], 16)
        self.assertEqual(lookup['13001', '2026-10-14', 'total', 'cumulative']['votes'], 36)
        self.assertEqual(lookup['13003', '2026-10-14', 'total', 'daily']['breakdowns']['race']['White'], 0)
        self.assertTrue(all(row['date'] <= '2026-10-14' for row in result))

    def test_archived_http_failure_identifies_boundary_without_query_credentials(self):
        url = ga.HUB + '/shared-config.js?access_token=fixture-private-value'
        failure = HTTPError(url, 403, 'Forbidden', {}, io.BytesIO())
        with patch.object(ga.urllib.request, 'urlopen', side_effect=failure), patch.object(ga.Archive, 'save') as save:
            with self.assertRaises(RuntimeError) as raised:
                ga.Archive().get(url, 'SOS host configuration', 'js')
        message = str(raised.exception)
        self.assertIn('SOS host configuration', message)
        self.assertIn('HTTP 403', message)
        self.assertIn(ga.HUB + '/shared-config.js', message)
        self.assertNotIn('fixture-private-value', message)
        self.assertNotIn('access_token', message)
        save.assert_not_called()

    def test_public_session_http_failure_identifies_the_actual_collect_boundary(self):
        failure = HTTPError(ga.HUB + '/qlik-oauth-create-user', 403, 'Forbidden', {}, io.BytesIO())
        configuration = [b'var tenant = "https://example.qlikcloud.com";', b'var appId = "fixture-app";']
        with patch.object(ga.Archive, 'get', side_effect=configuration), patch.object(ga.urllib.request, 'urlopen', side_effect=failure):
            with self.assertRaisesRegex(RuntimeError, 'SOS anonymous read session.*HTTP 403.*qlik-oauth-create-user'):
                ga.collect('2026-10-23')

    def test_public_session_credentials_are_passed_only_in_memory(self):
        configuration = [b'var tenant = "https://example.qlikcloud.com";', b'var appId = "fixture-app";']
        token = 'fixture-private-session'
        body = io.BytesIO(json.dumps({'access_token': token}).encode())
        with patch.object(ga.Archive, 'get', side_effect=configuration), patch.object(ga.Archive, 'save') as save, patch.object(ga.urllib.request, 'urlopen', return_value=body), patch.object(ga, 'QlikSocket', side_effect=InterruptedError('stop after credential handoff')) as connect:
            with self.assertRaisesRegex(InterruptedError, 'stop after credential handoff'):
                ga.collect('2026-10-23')
        connect.assert_called_once_with('wss://example.qlikcloud.com/app/fixture-app', token)
        save.assert_not_called()

    def test_invalid_and_fractional_counts_are_rejected(self):
        for count in [-1, 0.5, float('nan'), '100']:
            with self.assertRaises(ValueError):
                ga.integer(count)

    def test_age_bounds_match_official_display(self):
        self.assertEqual(ga.category('age', '35-40'), '35-39')
        self.assertEqual(ga.category('age', '18-24'), '18-24')
        self.assertEqual(ga.category('race', '-'), 'Unknown')
        self.assertEqual(ga.category('race', 'Other/Unknown'), 'Other/Unknown')

    def test_actual_archived_source_reconciliation(self):
        path = ROOT / 'dashboard/data/states/ga.json'
        if not path.exists():
            self.skipTest('Run the Georgia collector once for actual-source verification')
        data = json.loads(path.read_text())
        counties = data['counties']
        self.assertEqual(len(counties), 159)
        self.assertEqual(sum(row['harris'] for row in counties), 2548017)
        self.assertEqual(sum(row['trump'] for row in counties), 2663117)
        cubes = 0
        for source in data['sources']:
            if 'dimensions' not in source:
                continue
            raw = json.loads((ROOT / source['path']).read_text())
            self.assertEqual(sum(count for _, count in ga.rows(raw)), raw['total'])
            cubes += 1
        self.assertEqual(cubes, 8)
        groups = collections.defaultdict(dict)
        for row in data['observations']:
            for kind in ('race', 'sex', 'age'):
                self.assertEqual(sum(row['breakdowns'][kind].values()), row['votes'])
            groups[row['year'], row['county'], row['date'], row['measure']][row['method']] = row
            if row['year'] == 2026:
                self.assertLessEqual(row['date'], data['through'])
        for key, methods in groups.items():
            self.assertEqual(methods['total']['votes'], methods['in_person']['votes'] + methods['mail']['votes'])
        lookup = {(r['year'], r['county'], r['date'], r['method'], r['measure']): r['votes']
                  for r in data['observations']}
        for row in data['observations']:
            if row['measure'] != 'cumulative' or row['date'] == data['start_dates'][str(row['year'])]:
                continue
            previous = (ga.dt.date.fromisoformat(row['date']) - ga.dt.timedelta(days=1)).isoformat()
            prefix = lookup[row['year'], row['county'], previous, row['method'], 'cumulative']
            daily = lookup[row['year'], row['county'], row['date'], row['method'], 'daily']
            self.assertEqual(row['votes'], prefix + daily)


if __name__ == '__main__':
    unittest.main()
