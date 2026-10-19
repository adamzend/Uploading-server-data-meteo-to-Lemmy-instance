#!/usr/bin/env python3
"""Publish a single weather post and uploaded charts through Lemmy API v3."""
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import uuid
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from zoneinfo import ZoneInfo

from settings import load as load_config

BASE = Path(__file__).resolve().parent
START = '[meteo-start]: #'
END = '[meteo-end]: #'
LEGACY_START = '<!-- METEO:START -->'
LEGACY_END = '<!-- METEO:END -->'
CHARTS = [('temperatura', 'Temperatura'), ('wilgotnosc', 'Wilgotność powietrza'),
          ('cisnienie', 'Ciśnienie atmosferyczne')]


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save_json(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.chmod(0o600)
    temporary.replace(path)


class ApiError(Exception):
    def __init__(self, status, code):
        super().__init__(f'Lemmy HTTP {status}: {code}')
        self.status = status
        self.code = code


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ApiError(code, 'redirect_refused; configure canonical instance address')


class Client:
    def __init__(self):
        self.secrets = load_config()['lemmy']
        self.base = self.secrets['instance'].rstrip('/')
        self.token_path = BASE / 'data/lemmy-token.json'
        self.token = None
        if self.token_path.exists():
            cached = read_json(self.token_path)
            if cached.get('instance') == self.base and cached.get('username') == self.secrets['username']:
                self.token = cached.get('jwt')

    def request(self, path, data=None, method=None, content_type='application/json', auth=True, retry=True):
        if auth and not self.token:
            self.login()
        headers = {'User-Agent': 'MeteoStation/1.0', 'Accept': 'application/json'}
        if auth:
            headers['Authorization'] = 'Bearer ' + self.token
        if data is not None:
            headers['Content-Type'] = content_type
            if not isinstance(data, bytes):
                data = json.dumps(data).encode('utf-8')
        request = Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with build_opener(NoRedirect()).open(request, timeout=45) as response:
                return json.load(response)
        except HTTPError as exc:
            try:
                code = json.loads(exc.read()).get('error', 'api_error')
            except Exception:
                code = 'non_json_error'
            if auth and retry and (exc.code == 401 or code in ('not_logged_in', 'incorrect_login')):
                self.login()
                return self.request(path, data, method, content_type, auth=True, retry=False)
            raise ApiError(exc.code, code) from None

    def login(self):
        result = self.request('/api/v3/user/login', {
            'username_or_email': self.secrets['username'], 'password': self.secrets['password']},
            method='POST', auth=False)
        if not result.get('jwt'):
            raise ValueError('Login did not return a token')
        self.token = result['jwt']
        save_json(self.token_path, {'jwt': self.token, 'instance': self.base, 'username': self.secrets['username']})

    def upload(self, filename):
        boundary = 'meteo-' + uuid.uuid4().hex
        header = (f'--{boundary}\r\nContent-Disposition: form-data; name="images[]"; '
                  f'filename="{filename.name}"\r\nContent-Type: image/png\r\n\r\n').encode()
        body = header + filename.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
        result = self.request('/pictrs/image', body, 'POST', 'multipart/form-data; boundary=' + boundary)
        files = result.get('files', [])
        if len(files) != 1:
            raise ValueError('Image upload did not return exactly one image')
        entry = files[0]
        return {'url': self.base + '/pictrs/image/' + quote(entry['file'], safe=''),
                'file': entry['file'], 'delete_token': entry.get('delete_token')}


def merge_body(existing, section):
    start, end = (LEGACY_START, LEGACY_END) if LEGACY_START in existing else (START, END)
    if existing.count(start) != 1 or existing.count(end) != 1:
        raise ValueError('Weather markers missing or duplicated; post left unchanged')
    before, rest = existing.split(start)
    middle, after = rest.split(end)
    return before + START + '\n\n' + section + '\n\n' + END + after


def render_section(status, images, now=None, config=None):
    config = config or load_config()
    now = now or datetime.now(timezone.utc)
    checked = datetime.fromisoformat(status['checked_at'])
    age = (now - checked).total_seconds()
    healthy = status['status'] == 'ok' and 0 <= age <= config['stale_after_minutes'] * 60
    if config.get('heartbeat', {}).get('enabled', False):
        healthy = healthy and status.get('freshness_verified') is True
    values = status.get('values') if healthy else status.get('last_success_values')
    def value(name, unit):
        return ('—' if not values else f"{values[name]:.1f}".replace('.', ',') + ' ' + unit)
    # Non-breaking-space paragraphs retain vertical spacing in Lemmy Markdown.
    lines = ['## ' + config['lemmy']['heading'], '', '\u00a0', '', '\u00a0', '',
             f"**Temperatura:** {value('temperature', '°C')}  ",
             f"**Wilgotność:** {value('humidity', '%')}  ",
             f"**Ciśnienie:** {value('pressure', 'hPa')}  ",
             '**Status:** ' + ('🟢 Działa poprawnie' if healthy else '🔴 Błąd stacji') + '  ']
    stamp = status.get('last_success_at')
    shown = datetime.fromisoformat(stamp).astimezone(ZoneInfo(config['timezone'])).strftime('%d.%m.%Y, %H:%M') if stamp else 'brak'
    lines.append('**Ostatni poprawny pomiar:** ' + shown)
    if not healthy and values:
        lines.append('\nPodane wartości pochodzą z ostatniego poprawnego pomiaru.')
    if not healthy:
        lines.append('\nBrak aktualnego, poprawnego odczytu lub potwierdzenia świeżości danych stacji.')
    elif not config.get('heartbeat', {}).get('enabled', False):
        lines.append('\nKontrola heartbeatu źródła jest wyłączona; status dotyczy odczytu Modbus.')
    lines.append('\n' + config['lemmy']['update_note'])
    for slug, title in CHARTS:
        lines.extend(['', f'### {title}', '', f"![{title} — bieżący miesiąc]({images[slug]['url']})"])
    return '\n'.join(lines)


def publish():
    os.umask(0o077)
    config = load_config()
    settings = config['lemmy']
    if not settings.get('enabled'):
        return None
    (BASE / 'data').mkdir(exist_ok=True)
    with (BASE / 'data/publish.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        client = Client()
        identity = client.request('/api/v3/site')['my_user']['local_user_view']['person']['id']
        state_path = BASE / 'data/lemmy-state.json'
        state = read_json(state_path) if state_path.exists() else {'images': {}}
        destination = {'instance': client.base, 'author_id': identity, 'community_id': settings['community_id']}
        if state.get('destination') not in (None, destination):
            raise ValueError('Destination changed: archive local publication state before using a different account or community')
        if settings['post_id'] and state.get('post_id') and settings['post_id'] != state['post_id']:
            raise ValueError('Configured post_id differs from saved state')
        state['destination'] = destination
        status = read_json(BASE / 'data/status.json')
        manifest = read_json(BASE / 'wykresy/manifest.json')
        if manifest['month'] != datetime.now(ZoneInfo(config['timezone'])).strftime('%Y-%m'):
            raise ValueError('Chart month is not current; publication deferred')
        for info in manifest['charts'].values():
            if info['last_success_at'] and status['last_success_at'] and datetime.fromisoformat(info['last_success_at']) != datetime.fromisoformat(status['last_success_at']):
                raise ValueError('Chart and measurement timestamps differ; publication deferred')
        post_id = state.get('post_id') or settings['post_id']
        if not post_id:
            result = client.request('/api/v3/user?person_id=' + str(identity) + '&limit=50&sort=New')
            candidates = [p['post'] for p in result.get('posts', []) if p['post']['community_id'] == settings['community_id']
                          and p['post']['name'] == settings['title'] and any(marker in (p['post'].get('body') or '') for marker in (START, LEGACY_START))]
            if len(candidates) > 1:
                raise ValueError('Multiple matching weather posts; manual selection required')
            if candidates:
                post_id = state['post_id'] = candidates[0]['id']
                state.pop('creation_pending', None)
                save_json(state_path, state)
            elif state.get('creation_pending'):
                raise ValueError('Previous creation outcome uncertain; refusing duplicate post')
        if post_id:
            current = client.request('/api/v3/post?id=' + str(post_id))['post_view']['post']
            if current['creator_id'] != identity or current['community_id'] != settings['community_id']:
                raise ValueError('Post ownership or community mismatch')
            if current['deleted'] or current['removed']:
                raise ValueError('Post has been deleted or removed')
            merge_body(current.get('body') or '', '')  # Validate markers before uploading.
        for slug, title in CHARTS:
            path = BASE / 'wykresy' / (slug + '.png')
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if state['images'].get(slug, {}).get('sha256') != digest:
                uploaded = client.upload(path)
                uploaded['sha256'] = digest
                with (BASE / 'data/lemmy-uploads.jsonl').open('a', encoding='utf-8') as archive:
                    archive.write(json.dumps({'uploaded_at': datetime.now(timezone.utc).isoformat(),
                                              'chart': slug, **uploaded}) + '\n')
                state['images'][slug] = uploaded
                save_json(state_path, state)
        section = render_section(status, state['images'], config=config)
        if not post_id:
            state['creation_pending'] = True
            save_json(state_path, state)
            appendix = (BASE / 'static.txt').read_text(encoding='utf-8') if (BASE / 'static.txt').exists() else ''
            result = client.request('/api/v3/post', {'name': settings['title'], 'community_id': settings['community_id'],
                                    'body': START + '\n\n' + section + '\n\n' + END + '\n\n' + appendix, 'nsfw': False}, 'POST')
            post_id = state['post_id'] = result['post_view']['post']['id']
            state.pop('creation_pending', None)
            save_json(state_path, state)
        else:
            # Fetch again to preserve edits made while uploading images.
            current = client.request('/api/v3/post?id=' + str(post_id))['post_view']['post']
            body = merge_body(current.get('body') or '', section)
            if body != current.get('body'):
                client.request('/api/v3/post', {'post_id': post_id, 'body': body}, 'PUT')
        post = client.request('/api/v3/post?id=' + str(post_id))['post_view']['post']
        if settings.get('pin_in_community') and not post['featured_community']:
            client.request('/api/v3/post/feature', {'post_id': post_id, 'featured': True, 'feature_type': 'Community'}, 'POST')
        state['post_id'] = post_id
        state['last_published_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
        state['last_measurement_at'] = status['checked_at']
        save_json(state_path, state)
        url = client.base + '/post/' + str(post_id)
        logging.info('Zaktualizowano wpis Lemmy: %s', url)
        return url


if __name__ == '__main__':
    print(publish())
