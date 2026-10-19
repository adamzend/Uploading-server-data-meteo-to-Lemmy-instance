import unittest
import itertools
from unittest.mock import patch
from datetime import datetime, timezone
import meteo
import settings
from test_support import config
from publish_lemmy import render_section

class FreshnessTests(unittest.TestCase):
    def setUp(self):
        self.c = config()
        self.c['heartbeat'].update(enabled=True, address=100, timeout_seconds=10, poll_interval_seconds=1)

    def test_changed_and_wrapped_counter(self):
        for values in [(5, 6), (65535, 0)]:
            with patch('meteo.read_registers', side_effect=[(v,) for v in values]), patch('meteo.time.sleep'):
                self.assertTrue(meteo.verify_freshness(self.c))

    def test_stuck_counter(self):
        with patch('meteo.time.monotonic', side_effect=itertools.count(0, 2)), patch('meteo.time.sleep'), patch('meteo.read_registers', return_value=(7,)):
            with self.assertRaises(meteo.FreshnessError):
                meteo.verify_freshness(self.c)

    def test_diagnostic_guard(self):
        self.c['heartbeat']['checks'] = [{'address': 101, 'allowed_values': [1]}]
        with patch('meteo.read_registers', return_value=(0,)):
            with self.assertRaises(meteo.FreshnessError):
                meteo.verify_freshness(self.c)

    def test_disabled_needs_no_reads(self):
        self.c.pop('heartbeat')
        with patch('meteo.read_registers') as reader:
            self.assertFalse(meteo.verify_freshness(self.c))
            reader.assert_not_called()

    def test_failure_does_not_read_measurements(self):
        with patch('meteo.verify_freshness', side_effect=meteo.FreshnessError('stale')), patch('meteo.read_registers') as reader:
            self.assertIsNone(meteo.collect_fast(self.c)[1])
            reader.assert_not_called()

    def test_recovery_stops_after_success(self):
        bad = ('time', None, None, 3, 'timeout')
        good = ('time', {'temperature': 1}, {}, 1, None)
        with patch('meteo.collect_fast', side_effect=[bad, good]) as collect, patch('meteo.time.sleep'):
            result = meteo.collect(self.c)
            self.assertEqual(result[3], 4)
            self.assertEqual(collect.call_count, 2)

    def test_recovery_is_bounded(self):
        self.c['recovery']['attempts'] = 2
        with patch('meteo.collect_fast', return_value=('time', None, None, 1, 'timeout')) as collect, patch('meteo.time.sleep'):
            self.assertEqual(meteo.collect(self.c)[3], 3)
            self.assertEqual(collect.call_count, 3)

    def test_configuration_validation(self):
        settings.validate(self.c)
        for address in [None, -1, 65536, True]:
            self.c['heartbeat']['address'] = address
            with self.assertRaises(ValueError):
                settings.validate(self.c)

    def test_no_green_without_verified_heartbeat(self):
        status = {'status': 'ok', 'checked_at': '2026-10-19T12:00:00+00:00',
                  'values': {'temperature': 8, 'humidity': 72, 'pressure': 1032}}
        images = {name: {'url': '/fixture.png'} for name in ('temperatura', 'wilgotnosc', 'cisnienie')}
        now = datetime(2026, 10, 19, 12, 1, tzinfo=timezone.utc)
        self.assertNotIn('🟢', render_section(status, images, now, self.c))
        status['freshness_verified'] = True
        self.assertIn('🟢', render_section(status, images, now, self.c))
