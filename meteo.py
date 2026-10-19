#!/usr/bin/env python3
"""Read-only Modbus TCP weather collector. Python standard library only."""
import argparse
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
from pathlib import Path
import socket
import sqlite3
import struct
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from settings import load as load_config

BASE = Path(__file__).resolve().parent
FIELDS = ("temperature", "humidity", "pressure")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_exact(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise OSError("Urządzenie zamknęło połączenie przed końcem odpowiedzi")
        data.extend(chunk)
    return bytes(data)


def read_registers(settings, start, count):
    unit = settings["unit_id"]
    function = settings["function_code"]
    request = struct.pack(">HHHBBHH", 1, 0, 6, unit, function, start, count)
    with socket.create_connection(
        (settings["host"], settings["port"]), timeout=settings["timeout_seconds"]
    ) as sock:
        sock.settimeout(settings["timeout_seconds"])
        sock.sendall(request)
        transaction, protocol, length, response_unit = struct.unpack(
            ">HHHB", read_exact(sock, 7)
        )
        if (transaction, protocol, response_unit) != (1, 0, unit):
            raise ValueError("Nieprawidłowy nagłówek odpowiedzi Modbus")
        if not 2 <= length <= 254:
            raise ValueError("Nieprawidłowa długość odpowiedzi Modbus")
        payload = read_exact(sock, length - 1)
        if payload[0] == (function | 0x80):
            code = payload[1] if len(payload) > 1 else "brak kodu"
            raise ValueError(f"Wyjątek Modbus: {code}")
        if len(payload) != 2 + count * 2 or payload[:2] != bytes((function, count * 2)):
            raise ValueError("Nieprawidłowa funkcja lub liczba bajtów Modbus")
        return struct.unpack(">" + "H" * count, payload[2:])


def decode(registers, start, sensors):
    values, raw = {}, {}
    for name in FIELDS:
        sensor = sensors[name]
        number = registers[sensor["address"] - start]
        raw[name] = number
        if sensor["signed"] and number >= 32768:
            number -= 65536
        value = number * sensor["multiplier"] + sensor["offset"]
        if not math.isfinite(value) or not sensor["min"] <= value <= sensor["max"]:
            raise ValueError(f"{name}: wynik {value} poza zakresem konfiguracji")
        values[name] = value
    return values, raw


class FreshnessError(ValueError):
    """The station is reachable but its source data is not confirmed fresh."""


def verify_freshness(config):
    h = config.get('heartbeat', {})
    if not h.get('enabled', False):
        return False
    deadline = time.monotonic() + h['timeout_seconds']
    settings = dict(config['modbus'])

    def read(address):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FreshnessError('Heartbeat: brak zmiany licznika w wymaganym czasie')
        settings['timeout_seconds'] = min(config['modbus']['timeout_seconds'], remaining)
        return read_registers(settings, address, 1)[0]

    def snapshot():
        for check in h.get('checks', []):
            value = read(check['address'])
            if value not in check['allowed_values']:
                raise FreshnessError('Heartbeat: nieprawidłowy stan diagnostyczny źródła')
        return read(h['address'])

    previous = snapshot()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FreshnessError('Heartbeat: brak zmiany licznika w wymaganym czasie')
        time.sleep(min(h['poll_interval_seconds'], remaining))
        current = snapshot()
        if time.monotonic() <= deadline and current != previous:
            return True


def collect(config):
    result = collect_fast(config)
    total = result[3]
    recovery = config.get('recovery', {'attempts': 5, 'delay_seconds': 60})
    for _ in range(recovery['attempts']):
        if result[1] is not None:
            break
        time.sleep(recovery['delay_seconds'])
        retry_config = dict(config, modbus=dict(config['modbus'], attempts=1))
        result = collect_fast(retry_config)
        total += result[3]
    return result[:3] + (total, result[4])


def collect_fast(config):
    settings = config["modbus"]
    attempts = settings["attempts"]
    if not 1 <= attempts <= 10:
        raise ValueError("Liczba prób musi wynosić od 1 do 10")
    for attempt in range(1, attempts + 1):
        try:
            verify_freshness(config)
            # Read only configured registers, including widely separated addresses.
            registers = {}
            for name in FIELDS:
                address = config['sensors'][name]['address']
                if address not in registers:
                    registers[address] = read_registers(settings, address, 1)[0]
            values, raw = decode(registers, 0, config['sensors'])
            return utc_now(), values, raw, attempt, None
        except FreshnessError as exc:
            return utc_now(), None, None, attempt, str(exc)
        except (OSError, ValueError) as exc:
            logging.warning("Próba %s/%s: %s", attempt, attempts, exc)
            if attempt < attempts:
                time.sleep(settings["retry_delay_seconds"])
            else:
                return utc_now(), None, None, attempt, str(exc)


def save_result(db_path, checked_at, values, raw, attempts, error):
    with sqlite3.connect(db_path, timeout=10) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY,
            checked_at TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('ok', 'error')),
            temperature_c REAL, humidity_percent REAL, pressure_hpa REAL,
            raw_json TEXT, attempts INTEGER NOT NULL, error TEXT
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS readings_time ON readings(checked_at)")
        db.execute("""INSERT INTO readings
            (checked_at,status,temperature_c,humidity_percent,pressure_hpa,raw_json,attempts,error)
            VALUES (?,?,?,?,?,?,?,?)""", (
                checked_at, "ok" if values is not None else "error",
                *((values[name] if values is not None else None) for name in FIELDS),
                json.dumps(raw) if raw is not None else None, attempts, error
            ))
        last_good = db.execute("""SELECT checked_at,temperature_c,humidity_percent,pressure_hpa
            FROM readings WHERE status='ok' ORDER BY id DESC LIMIT 1""").fetchone()
    return last_good


