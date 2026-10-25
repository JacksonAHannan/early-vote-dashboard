"""Georgia aggregate semantics and reconciliation; no network calls."""
import collections
import importlib.util
import json
import io
from pathlib import Path
import unittest
import types
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
        with patch.object(ga.urllib.request, 'urlopen', side_effect=failure), patch.object(ga.Archive, 'save') as save, patch.object(ga, 'compatible_request', side_effect=RuntimeError('fixture denied')):
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
        with patch.object(ga.Archive, 'get', side_effect=configuration), patch.object(ga.urllib.request, 'urlopen', side_effect=failure), patch.object(ga, 'compatible_request', side_effect=RuntimeError('fixture denied')):
            with self.assertRaisesRegex(RuntimeError, 'SOS anonymous read session.*HTTP 403.*qlik-oauth-create-user'):
                ga.collect('2026-10-23')

    def test_compatible_transport_is_bounded_and_retains_the_original_request(self):
        url = ga.HUB + '/shared-config.js'
        headers = {'User-Agent': 'TurnoutResearch/1.0', 'Accept': 'application/javascript'}
        for status in (403, 429, 500, 502, 503):
            failure = HTTPError(url, status, 'fixture', {}, io.BytesIO())
            with patch.object(ga.urllib.request, 'urlopen', side_effect=failure), patch.object(ga, 'compatible_request', return_value=b'public bytes') as fallback:
                self.assertEqual(ga.request_bytes(url, 'host config', headers), b'public bytes')
                fallback.assert_called_once_with(url, headers)
        for status in (400, 401, 404):
            failure = HTTPError(url, status, 'fixture', {}, io.BytesIO())
            with patch.object(ga.urllib.request, 'urlopen', side_effect=failure), patch.object(ga, 'compatible_request') as fallback:
                with self.assertRaises(RuntimeError):
                    ga.request_bytes(url, 'host config', headers)
                fallback.assert_not_called()
        with patch.object(ga.urllib.request, 'urlopen', return_value=io.BytesIO(b'direct success')), patch.object(ga, 'compatible_request') as fallback:
            self.assertEqual(ga.request_bytes(url, 'host config', headers), b'direct success')
            fallback.assert_not_called()

    def test_compatible_transport_uses_only_pipes_and_does_not_echo_failure_payloads(self):
        url = ga.HUB + '/qlik-oauth-create-user?access_token=fixture-private-query'
        headers = {'Authorization': 'Bearer fixture-private-header'}
        result = types.SimpleNamespace(returncode=0, stdout=b'{"access_token":"fixture-private-response"}')
        with patch.object(ga.subprocess, 'run', return_value=result) as run:
            self.assertEqual(ga.compatible_request(url, headers), result.stdout)
        args, options = run.call_args
        self.assertEqual(args[0][:2], ['uv', 'run'])
        self.assertEqual(json.loads(options['input']), {'url': url, 'headers': headers})
        self.assertEqual(options['stdout'], ga.subprocess.PIPE)
        self.assertEqual(options['stderr'], ga.subprocess.PIPE)
        failure = HTTPError(url, 403, 'Forbidden', {}, io.BytesIO())
        result = types.SimpleNamespace(returncode=1, stdout=b'fixture-private-response', stderr=b'fixture-private-query fixture-private-header')
        with patch.object(ga.urllib.request, 'urlopen', side_effect=failure), patch.object(ga.subprocess, 'run', return_value=result):
            with self.assertRaises(RuntimeError) as raised:
                ga.request_bytes(url, 'anonymous session', headers)
        self.assertIn('HTTP 403', str(raised.exception))
        self.assertNotIn('fixture-private', str(raised.exception))
        self.assertNotIn('access_token', str(raised.exception))

    def test_public_browser_transport_is_host_limited_and_preserves_headers(self):
        spec = importlib.util.spec_from_file_location('public_transport', ROOT / 'dashboard/scripts/transport.py')
        transport = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(transport)
        self.assertTrue(transport.needs_browser(ga.HUB + '/shared-config.js', 403))
        self.assertFalse(transport.needs_browser(ga.HUB + '/shared-config.js', 401))
        self.assertFalse(transport.needs_browser('https://d11khjvhu86vzz.cloudfront.net.evil.test/', 403))
        self.assertFalse(transport.needs_browser('https://example.org/', 403))
        self.assertTrue(transport.needs_browser('https://www.dallascountyvotes.org/public/', 202))
        headers = {'Accept': 'application/json'}
        response = types.SimpleNamespace(status_code=200, content=b'public bytes', raise_for_status=lambda: None)
        session = unittest.mock.MagicMock()
        session.__enter__.return_value.get.return_value = response
        requests = types.SimpleNamespace(Session=lambda **kwargs: session)
        with patch.dict('sys.modules', {'curl_cffi': types.SimpleNamespace(requests=requests)}):
            self.assertEqual(transport.download({'url': ga.HUB + '/shared-config.js', 'headers': headers}), b'public bytes')
        session.__enter__.return_value.get.assert_called_once_with(ga.HUB + '/shared-config.js', headers=headers, timeout=120)
        # Persistent curl 403 uses a normal browser only for the allowed host,
        # retaining the same public endpoint and requested headers.
        response.status_code = 403
        browser = unittest.mock.MagicMock()
        context = browser.new_context.return_value
        page = context.new_page.return_value
        page.goto.return_value.ok = True
        page.goto.return_value.body.return_value = b'browser public bytes'
        manager = unittest.mock.MagicMock()
        manager.__enter__.return_value.chromium.launch.return_value = browser
        sync_api = types.SimpleNamespace(sync_playwright=lambda: manager)
        with patch.dict('sys.modules', {'curl_cffi': types.SimpleNamespace(requests=requests), 'playwright': types.SimpleNamespace(sync_api=sync_api), 'playwright.sync_api': sync_api}):
            self.assertEqual(transport.download({'url': ga.HUB + '/shared-config.js', 'headers': headers}), b'browser public bytes')
        browser.new_context.assert_called_once_with(extra_http_headers=headers)
        page.goto.assert_called_once_with(ga.HUB + '/shared-config.js', wait_until='domcontentloaded', timeout=60000)
        browser.close.assert_called_once()

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
