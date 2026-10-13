from datetime import datetime, timezone
import math
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from unittest.mock import patch
from test_support import config
import charts
import meteo


class ChartTests(unittest.TestCase):
    def setUp(self):
        self.mock_config = patch("charts.load_config", return_value=config())
        self.mock_config.start()
        self.addCleanup(self.mock_config.stop)
    def test_month_bounds_dst_leap_and_year_end(self):
        tz = ZoneInfo('Europe/Warsaw')
        start, end = charts.month_bounds(2026, 10, tz)
        self.assertEqual(start.astimezone(timezone.utc).isoformat(), '2026-09-30T22:00:00+00:00')
        self.assertEqual(end.astimezone(timezone.utc).isoformat(), '2026-10-31T23:00:00+00:00')
        self.assertEqual((charts.month_bounds(2024, 2, tz)[1] - charts.month_bounds(2024, 2, tz)[0]).days, 29)
        self.assertEqual(charts.month_bounds(2026, 12, tz)[1].year, 2027)

    def test_gaps_and_failed_readings(self):
        rows = [('2026-10-12T10:00:00+00:00', 'ok', 7.0),
                ('2026-10-12T11:00:00+00:00', 'error', None),
                ('2026-10-12T12:00:00+00:00', 'ok', 8.0),
                ('2026-10-12T15:00:00+00:00', 'ok', 9.0)]
        x, y = charts.series(rows, 2, ZoneInfo('Europe/Warsaw'))
        self.assertEqual(len(y), 5)
        self.assertTrue(math.isnan(y[1]))
        self.assertTrue(math.isnan(y[3]))
        self.assertEqual([v for v in y if math.isfinite(v)], [7, 8, 9])

    def test_local_month_selection_and_future_exclusion(self):
        with tempfile.TemporaryDirectory() as temporary:
            db = Path(temporary) / 'test.sqlite3'
            for stamp in ['2026-09-30T21:59:59+00:00', '2026-09-30T22:00:00+00:00',
                          '2026-10-12T10:00:00+00:00', '2026-10-31T23:00:00+00:00']:
                meteo.save_result(db, stamp, {'temperature': 7, 'humidity': 90, 'pressure': 1010}, {}, 1, None)
            tz = ZoneInfo('Europe/Warsaw')
            start, end = charts.month_bounds(2026, 10, tz)
            rows = charts.load_rows(db, start, end, datetime(2026, 10, 10, tzinfo=tz))
            self.assertEqual([row[0] for row in rows], ['2026-09-30T22:00:00+00:00'])

    def test_render_empty_and_single_reading(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / 'test.sqlite3'
            meteo.save_result(db, '2026-10-12T10:00:00+00:00',
                {'temperature': -5, 'humidity': 100, 'pressure': 1010}, {}, 1, None)
            for month, expected in [('2026-09', 0), ('2026-10', 1)]:
                output = root / month
                manifest = charts.generate(month, db_path=db, output=output,
                    now=datetime(2026, 10, 12, 12, tzinfo=timezone.utc))
                for chart in manifest['charts'].values():
                    self.assertEqual(chart['count'], expected)
                    with Image.open(output / chart['file']) as img:
                        self.assertEqual(img.size, (1680, 945))
                        img.verify()


if __name__ == '__main__':
    unittest.main()
