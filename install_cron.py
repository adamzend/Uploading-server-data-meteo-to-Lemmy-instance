"""Install hourly job for the current Unix user; preserve unrelated jobs."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import os
import shlex
import subprocess
from settings import load

BASE = Path(__file__).resolve().parent
MARKER = '# meteo-collector'

def entry(base):
    if any(c in str(base) for c in ('%', '\n', '\r')):
        raise ValueError('CRON path cannot contain percent signs or newlines')
    return ('0 * * * * ' + shlex.quote(str(base / '.venv/bin/python')) + ' '
            + shlex.quote(str(base / 'run_cycle.py')) + ' --quiet >> '
            + shlex.quote(str(base / 'logs/cron.log')) + ' 2>&1 ' + MARKER)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remove', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    if not args.remove:
        load()
        if not (BASE / '.venv/bin/python').exists():
            raise SystemExit('Run install.sh first')
    result = subprocess.run(['crontab', '-l'], capture_output=True, text=True,
                            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
    if result.returncode == 0:
        previous = result.stdout
    elif result.returncode == 1 and 'no crontab for' in result.stderr:
        previous = ''
    else:
        raise SystemExit('Cannot read crontab')
    (BASE / 'data').mkdir(exist_ok=True)
    (BASE / 'logs').mkdir(exist_ok=True)
    backup = BASE / 'data' / ('crontab-before-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.txt')
    backup.write_text(previous, encoding='utf-8')
    lines = [line for line in previous.splitlines() if not line.rstrip().endswith(MARKER)]
    if not args.remove:
        lines.append(entry(BASE))
    updated = '\n'.join(lines) + '\n'
    subprocess.run(['crontab', '-'], input=updated, text=True, check=True)
    if subprocess.check_output(['crontab', '-l'], text=True) != updated:
        raise SystemExit('Crontab verification failed')
    print('CRON zaktualizowany; kopia poprzedniej konfiguracji w data/.')

if __name__ == '__main__':
    main()
