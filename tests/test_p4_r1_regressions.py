"""P4-R1 regressions through real PG, public APIs, Worker and guarded HTTP."""
import io
import base64
import json
import threading
import uuid
import wave
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend import store as s
from backend.app import app
from backend.worker import Worker
from tests.platform_model_helpers import admin, CANARY, create_provider, provider_body
from tests.test_p4_submission_execution import project, submit


@pytest.fixture
def fake(monkeypatch):
    events = []
    png = io.BytesIO()
    Image.new('RGB', (8, 8), 'green').save(png, format='PNG')
    wav = io.BytesIO()
    with wave.open(wav, 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b'\0\0' * 800)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, body, mime='application/json', status=200):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def record(self, body=None):
            event = {'method': self.command, 'path': self.path,
                     'has_auth': bool(self.headers.get('Authorization')),
                     'correct_auth': self.headers.get('Authorization') == 'Bearer ' + CANARY}
            if self.path == '/v1/chat/completions':
                event.update({key: body[key] for key in ('max_tokens', 'temperature') if key in body})
            elif self.path == '/v1/images/generations':
                event.update({key: body[key] for key in ('n', 'size') if key in body})
            events.append(event)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or '{}')
            self.record(body)
            if self.path == '/v1/chat/completions':
                self.reply(('data: ' + json.dumps({'choices': [{'delta': {'content': 'P4-R1 text'}}]})
                            + '\n\ndata: [DONE]\n\n').encode(), 'text/event-stream')
            elif self.path in ('/api/v1/generate', '/prompt'):
                self.reply({'job_id': 'maestro-r1', 'prompt_id': 'comfy-r1'})
            elif self.path == '/v1/models/test/audio/predictions':
                self.reply({'id': 'replicate-audio-r1'})
            elif self.path == '/v1/images/generations':
                self.reply({'data': [{'b64_json': base64.b64encode(png.getvalue()).decode()}]})
            else:
                self.reply({'error': 'not found'}, status=404)

        def do_GET(self):
            self.record()
            if self.path == '/api/v1/models':
                self.reply({'models': [{'model_type': 'test-maestro',
                                       'director': {'image': {'compatible': True}}}]})
            elif self.path == '/api/v1/defaults/test-maestro':
                self.reply({'defaults': {}})
            elif self.path == '/api/v1/status/maestro-r1':
                self.reply({'status': 'completed', 'output_files': ['result.png']})
            elif self.path == '/history/comfy-r1':
                self.reply({'comfy-r1': {'outputs': {'1': {'images': [
                    {'filename': 'result.png', 'subfolder': '', 'type': 'output'}]}}}})
            elif self.path.startswith(('/api/v1/uploads/', '/view?')):
                self.reply(png.getvalue(), 'image/png')
            elif self.path == '/v1/predictions/replicate-audio-r1':
                self.reply({'status': 'succeeded', 'output':
                            f'http://127.0.0.1:{self.server.server_port}/result.wav'})
            elif self.path == '/result.wav':
                self.reply(wav.getvalue(), 'audio/wav')
            else:
                self.reply({'error': 'not found'}, status=404)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv('OVC_PROVIDER_EGRESS_EXCEPTIONS', json.dumps([
        {'scheme': 'http', 'host': '127.0.0.1', 'ip': '127.0.0.1', 'port': server.server_port}]))
    try:
        yield f'http://127.0.0.1:{server.server_port}', events
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def model(admin, provider, *, kind='text', upstream='test-text', rules=None, defaults=None):
    return admin.post('/api/admin/models', json={
        'revision': 0, 'provider_id': provider['id'], 'kind': kind, 'enabled': True, 'published': True,
        'definition': {'name': 'P4-R1 regression', 'upstream_model': upstream, 'capabilities': {},
                       'rules': rules or {}, 'defaults': defaults or {}}})


@contextmanager
def ordinary_editor(admin, p):
    token = admin.post('/api/admin/invitations', json={'expires_hours': 1}).json()['token']
    with TestClient(app) as client:
        registered = client.post('/api/auth/register', json={
            'invitation_token': token, 'phone': '1' + str(uuid.uuid4().int % 10**10).zfill(10),
            'nickname': 'P4-R1 ordinary', 'password': 'Synthetic-r1-test-only!'})
        assert registered.status_code == 200
        uid = registered.json()['user']['id']
        client.headers['X-CSRF-Token'] = client.cookies.get('ovc_csrf')
        with s.db() as c:
            workspace = c.execute('SELECT workspace_id FROM productions WHERE id=%s',
                                  (p['production_id'],)).fetchone()['workspace_id']
        assert admin.put(f'/api/workspaces/{workspace}/members/{uid}', json={'role': 'member'}).status_code == 200
        assert admin.put(f"/api/productions/{p['production_id']}/members/{uid}", json={'role': 'editor'}).status_code == 200
        assert client.get('/api/admin/models').status_code == 403
        yield client


