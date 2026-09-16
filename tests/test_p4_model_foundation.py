"""P4 foundation tests against isolated PostgreSQL and fake HTTP transports.

These do not claim UI/Worker/full-stage acceptance. Never print synthetic keys.
"""
import json
import socket
import time
import uuid

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend import platform_models as models, provider_secrets as secrets, store as s
from backend import provider_egress as egress
from backend.app import app
from tests.auth_helpers import login_admin

from tests.platform_model_helpers import MASTER, CANARY, admin, provider_body, create_provider, create_model

def job_binding(admin, model):
    response = admin.post('/api/projects', json={'name': 'P4 binding fixture'})
    assert response.status_code == 200, response.text
    pid = response.json()['id']
    jid = s.uid('job-')
    inp = {'model_id': model['id'], 'prompt': 'Synthetic prompt'}
    with s.db() as c:
        binding = models.resolve(c, model['id'], 'text', inp)
        c.execute('''INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated)
            VALUES(%s,%s,%s,'test','text','queued',%s,%s,%s)''',
            (jid, s.uid('submission-'), pid, s.dumps(inp), time.time(), time.time()))
        models.bind_job(c, jid, binding)
    return jid, binding


def test_secret_ciphertext_and_safe_projection(admin):
    provider = create_provider(admin)
    model = create_model(admin, provider)
    with s.db() as c:
        row = c.execute('SELECT * FROM provider_credential_versions WHERE id=%s',
                        (provider['credential_version_id'],)).fetchone()
        assert CANARY not in row['ciphertext']
        assert secrets.decrypt(c, row) == CANARY
        audit = c.execute('SELECT payload FROM audit_events WHERE target_id=%s', (provider['id'],)).fetchall()
        assert CANARY not in str(audit)
    result = admin.get('/api/models')
    assert result.status_code == 200
    assert any(item['id'] == model['id'] for item in result.json()['models'])
    assert all(word not in result.text for word in (CANARY, 'private-upstream-test-id', 'models.example.test'))


@pytest.mark.parametrize('mode', ['missing', 'wrong', 'malformed', 'corrupt'])
def test_secret_failure_is_closed_and_atomic(admin, monkeypatch, mode):
    provider = create_provider(admin)
    model = create_model(admin, provider)
    jid, _ = job_binding(admin, model)
    with s.db() as c:
        job = s.unpack(c.execute('SELECT * FROM jobs WHERE id=%s', (jid,)).fetchone())
    if mode == 'missing':
        monkeypatch.delenv(secrets.KEY_ENV)
    elif mode == 'wrong':
        monkeypatch.setenv(secrets.KEY_ENV, Fernet.generate_key().decode('ascii'))
    elif mode == 'malformed':
        monkeypatch.setenv(secrets.KEY_ENV, 'not-a-master-key')
    else:
        with s.db() as c:
            c.execute('UPDATE provider_credential_versions SET ciphertext=%s WHERE id=%s',
                      ('corrupt', provider['credential_version_id']))
    with s.db() as c:
        counts = tuple(c.execute('SELECT count(*) n FROM ' + table).fetchone()['n'] for table in
                       ('model_providers', 'provider_config_versions', 'provider_credential_versions', 'audit_events'))
    response = admin.put('/api/admin/model-providers/' + provider['id'], json={
        key: value for key, value in provider_body(revision=provider['revision']).items() if key != 'api_key'
    })
    assert response.status_code == 400
    assert CANARY not in response.text
    with s.db() as c:
        after = tuple(c.execute('SELECT count(*) n FROM ' + table).fetchone()['n'] for table in
                      ('model_providers', 'provider_config_versions', 'provider_credential_versions', 'audit_events'))
        assert after == counts
    assert admin.post('/api/admin/model-providers/' + provider['id'] + '/check').status_code == 400
    # Prove the real Worker path also stops before HTTP, not only admin saves.
    from backend.worker import Worker
    calls = []
    def forbidden_http(*args, **kwargs):
        calls.append('unexpected-http')
        raise AssertionError('unavailable secrets must never reach HTTP')
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', forbidden_http)
    with pytest.raises(secrets.SecretUnavailable):
        Worker().execute(job)
    assert calls == []


