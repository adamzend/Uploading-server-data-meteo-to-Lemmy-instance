"""Configuration validation; never display credentials."""
import json
import math
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent
FIELDS = ('temperature', 'humidity', 'pressure')

def validate(config):
    ZoneInfo(config['timezone'])
    if not isinstance(config['stale_after_minutes'], (int, float)) or not 1 <= config['stale_after_minutes'] <= 10080:
        raise ValueError('stale_after_minutes: expected 1..10080')
    m = config['modbus']
    if not isinstance(m['host'], str) or not m['host'].strip():
        raise ValueError('modbus.host: enter device address')
    for key, lo, hi in [('port', 1, 65535), ('unit_id', 0, 255), ('function_code', 3, 4), ('attempts', 1, 10)]:
        if type(m[key]) is not int or not lo <= m[key] <= hi:
            raise ValueError('modbus.' + key + ': invalid value')
    for key, lo, hi in [('timeout_seconds', .1, 120), ('retry_delay_seconds', 0, 60)]:
        if not isinstance(m[key], (int, float)) or not lo <= m[key] <= hi:
            raise ValueError('modbus.' + key + ': invalid value')
    for name in FIELDS:
        s = config['sensors'][name]
        if type(s['address']) is not int or not 0 <= s['address'] <= 65535:
            raise ValueError(name + '.address: enter a zero-based register address')
        if type(s['signed']) is not bool:
            raise ValueError(name + '.signed: expected boolean')
        for key in ('multiplier', 'offset', 'min', 'max'):
            if type(s[key]) not in (int, float) or not math.isfinite(s[key]):
                raise ValueError(name + '.' + key + ': expected finite number')
        if s['multiplier'] == 0 or s['min'] > s['max']:
            raise ValueError(name + ': invalid multiplier or range')
    l = config['lemmy']
    if type(l['enabled']) is not bool:
        raise ValueError('lemmy.enabled: expected boolean')
    if l['enabled']:
        u = urlsplit(l['instance'])
        if u.scheme != 'https' or not u.hostname or u.username or u.password or u.path not in ('', '/') or u.query or u.fragment:
            raise ValueError('lemmy.instance: expected HTTPS origin without credentials or path')
        for key in ('username', 'password', 'title', 'heading'):
            if not isinstance(l[key], str) or not l[key].strip():
                raise ValueError('lemmy.' + key + ': required')
        if type(l['community_id']) is not int or l['community_id'] <= 0:
            raise ValueError('lemmy.community_id: expected positive integer')
        if l['post_id'] is not None and (type(l['post_id']) is not int or l['post_id'] <= 0):
            raise ValueError('lemmy.post_id: expected null or positive integer')
        if type(l['pin_in_community']) is not bool:
            raise ValueError('lemmy.pin_in_community: expected boolean')
    return config

def load():
    return validate(json.loads((BASE / 'config.json').read_text(encoding='utf-8')))

if __name__ == '__main__':
    try:
        load()
        print('Konfiguracja poprawna. Nie wykonano połączeń sieciowych.')
    except Exception as exc:
        raise SystemExit('Błąd konfiguracji: ' + str(exc))
