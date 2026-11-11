"""Kiểm tra nhánh HTTP 429 của live tools bằng mock, không gọi mạng."""
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bonus.tools import BonusTools


class LiveRateLimitTests(unittest.TestCase):
    def test_429_blocks_status_and_details_for_same_provider(self):
        headers_to_test = (
            {'Retry-After': '2'},
            {'Retry-After': 'Thu, 12 Nov 2026 08:00:00 GMT'},
            {},
        )
        for headers in headers_to_test:
            with self.subTest(headers=headers):
                tools = BonusTools(mode='live')
                error = urllib.error.HTTPError(
                    'https://example.invalid',
                    429, 'rate limited', headers, io.BytesIO(b''),
                )
                try:
                    with patch(
                        'bonus.tools.urllib.request.urlopen',
                        side_effect=error,
                    ) as request:
                        first = tools.execute('get_vercel_status', {})
                        again = tools.execute(
                            'get_vercel_status',
                            {'component': 'Builds'},
                        )
                        details = tools.execute(
                            'get_incident_details',
                            {
                                'provider': 'vercel',
                                'incident_id': 'example',
                            },
                        )
                    self.assertEqual(request.call_count, 1)
                    self.assertEqual(first['error'], 'RATE_LIMITED')
                    self.assertEqual(first['http_status'], 429)
                    self.assertEqual(
                        first['retry_after'], headers.get('Retry-After')
                    )
                    self.assertFalse(first['retriable'])
                    self.assertTrue(again['request_skipped'])
                    self.assertTrue(details['request_skipped'])
                finally:
                    error.close()

    def test_other_provider_still_works_after_429(self):
        tools = BonusTools(mode='live')
        error = urllib.error.HTTPError(
            'https://example.invalid',
            429, 'rate limited', {'Retry-After': '30'},
            io.BytesIO(b''),
        )
        try:
            with patch(
                'bonus.tools.urllib.request.urlopen',
                side_effect=error,
            ):
                tools.execute('get_vercel_status', {})
        finally:
            error.close()

        snapshot = json.loads(
            (ROOT / 'fixtures/github.json').read_text(encoding='utf-8')
        )
        with patch.object(tools, '_load', return_value=snapshot) as load:
            result = tools.execute('get_github_status', {})

        load.assert_called_once_with('github')
        self.assertEqual(result['provider'], 'github')
        self.assertIn('indicator', result['overall'])


if __name__ == '__main__':
    unittest.main()