def write_status(path, checked_at, values, last_good, local_timezone, error=None, heartbeat_enabled=False):
    status = {
        "error": error,
        "heartbeat_enabled": heartbeat_enabled,
        "freshness_verified": heartbeat_enabled and values is not None,
        "status": "ok" if values is not None else "error",
        "label": "Działa poprawnie" if values is not None else "Błąd stacji",
        "checked_at": checked_at,
        "checked_at_local": datetime.fromisoformat(checked_at).astimezone(
            ZoneInfo(local_timezone)).isoformat(),
        "values": values,
        "last_success_at": last_good[0] if last_good else None,
        "last_success_values": dict(zip(FIELDS, last_good[1:])) if last_good else None,
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return status


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true", help="Log to file without terminal output")
    args = parser.parse_args()
    (BASE / "data").mkdir(exist_ok=True)
    (BASE / "logs").mkdir(exist_ok=True)
    handler = RotatingFileHandler(BASE / "logs/meteo.log", maxBytes=2_000_000,
                                  backupCount=5, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(message)s")
    with (BASE / "data/meteo.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logging.info("Poprzedni odczyt jeszcze trwa; pomijam uruchomienie")
            return 0
        try:
            config = load_config()
            ZoneInfo(config["timezone"])
            checked_at, values, raw, attempts, error = collect(config)
            last_good = save_result(BASE / "data/meteo.sqlite3", checked_at,
                                    values, raw, attempts, error)
            status = write_status(BASE / "data/status.json", checked_at,
                                  values, last_good, config["timezone"], error,
                                  config.get("heartbeat", {}).get("enabled", False))
            if values is not None:
                logging.info("Pomiar: temperatura=%s °C; wilgotność=%s %%; ciśnienie=%s hPa",
                             values["temperature"], values["humidity"], values["pressure"])
            else:
                logging.error("Błąd stacji: %s", error)
            if not args.quiet:
                print(json.dumps(status, ensure_ascii=False, indent=2))
            return 0 if values is not None else 1
        except Exception:
            logging.exception("Błąd programu lub zapisu danych")
            if not args.quiet:
                print("Błąd programu. Szczegóły: " + str(BASE / "logs/meteo.log"), file=sys.stderr)
            return 2


if __name__ == "__main__":
    sys.exit(main())