def test_rotation_keeps_original_identity_and_revocation_blocks(admin):
    provider = create_provider(admin)
    model = create_model(admin, provider)
    jid, first = job_binding(admin, model)
    replacement = admin.put('/api/admin/model-providers/' + provider['id'], json=provider_body(
        revision=provider['revision'], api_key='synthetic-rotated-key',
        config={'type': 'openai', 'url': 'https://second.example.test/v1'},
    ))
    assert replacement.status_code == 200
    changed = replacement.json()
    with s.db() as c:
        second = models.resolve(c, model['id'], 'text', {'model_id': model['id'], 'prompt': 'new'})
        assert first.credential_version_id != second.credential_version_id
        original = models.load_job_provider(c, jid, remote=True)
        assert original['url'] == provider['config']['url']
        assert original['api_key'] == CANARY
        stored = c.execute('SELECT * FROM job_private WHERE job_id=%s', (jid,)).fetchone()
        assert CANARY not in str(stored)
        assert json.loads(stored['provider']) == {}
    revoke = admin.post(f"/api/admin/model-providers/{provider['id']}/credentials/{first.credential_version_id}/revoke")
    assert revoke.status_code == 200
    with s.db() as c, pytest.raises(secrets.SecretUnavailable):
        models.load_job_provider(c, jid, remote=True)
    assert changed['credential_version_id'] == second.credential_version_id


def test_disable_stops_new_calls_but_not_old_remote_queries(admin):
    provider = create_provider(admin)
    model = create_model(admin, provider)
    jid, _ = job_binding(admin, model)
    body = provider_body(revision=provider['revision'], enabled=False)
    body.pop('api_key')
    assert admin.put('/api/admin/model-providers/' + provider['id'], json=body).status_code == 200
    with s.db() as c:
        with pytest.raises(ValueError, match='停用'):
            models.resolve(c, model['id'], 'text', {'model_id': model['id'], 'prompt': 'new'})
        with pytest.raises(ValueError, match='停用'):
            models.load_job_provider(c, jid)
        assert models.load_job_provider(c, jid, remote=True)['credential_version_id'] == provider['credential_version_id']
    assert not any(item['id'] == model['id'] for item in admin.get('/api/models').json()['models'])


@pytest.mark.parametrize('override', [
    {'provider': 'other'}, {'nested': [{'api_key': 'injected'}]},
    {'parameters': {'headers': {'Authorization': 'injected'}}},
    {'document': {'nodes': [{'config': {'model': 'upstream-injected'}}]}},
    {'nested': {'baseURL': 'http://127.0.0.1'}},
])
def test_nested_override_rejected_by_resolver(admin, override):
    provider = create_provider(admin)
    model = create_model(admin, provider)
    with s.db() as c, pytest.raises(ValueError, match='覆盖'):
        models.resolve(c, model['id'], 'text', {'model_id': model['id'], 'prompt': 'test', **override})


@pytest.mark.parametrize('parameters', [{'max_tokens': 201}, {'max_tokens': True}, {'unknown': 1}])
def test_parameter_bounds(admin, parameters):
    provider = create_provider(admin)
    model = create_model(admin, provider)
    with s.db() as c, pytest.raises(ValueError):
        models.resolve(c, model['id'], 'text', {'model_id': model['id'], 'prompt': 'test', 'parameters': parameters})


def test_admin_csrf_and_non_admin_guards(admin):
    csrf = admin.headers.pop('X-CSRF-Token')
    assert admin.post('/api/admin/model-providers', json=provider_body()).status_code == 403
    admin.headers['X-CSRF-Token'] = csrf
    invitation = admin.post('/api/admin/invitations', json={'expires_hours': 1}).json()['token']
    with TestClient(app) as ordinary:
        response = ordinary.post('/api/auth/register', json={
            'invitation_token': invitation, 'phone': '1' + str(uuid.uuid4().int % 10**10).zfill(10),
            'nickname': 'P4 Ordinary', 'password': 'P4-test-password-only!',
        })
        assert response.status_code == 200
        ordinary.headers['X-CSRF-Token'] = ordinary.cookies.get('ovc_csrf')
        assert ordinary.get('/api/models').status_code == 200
        for path in ('/api/admin/model-providers', '/api/admin/models'):
            assert ordinary.get(path).status_code == 403
            assert ordinary.post(path, json={}).status_code == 403
        template_id = 'p4-template-' + uuid.uuid4().hex
        body = {'revision': admin.get('/api/prompt-library').json()['revision'],
                'name': 'P4 template', 'kind': 'text', 'content': 'Safe template'}
        assert ordinary.put('/api/admin/prompt-templates/' + template_id, json=body).status_code == 403
        assert ordinary.put('/api/prompt-library/' + template_id, json=body).status_code == 403
        assert admin.put('/api/prompt-library/' + template_id, json=body).status_code == 410
        first = admin.put('/api/admin/prompt-templates/' + template_id, json=body)
        assert first.status_code == 200
        assert ordinary.get('/api/prompt-library').json() == first.json()
        assert admin.put('/api/admin/prompt-templates/' + template_id, json=body).status_code == 409
        body.update(revision=first.json()['revision'], content='Updated template')
        second = admin.put('/api/admin/prompt-templates/' + template_id, json=body)
        assert second.status_code == 200
        template = next(item for item in second.json()['templates'] if item['id'] == template_id)
        assert template['version'] == 2
        assert template['history'][0]['content'] == 'Safe template'
        with s.db() as c:
            assert c.execute('SELECT count(*) n FROM prompt_template_revisions WHERE template_id=%s',
                             (template_id,)).fetchone()['n'] == 2


