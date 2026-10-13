#!/bin/sh
set -eu
cd "$(dirname "$0")"
umask 077
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
mkdir -p data logs wykresy tmp
if [ ! -f config.json ]; then cp config.example.json config.json; fi
chmod 600 config.json
printf '%s\n' 'Środowisko gotowe. Uzupełnij config.json w mcedit. CRON nie został włączony.'
