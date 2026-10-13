import json
from pathlib import Path

def config():
    c = json.loads((Path(__file__).parent / 'config.example.json').read_text(encoding='utf-8'))
    c['timezone'] = 'Europe/Warsaw'
    c['modbus'].update(host='localhost', unit_id=8)
    for key, address in [('temperature', 20), ('humidity', 23), ('pressure', 25)]:
        c['sensors'][key]['address'] = address
    return c