@pytest.mark.parametrize('role',['owner','manager','editor','viewer'])
def test_each_tenant_role_denied_all_model_and_legacy_management_routes(admin, role):
    p=admin.post('/api/projects',json={'name':'P4 role matrix'}).json()
    provider=create_provider(admin); model=create_model(admin,provider)
    invitation=admin.post('/api/admin/invitations',json={'expires_hours':1}).json()['token']
    with TestClient(app) as ordinary:
        response=ordinary.post('/api/auth/register',json={'invitation_token':invitation,
            'phone':'1'+str(uuid.uuid4().int%10**10).zfill(10),'nickname':'P4 '+role,
            'password':'Synthetic-role-test-only!'})
        assert response.status_code==200
        uid=response.json()['user']['id']
        ordinary.headers['X-CSRF-Token']=ordinary.cookies.get('ovc_csrf')
        with s.db() as c:
            workspace=c.execute('SELECT workspace_id FROM productions WHERE id=%s',(p['production_id'],)).fetchone()['workspace_id']
            c.execute('INSERT INTO workspace_members(workspace_id,user_id,role,created) VALUES(%s,%s,%s,%s)',
                      (workspace,uid,'owner' if role=='owner' else 'member',time.time()))
            if role!='owner':
                c.execute('INSERT INTO production_members(production_id,user_id,role,created) VALUES(%s,%s,%s,%s)',
                          (p['production_id'],uid,role,time.time()))
        assert ordinary.get('/api/projects/'+p['id']).status_code==200
        paths=[('GET','/api/admin/model-providers'),('POST','/api/admin/model-providers'),
               ('PUT','/api/admin/model-providers/'+provider['id']),
               ('POST',f"/api/admin/model-providers/{provider['id']}/check"),
               ('POST',f"/api/admin/model-providers/{provider['id']}/credentials/{provider['credential_version_id']}/revoke"),
               ('GET','/api/admin/models'),('POST','/api/admin/models'),('PUT','/api/admin/models/'+model['id']),
               ('PUT','/api/settings'),('GET',f"/api/providers/{provider['id']}/models"),
               ('POST',f"/api/providers/{provider['id']}/verify"),('POST',f"/api/providers/{provider['id']}/test"),
               ('PUT','/api/admin/prompt-templates/role-test')]
        for method,path in paths:
            result=ordinary.request(method,path,json={} if method!='GET' else None)
            assert result.status_code==403,(role,method,path,result.status_code)
        for path in ('/api/models','/api/settings','/api/prompt-library'):
            result=ordinary.get(path)
            assert result.status_code==200
            assert CANARY not in result.text
            assert 'models.example.test' not in result.text


def test_save_and_check_make_no_http_requests(admin, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('configuration must not submit HTTP')
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))])
    provider = create_provider(admin)
    response = admin.post(f"/api/admin/model-providers/{provider['id']}/check")
    assert response.status_code == 200
    assert response.json()['status'] == 'unverified'
    assert response.json()['authentication_verified'] is False