def execute(job):
    s.job_update(job['id'], status='running')
    return Worker().execute(job)


@pytest.mark.parametrize('value', [None, 201, 100])
def test_effective_text_parameters_match_published_limit(admin, fake, value):
    base, events = fake
    provider = create_provider(admin, config={'type': 'openai', 'url': base + '/v1'})
    rules = {'max_tokens': {'type': 'integer', 'min': 1, 'max': 200}}
    published = model(admin, provider, rules=rules)
    assert published.status_code == 200
    p = project(admin)
    with ordinary_editor(admin, p) as client:
        parameters = {} if value is None else {'max_tokens': value}
        response = submit(client, p['id'], published.json()['id'],
                          input={'model_id': published.json()['id'], 'prompt': 'Test', 'parameters': parameters})
        if response.status_code == 400:
            assert value in (None, 201)
            assert events == []
            print(json.dumps({'case': value, 'submit': 400, 'http_calls': 0}))
            return
        assert response.status_code == 200
        assert value != 201
        job = response.json()
        with s.db() as c:
            frozen = json.loads(c.execute('SELECT parameters FROM job_private WHERE job_id=%s',
                                          (job['id'],)).fetchone()['parameters'])
        assert execute(job)['text'] == 'P4-R1 text'
        print(json.dumps({'case': value, 'rules': rules, 'frozen': frozen, 'wire': events}))
        assert events[0]['max_tokens'] <= 200
        assert events[0]['max_tokens'] == frozen['max_tokens']
        if value == 100:
            assert events[0]['max_tokens'] == 100


@pytest.mark.parametrize('provider_type', ['maestro', 'comfy'])
def test_unsupported_native_key_mode_rejected_before_publication(admin, fake, provider_type):
    base, events = fake
    options = {'workflow': {'1': {'inputs': {'text': '{{prompt}}'}}}} if provider_type == 'comfy' else {}
    response = admin.post('/api/admin/model-providers', json=provider_body(config={
        'type': provider_type, 'url': base, 'auth_mode': 'api_key', 'options': options}))
    if response.status_code == 200:
        # Baseline: prove the accepted Key is actually ignored by the real adapter.
        published = model(admin, response.json(), kind='image', upstream='test-maestro')
        assert published.status_code == 200
        p = project(admin)
        job = submit(admin, p['id'], published.json()['id'], kind='image').json()
        assert execute(job)['assets']
    print(json.dumps({'provider': provider_type, 'save_status': response.status_code, 'http': events}))
    assert response.status_code == 400
    assert events == []


def test_replicate_audio_not_publishable_or_callable(admin, fake):
    base, events = fake
    provider = create_provider(admin, config={'type': 'replicate', 'url': base + '/v1'})
    published = model(admin, provider, kind='audio', upstream='test/audio')
    observed_error = None
    if published.status_code == 200:
        p = project(admin)
        response = submit(admin, p['id'], published.json()['id'], kind='audio')
        assert response.status_code == 200
        try:
            execute(response.json())
        except Exception as exc:
            observed_error = type(exc).__name__
    print(json.dumps({'publish_status': published.status_code, 'error_type': observed_error, 'http': events}))
    assert published.status_code == 400
    assert events == []


@pytest.mark.parametrize('provider_type', ['maestro', 'comfy'])
def test_native_anonymous_supported_path_keeps_real_http_execution(admin, fake, provider_type):
    base, events = fake
    options = {'workflow': {'1': {'inputs': {'text': '{{prompt}}'}}}} if provider_type == 'comfy' else {}
    provider = create_provider(admin, api_key='', config={
        'type': provider_type, 'url': base, 'auth_mode': 'none', 'options': options})
    published = model(admin, provider, kind='image', upstream='test-maestro')
    assert published.status_code == 200
    p = project(admin)
    with ordinary_editor(admin, p) as client:
        response = submit(client, p['id'], published.json()['id'], kind='image')
        assert response.status_code == 200
        assets = execute(response.json())['assets']
        assert assets[0]['kind'] == 'image'
        assert client.get(assets[0]['url']).status_code == 200
    assert len(events) >= 3
    assert all(not item['has_auth'] for item in events)
    print(json.dumps({'provider': provider_type, 'auth_mode': 'none', 'result': 'image', 'http': events}))


