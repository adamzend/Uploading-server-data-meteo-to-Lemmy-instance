from datetime import datetime, timezone
import unittest
from unittest.mock import patch
from test_support import config

from publish_lemmy import START, END, merge_body, render_section


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.mock_config = patch("publish_lemmy.load_config", return_value=config())
        self.mock_config.start()
        self.addCleanup(self.mock_config.stop)
    def test_preserves_description(self):
        old = 'Opis użytkownika\n' + START + '\nstary pomiar\n' + END + '\nDalszy opis'
        self.assertEqual(merge_body(old, 'nowy pomiar'),
                         'Opis użytkownika\n' + START + '\n\nnowy pomiar\n\n' + END + '\nDalszy opis')

    def test_migrates_html_comments(self):
        text = 'Opis\n<!-- METEO:START -->\nstare\n<!-- METEO:END -->\nStopka'
        result = merge_body(text, 'nowe')
        self.assertEqual(result, 'Opis\n' + START + '\n\nnowe\n\n' + END + '\nStopka')
        self.assertNotIn('<!--', result)

    def test_refuses_missing_duplicate_and_reversed_markers(self):
        for text in ('opis bez znaczników', START + START + END, END + START):
            with self.assertRaises(ValueError):
                merge_body(text, 'nowe')

    def test_stale_measurement_and_failure_do_not_claim_healthy(self):
        status = {'status': 'ok', 'checked_at': '2026-10-13T00:00:00+00:00',
                  'last_success_at': '2026-10-13T00:00:00+00:00',
                  'values': {'temperature': 7.3, 'humidity': 95.1, 'pressure': 1020.3}}
        status['last_success_values'] = status['values']
        images = {name: {'url': '/fixture.png'}
                  for name in ('temperatura', 'wilgotnosc', 'cisnienie')}
        fresh = render_section(status, images, datetime(2026, 10, 13, 0, 5, tzinfo=timezone.utc))
        self.assertIn('🟢 Działa poprawnie', fresh)
        self.assertIn('7,3 °C', fresh)
        self.assertEqual(fresh.count('![',), 3)
        old = render_section(status, images, datetime(2026, 10, 13, 3, tzinfo=timezone.utc))
        self.assertIn('🔴 Błąd stacji', old)
        self.assertIn('ostatniego poprawnego pomiaru.', old)
        status.update(status='error', values=None)
        failed = render_section(status, images, datetime(2026, 10, 13, 0, 5, tzinfo=timezone.utc))
        self.assertIn('🔴 Błąd stacji', failed)
        self.assertIn('7,3 °C', failed)


if __name__ == '__main__':
    unittest.main()
