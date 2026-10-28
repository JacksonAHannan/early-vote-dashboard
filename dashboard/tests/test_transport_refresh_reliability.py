"""Hourly refresh must survive transient official transport failures; fake bytes only."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
spec = importlib.util.spec_from_file_location('refresh_transport', SCRIPTS / 'transport.py')
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)


class TransportRefresh(unittest.TestCase):
    def request(self, effects, form=None):
        session = MagicMock()
        active = session.__enter__.return_value
        call = active.post if form else active.get
        call.side_effect = effects
        failure = type('FakeRequestsError', (Exception,), {})
        requests = types.SimpleNamespace(Session=lambda **kwargs: session, RequestsError=failure)
        return session, active, requests, failure

    def response(self, status, content=b'newly posted next-day report'):
        response = types.SimpleNamespace(status_code=status, content=content)
        def raise_for_status():
            if status >= 400:
                raise RuntimeError('synthetic HTTP failure')
        response.raise_for_status = raise_for_status
        return response

    def test_gateway_and_rate_limit_retry_the_exact_get_or_post(self):
        for status in (429, 500, 502, 503, 504):
            for form in (None, {'date': '10/28/2026'}):
                with self.subTest(status=status, form=form):
                    session, active, requests, _ = self.request([self.response(status), self.response(200)], form)
                    request = {'url': 'https://official.example/roster', 'headers': {'Accept': 'text/csv'}, 'form': form}
                    with patch.dict(sys.modules, {'curl_cffi': types.SimpleNamespace(requests=requests)}), patch.object(transport, 'sleep', create=True):
                        self.assertEqual(transport.download(request), b'newly posted next-day report')
                    call = active.post if form else active.get
                    self.assertEqual(call.call_count, 2)
                    self.assertEqual(call.call_args_list[0], call.call_args_list[1])

    def test_body_timeout_retries_without_returning_partial_bytes(self):
        session, active, requests, failure = self.request([])
        active.get.side_effect = [failure('synthetic interrupted body'), self.response(200)]
        with patch.dict(sys.modules, {'curl_cffi': types.SimpleNamespace(requests=requests)}), patch.object(transport, 'sleep', create=True):
            self.assertEqual(transport.download({'url': 'https://official.example/roster'}), b'newly posted next-day report')
        self.assertEqual(active.get.call_count, 2)

    def test_hard_errors_and_not_ready_are_not_retried(self):
        for status in (202, 400, 401, 403, 404):
            session, active, requests, _ = self.request([self.response(status)])
            with patch.dict(sys.modules, {'curl_cffi': types.SimpleNamespace(requests=requests)}):
                with self.assertRaises(RuntimeError):
                    transport.download({'url': 'https://official.example/roster'})
            self.assertEqual(active.get.call_count, 1)

    def test_exhaustion_is_bounded(self):
        session, active, requests, _ = self.request([self.response(502)] * 2)
        with patch.dict(sys.modules, {'curl_cffi': types.SimpleNamespace(requests=requests)}), patch.object(transport, 'sleep', create=True):
            with self.assertRaises(RuntimeError):
                transport.download({'url': 'https://official.example/roster'})
        self.assertEqual(active.get.call_count, 2)


if __name__ == '__main__':
    unittest.main()