def test_config_and_credential_roll_back_when_audit_fails(admin, monkeypatch):
    from backend import identity
    with s.db() as c:
        before = tuple(c.execute('SELECT count(*) n FROM ' + table).fetchone()['n'] for table in
                       ('model_providers', 'provider_config_versions', 'provider_credential_versions'))
    def failure(*args, **kwargs):
        raise ValueError('Synthetic audit failure')
    monkeypatch.setattr(identity, 'audit', failure)
    assert admin.post('/api/admin/model-providers', json=provider_body()).status_code == 400
    with s.db() as c:
        after = tuple(c.execute('SELECT count(*) n FROM ' + table).fetchone()['n'] for table in
                      ('model_providers', 'provider_config_versions', 'provider_credential_versions'))
    assert before == after


def test_ciphertext_cannot_be_transplanted_to_other_provider(admin):
    first, second = create_provider(admin), create_provider(admin)
    with s.db() as c:
        a = models._credential(c, first['credential_version_id'])
        b = models._credential(c, second['credential_version_id'])
        transplanted = {**dict(b), 'ciphertext': a['ciphertext']}
        with pytest.raises(secrets.SecretUnavailable):
            secrets.decrypt(c, transplanted)


def test_provider_protocol_change_must_remain_compatible(admin):
    provider = create_provider(admin)
    create_model(admin, provider)
    response = admin.put('/api/admin/model-providers/' + provider['id'], json=provider_body(
        revision=provider['revision'], config={'type': 'minimax', 'url': 'https://models.example.test/v1'}))
    assert response.status_code == 400


@pytest.mark.parametrize('url', [
    'file:///etc/passwd', 'https://user:pass@example.test', 'http://127.0.0.1/',
    'http://169.254.169.254/', 'http://10.0.0.1/', 'http://[::1]/',
    'http://[::ffff:127.0.0.1]/', 'https://example.test\\@localhost/',
])
def test_egress_rejects_unsafe_addresses(monkeypatch, url):
    monkeypatch.delenv(egress.EXCEPTIONS_ENV, raising=False)
    with pytest.raises(egress.EgressDenied):
        egress.validate_url(url, resolve=True)


def test_dns_pinning_redirect_and_exact_private_exception(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))])
    calls = []
    def responder(request):
        calls.append((request.url.host, request.headers['host'], request.extensions['sni_hostname']))
        return httpx.Response(302, headers={'Location': 'http://127.0.0.1:9786/private'})
    transport = egress.GuardedTransport(transport=httpx.MockTransport(responder))
    with httpx.Client(transport=transport, follow_redirects=True, trust_env=False) as client:
        with pytest.raises(egress.EgressDenied):
            client.get('https://public.example.test/result')
    assert calls == [('93.184.216.34', 'public.example.test', 'public.example.test')]
    monkeypatch.setenv(egress.EXCEPTIONS_ENV, json.dumps([
        {'scheme': 'http', 'host': '127.0.0.1', 'ip': '127.0.0.1', 'port': 9786}]))
    assert egress.validate_url('http://127.0.0.1:9786/result', resolve=True)[1] == ['127.0.0.1']
    with pytest.raises(egress.EgressDenied):
        egress.validate_url('http://127.0.0.1:9787/result', resolve=True)


def test_cross_origin_redirect_cannot_forward_any_provider_headers(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))])
    calls = []
    def responder(request):
        calls.append(request.url.host)
        return httpx.Response(307, headers={'Location': 'https://other.example.test/steal'})
    transport = egress.GuardedTransport(origin='https://api.example.test', transport=httpx.MockTransport(responder))
    with httpx.Client(transport=transport, follow_redirects=True, trust_env=False,
                      headers={'X-Api-Key': CANARY}) as client:
        with pytest.raises(egress.EgressDenied, match='其他来源'):
            client.post('https://api.example.test/start', json={'prompt': 'test'})
    assert len(calls) == 1


@pytest.mark.parametrize('addresses', [['127.0.0.1'], ['93.184.216.34', '10.0.0.1']])
def test_dns_private_or_mixed_answers_block_before_transport(monkeypatch, addresses):
    monkeypatch.delenv(egress.EXCEPTIONS_ENV, raising=False)
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443)) for ip in addresses])
    calls = []
    transport = egress.GuardedTransport(transport=httpx.MockTransport(lambda req: calls.append(req)))
    with httpx.Client(transport=transport, trust_env=False) as client:
        with pytest.raises(egress.EgressDenied):
            client.get('https://dns.example.test/result')
    assert calls == []
