import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import meteo
import settings
import publish_lemmy as publisher
from install_cron import entry
from test_meteo import FakeSocket
from test_support import config

class GenericTests(unittest.TestCase):
    def test_example_requires_real_addresses(self):
        c = json.loads((settings.BASE / 'config.example.json').read_text())
        with self.assertRaises(ValueError):
            settings.validate(c)
        c = config()
        settings.validate(c)
        c['sensors']['pressure']['address'] = None
        with self.assertRaises(ValueError):
            settings.validate(c)

    def test_signed_multiplier_offset_and_distant_addresses(self):
        c = config()
        c['sensors']['pressure']['address'] = 60000
        c['sensors']['temperature'].update(multiplier=.2, offset=1)
        values, raw = meteo.decode({20:65526, 23:450, 60000:10132}, 0, c['sensors'])
        self.assertEqual(values['temperature'], -1)
        self.assertAlmostEqual(values['pressure'], 1013.2)
        self.assertEqual(raw['temperature'], 65526)
        with patch('meteo.read_registers', side_effect=[(65526,), (450,), (10132,)]) as reader:
            result = meteo.collect(c)
        self.assertIsNone(result[-1])
        self.assertEqual([call.args[1:] for call in reader.call_args_list], [(20,1),(23,1),(60000,1)])

    def test_input_registers_fc04(self):
        c = config()['modbus']
        c['function_code'] = 4
        fake = FakeSocket(struct.pack('>HHHBBBH', 1, 0, 5, 8, 4, 2, 234))
        with patch('meteo.socket.create_connection', return_value=fake):
            self.assertEqual(meteo.read_registers(c, 10, 1), (234,))
        self.assertEqual(fake.sent, struct.pack('>HHHBBHH', 1, 0, 6, 8, 4, 10, 1))

    def test_cron_quotes_paths_and_rejects_percent(self):
        self.assertIn("'/tmp/weather station/run_cycle.py'", entry(Path('/tmp/weather station')))
        with self.assertRaises(ValueError):
            entry(Path('/tmp/weather%station'))

    def test_publish_updates_existing_post_preserving_static_footer(self):
        c = config()
        c['lemmy'].update(enabled=True, instance='https://localhost', username='fixture', password='fixture', community_id=12, post_id=42)
        requests = []
        post = {'id':42,'creator_id':99,'community_id':12,'deleted':False,'removed':False,
                'featured_community':False,'body':'Intro\n'+publisher.START+'\n\nold\n\n'+publisher.END+'\n\nSensor specifications'}
        class FakeClient:
            base = 'https://localhost'
            def request(self, path, data=None, method=None):
                requests.append((path,data,method))
                if path == '/api/v3/site':
                    return {'my_user':{'local_user_view':{'person':{'id':99}}}}
                if method == 'PUT':
                    post['body'] = data['body']
                return {'post_view':{'post':post.copy()}}
            def upload(self, filename):
                return {'url':'/fixture.png', 'file':filename.name, 'delete_token':'fixture'}
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base/'data').mkdir()
            (base/'wykresy').mkdir()
            from datetime import datetime
            from zoneinfo import ZoneInfo
            stamp = datetime.now(ZoneInfo(c['timezone'])).isoformat()
            values = dict(temperature=23.4,humidity=45,pressure=1013.2)
            (base/'data/status.json').write_text(json.dumps(dict(status='ok',checked_at=stamp,last_success_at=stamp,values=values,last_success_values=values)))
            (base/'wykresy/manifest.json').write_text(json.dumps({'month':stamp[:7], 'charts':{s:{'last_success_at':stamp} for s,_ in publisher.CHARTS}}))
            for slug,_ in publisher.CHARTS:
                (base/'wykresy'/ (slug+'.png')).write_bytes(b'fixture')
            with patch.object(publisher,'BASE',base), patch.object(publisher,'load_config',return_value=c), patch.object(publisher,'Client',FakeClient):
                publisher.publish()
            self.assertTrue(post['body'].endswith('Sensor specifications'))
            self.assertIn('23,4 °C',post['body'])
            self.assertFalse(any(method=='POST' and path=='/api/v3/post' for path,_,method in requests))
            self.assertEqual(json.loads((base/'data/lemmy-state.json').read_text())['post_id'],42)

if __name__ == '__main__':
    unittest.main()
