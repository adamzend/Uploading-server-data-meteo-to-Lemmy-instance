import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest
from unittest.mock import patch

import meteo

from test_support import config
CONFIG = config()


class FakeSocket:
    def __init__(self, response):
        self.response = response
        self.sent = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def settimeout(self, timeout):
        pass

    def sendall(self, request):
        self.sent = request

    def recv(self, size):
        # Simulate fragmented TCP replies.
        size = min(size, 2)
        data, self.response = self.response[:size], self.response[size:]
        return data


class CollectorTests(unittest.TestCase):
    def test_fragmented_response_and_read_only_request(self):
        response = struct.pack(">HHHBBB6H", 1, 0, 15, 8, 3, 12,
                               65481, 67, 0, 951, 0, 10202)
        fake = FakeSocket(response)
        with patch("meteo.socket.create_connection", return_value=fake):
            registers = meteo.read_registers(CONFIG["modbus"], 20, 6)
        self.assertEqual(fake.sent, struct.pack(">HHHBBHH", 1, 0, 6, 8, 3, 20, 6))
        values, _ = meteo.decode(registers, 20, CONFIG["sensors"])
        for key, expected in {"temperature": -5.5, "humidity": 95.1, "pressure": 1020.2}.items():
            self.assertAlmostEqual(values[key], expected)

    def test_modbus_exception(self):
        fake = FakeSocket(struct.pack(">HHHBBB", 1, 0, 3, 8, 0x83, 2))
        with patch("meteo.socket.create_connection", return_value=fake):
            with self.assertRaisesRegex(ValueError, "Wyjątek Modbus: 2"):
                meteo.read_registers(CONFIG["modbus"], 20, 6)

    def test_closed_connection(self):
        with self.assertRaises(OSError):
            meteo.read_exact(FakeSocket(b"\x00"), 7)

    def test_invalid_humidity(self):
        with self.assertRaisesRegex(ValueError, "humidity"):
            meteo.decode((73, 0, 0, 1001, 0, 10202), 20, CONFIG["sensors"])

    def test_failure_retries_and_preserves_last_good(self):
        with patch("meteo.read_registers", side_effect=TimeoutError("test timeout")) as reader:
            with patch("meteo.time.sleep"):
                checked_at, values, raw, attempts, error = meteo.collect(CONFIG)
        self.assertEqual(reader.call_count, 3)
        self.assertIsNone(values)
        with tempfile.TemporaryDirectory(dir=meteo.BASE) as temporary:
            db = Path(temporary) / "test.sqlite3"
            good_time = "2026-10-12T10:00:00+00:00"
            meteo.save_result(db, good_time,
                              {"temperature": 7.3, "humidity": 95.1, "pressure": 1020.2},
                              {}, 1, None)
            last_good = meteo.save_result(db, checked_at, values, raw, attempts, error)
            status = meteo.write_status(Path(temporary) / "status.json", checked_at,
                                        values, last_good, CONFIG["timezone"])
            self.assertEqual(status["status"], "error")
            self.assertIsNone(status["values"])
            self.assertEqual(status["last_success_at"], good_time)
            with sqlite3.connect(db) as connection:
                self.assertEqual(connection.execute(
                    "SELECT temperature_c,humidity_percent,pressure_hpa FROM readings WHERE status='error'"
                ).fetchone(), (None, None, None))


if __name__ == "__main__":
    unittest.main()
