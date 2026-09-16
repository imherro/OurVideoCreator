"""Shared P4 synthetic secret and API fixtures; one keyring per isolated test DB."""
import uuid
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from backend import provider_secrets as secrets, store as s
from backend.app import app
from tests.auth_helpers import login_admin

MASTER = Fernet.generate_key().decode('ascii')
CANARY = 'p4-test-' + uuid.uuid4().hex


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setenv(secrets.KEY_ENV, MASTER)
    monkeypatch.setenv(secrets.KEY_ID_ENV, 'p4-test')
    with s.db() as c:
        c.execute('DELETE FROM auth_rate_limits')
    with TestClient(app) as client:
        login_admin(client)
        yield client


def provider_body(**changes):
    return {'revision': 0, 'name': 'P4 Fake', 'enabled': True, 'api_key': CANARY,
            'config': {'type': 'openai', 'url': 'https://models.example.test/v1'}, **changes}


def create_provider(admin, **changes):
    response = admin.post('/api/admin/model-providers', json=provider_body(**changes))
    assert response.status_code == 200
    assert CANARY not in response.text
    return response.json()


def create_model(admin, provider):
    response = admin.post('/api/admin/models', json={
        'revision': 0, 'provider_id': provider['id'], 'kind': 'text', 'published': True,
        'enabled': True, 'default': True, 'definition': {
            'name': 'Safe text', 'upstream_model': 'private-upstream-test-id',
            'defaults': {'max_tokens': 100},
            'rules': {'max_tokens': {'type': 'integer', 'min': 1, 'max': 200}},
            'capabilities': {'max_prompt_length': 1000},
        },
    })
    assert response.status_code == 200, response.text
    return response.json()


def publish_test_model(client, model_id, *, kind='text', provider_type='openai',
                       upstream_model='test-text', url='https://models.example.test/v1',
                       capabilities=None, defaults=None, rules=None, options=None, default=False, api_key=CANARY):
    """Regression fixtures use real admin HTTP writes, never old settings bypasses."""
    provider_id = 'test-provider-' + model_id
    existing = client.get('/api/admin/model-providers').json()['providers']
    old = next((item for item in existing if item['id'] == provider_id), None)
    native_anonymous = provider_type in {'comfy', 'maestro'}
    response = client.put('/api/admin/model-providers/' + provider_id, json={
        'revision': old['revision'] if old else 0, 'name': 'Synthetic ' + model_id,
        'enabled': True, 'api_key': '' if native_anonymous else api_key,
        'config': {'type': provider_type, 'url': url, 'options': options or {},
                   'auth_mode': 'none' if native_anonymous else 'api_key'},
    })
    assert response.status_code == 200, response.text
    existing = client.get('/api/admin/models').json()['models']
    old = next((item for item in existing if item['id'] == model_id), None)
    response = client.put('/api/admin/models/' + model_id, json={
        'revision': old['revision'] if old else 0, 'provider_id': provider_id,
        'kind': kind, 'published': True, 'enabled': True, 'default': default,
        'definition': {'name': 'Synthetic ' + model_id, 'upstream_model': upstream_model,
                       'capabilities': capabilities or {}, 'defaults': defaults or {}, 'rules': rules or {}},
    })
    assert response.status_code == 200, response.text
    return response.json()


def bind_adapter_job(connection, job_id, kind, provider, inp):
    """Protocol regressions retain DB-backed credentials/model resolution.

    Input/reference assembly is tested separately through the public submit API;
    these tests invoke adapters with deliberately crafted protocol cases.
    """
    from backend import model_validation, platform_models
    purpose = 'text' if kind == 'storyboard' else kind
    selected = (provider.get('models') or {}).get(purpose) or provider.get('model') or 'test'
    provider_type = provider['type']
    defaults = {k:v for k,v in provider.get('parameters',{}).get(purpose,{}).items() if k in model_validation.PARAMETERS}
    rules = {k:{'type':'boolean' if type(v) is bool else 'integer' if type(v) is int else 'number' if type(v) is float else 'string'} for k,v in defaults.items()}
    caps = {}
    if purpose in ('image','video') and provider_type not in ('openai','video_api'):
        maximum = 10 if purpose == 'image' else 30 if provider_type == 'runninghub' else 1
        maximum = provider.get('parameters',{}).get(purpose,{}).get('max_references',maximum)
        caps = {'image_reference':True,'max_references':maximum}
        if purpose == 'video' and provider_type in ('volcengine_ark','runninghub','maestro'):
            caps['end_frame']=True
        if purpose == 'video' and provider_type in ('volcengine_ark','runninghub'):
            caps['audio_reference']=True
    options = {k:v for k,v in provider.items() if k in ('parameters','workflow','structured','public_base_url','resource_id')}
    model_id = s.uid('adapter-model-')
    with TestClient(app) as client:
        login_admin(client)
        publish_test_model(client,model_id,kind=purpose,provider_type=provider_type,upstream_model=selected,
            url=provider['url'],capabilities=caps,defaults=defaults,rules=rules,options=options,
            api_key=provider.get('api_key') or CANARY)
    inp.pop('provider',None);inp.pop('model',None);inp['model_id']=model_id
    platform_models.bind_job(connection,job_id,platform_models.resolve(connection,model_id,kind,inp))
    connection.execute('UPDATE jobs SET input=%s WHERE id=%s',(s.dumps(inp),job_id))
