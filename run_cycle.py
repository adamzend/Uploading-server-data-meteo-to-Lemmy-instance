#!/usr/bin/env python3
"""Scheduled measurement followed by charts, including after a failed reading."""
import fcntl
import logging
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent


def main():
    os.umask(0o077)
    (BASE / 'data').mkdir(exist_ok=True)
    with (BASE / 'data/cycle.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        import meteo
        result = meteo.main()
        try:
            from charts import generate
            manifest = generate()
            logging.info('Wygenerowano 3 wykresy dla miesiąca %s', manifest['month'])
        except Exception:
            logging.exception('Nie udało się wygenerować wykresów')
            return 3
        if result != 2:
            try:
                from publish_lemmy import publish
                publish()
            except Exception:
                logging.exception('Nie udało się zaktualizować wpisu Lemmy')
                return 4
        return result


if __name__ == '__main__':
    sys.exit(main())