@pytest.mark.parametrize('provider_type', ['maestro', 'comfy', 'replicate'])
def test_legacy_unsupported_combinations_hidden_and_blocked_at_every_entry(admin, fake, provider_type):
    base, events = fake
    native = provider_type != 'replicate'
    provider = create_provider(admin, api_key='' if native else CANARY, config={
        'type': provider_type, 'url': base + '/v1', 'auth_mode': 'none' if native else 'api_key'})
    published = model(admin, provider, kind='image', upstream='test/image').json()
    p = project(admin)
    queued = submit(admin, p['id'], published['id'], kind='image').json()
    # Test-only fixture representing a pre-R1 accepted immutable version; the
    # product must reject it without rewriting or migrating user data.
    with s.db() as c:
        if native:
            config = dict(provider['config'], auth_mode='api_key')
            c.execute('UPDATE provider_config_versions SET config=%s WHERE id=%s',
                      (s.dumps(config), provider['config_version_id']))
        else:
            c.execute("UPDATE model_catalog SET kind='audio' WHERE id=%s", (published['id'],))
    kind = 'image' if native else 'audio'
    assert published['id'] not in {item['id'] for item in admin.get('/api/models').json()['models']}
    assert model(admin, provider, kind=kind, upstream='test/audio').status_code == 400
    assert submit(admin, p['id'], published['id'], kind=kind).status_code == 400
    with pytest.raises(ValueError, match='不支持'):
        execute(queued)
    s.job_update(queued['id'], status='interrupted', provider_job_id='old-handle')
    assert admin.post('/api/jobs/' + queued['id'] + '/resume').status_code == 400
    assert events == []


@pytest.mark.parametrize('name,kind,provider_type,rule,value', [
    ('temperature', 'text', 'openai', {'type': 'number', 'min': 0, 'max': .2}, 0),
    ('n', 'image', 'openai', {'type': 'integer', 'min': 2, 'max': 3}, 2),
    ('voice_type', 'audio', 'volcengine_speech', {'type': 'string', 'enum': ['only-allowed-voice']}, 'only-allowed-voice'),
])
def test_other_declared_controls_cannot_fall_back_when_omitted(admin, fake, name, kind, provider_type, rule, value):
    base, events = fake
    provider = create_provider(admin, config={'type': provider_type, 'url': base + '/v1'})
    published = model(admin, provider, kind=kind, rules={name: rule})
    assert published.status_code == 200
    p = project(admin)
    missing = submit(admin, p['id'], published.json()['id'], kind=kind)
    assert missing.status_code == 400
    assert events == []
    allowed = model(admin, provider, kind=kind, rules={name: rule}, defaults={name: value})
    assert allowed.status_code == 200
    response = submit(admin, p['id'], allowed.json()['id'], kind=kind)
    assert response.status_code == 200
    with s.db() as c:
        frozen = json.loads(c.execute('SELECT parameters FROM job_private WHERE job_id=%s',
                                      (response.json()['id'],)).fetchone()['parameters'])
    assert frozen[name] == value
    if kind != 'audio':
        assert execute(response.json())
        assert events[0][name] == frozen[name]
    print(json.dumps({'parameter': name, 'missing': 400, 'frozen': frozen, 'wire': events}))


def test_old_queued_missing_parameter_cannot_reach_adapter_fallback(admin, fake):
    base, events = fake
    provider = create_provider(admin, config={'type': 'openai', 'url': base + '/v1'})
    published = model(admin, provider, rules={'max_tokens': {'type': 'integer', 'min': 1, 'max': 200}},
                      defaults={'max_tokens': 100}).json()
    p = project(admin)
    job = submit(admin, p['id'], published['id']).json()
    with s.db() as c:
        c.execute("UPDATE job_private SET parameters='{}' WHERE job_id=%s", (job['id'],))
    with pytest.raises(ValueError, match='缺少平台受限参数'):
        execute(job)
    assert events == []


@pytest.mark.parametrize('voice', ['', ' spaced-voice '])
def test_voice_enum_cannot_publish_values_that_trigger_fallback_or_rewrite(admin, fake, voice):
    base, events = fake
    provider = create_provider(admin, config={'type': 'volcengine_speech', 'url': base + '/v1'})
    response = model(admin, provider, kind='audio',
                     rules={'voice_type': {'type': 'string', 'enum': [voice]}}, defaults={'voice_type': voice})
    assert response.status_code == 400
    assert events == []
