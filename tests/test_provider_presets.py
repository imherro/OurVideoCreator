"""Real isolated PostgreSQL; synthetic secrets; network blocked by conftest."""
from copy import deepcopy
import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import platform_models, provider_presets, provider_secrets, store as s
from backend.app import app
from tests.platform_model_helpers import admin, CANARY


def card(admin, name):
    response = admin.get('/api/admin/provider-presets')
    assert response.status_code == 200
    return next(p for p in response.json()['presets'] if p['id'] == name)


def save(admin, name, **body):
    return admin.post('/api/admin/provider-presets/' + name,
                      json={'revision': card(admin, name)['revision'], **body})


@pytest.mark.parametrize('name,count', [('runninghub', 3), ('hc', 2), ('ark', 4), ('speech', 1)])
def test_one_key_publishes_valid_single_user_presets(admin, name, count):
    response = save(admin, name, api_key=CANARY, use_defaults=True)
    assert response.status_code == 200, response.text
    assert CANARY not in response.text
    value = response.json()['preset']
    assert value['configured'] and len(value['models']) == count
    assert all(m['published'] for m in value['models'])
    assert all(m['is_default'] for m in value['models'] if m['primary'])
    public = admin.get('/api/models')
    assert CANARY not in public.text
    ids = {m['id'] for m in public.json()['models']}
    assert all(m['id'] in ids for m in value['models'])
    with s.db() as c:
        for model in value['models']:
            binding = platform_models.resolve(c, model['id'], model['kind'], {'prompt': 'offline test'})
            assert binding is not None


def test_runninghub_uses_explicit_two_origins_and_rotates_both_atomically(admin):
    assert save(admin, 'runninghub', api_key=CANARY).status_code == 200
    old = {p['id']: p for p in admin.get('/api/admin/model-providers').json()['providers']
           if p['id'].startswith('preset-runninghub-')}
    replacement = 'synthetic-rotation-' + uuid.uuid4().hex
    response = save(admin, 'runninghub', api_key=replacement)
    assert response.status_code == 200 and replacement not in response.text
    rows = [p for p in admin.get('/api/admin/model-providers').json()['providers']
            if p['id'].startswith('preset-runninghub-')]
    assert {p['config']['url'] for p in rows} == {'https://llm.runninghub.ai/v1', 'https://www.runninghub.ai'}
    with s.db() as c:
        for p in rows:
            current = c.execute('SELECT * FROM provider_credential_versions WHERE id=%s', (p['credential_version_id'],)).fetchone()
            previous = c.execute('SELECT * FROM provider_credential_versions WHERE id=%s', (old[p['id']]['credential_version_id'],)).fetchone()
            assert provider_secrets.decrypt(c, current) == replacement
            assert previous['state'] == 'retired' and provider_secrets.decrypt(c, previous) == CANARY


def test_keep_key_preserves_custom_model_and_global_defaults(admin):
    assert save(admin, 'ark', api_key=CANARY, use_defaults=True).status_code == 200
    value = next(m for m in admin.get('/api/admin/models').json()['models'] if m['id'] == 'preset-ark-text')
    definition = deepcopy(value['definition']); definition['defaults']['temperature'] = 0.23
    edited = admin.put('/api/admin/models/' + value['id'], json={
        'revision': value['revision'], 'provider_id': value['provider_id'], 'kind': value['kind'],
        'definition': definition, 'enabled': True, 'published': True, 'default': True})
    assert edited.status_code == 200
    before = admin.get('/api/admin/models').json()
    providers_before = admin.get('/api/admin/model-providers').json()['providers']
    assert save(admin, 'ark', use_defaults=False).status_code == 200
    assert admin.get('/api/admin/models').json() == before
    after = admin.get('/api/admin/model-providers').json()['providers']
    assert {p['id']: p['credential_version_id'] for p in after} == {p['id']: p['credential_version_id'] for p in providers_before}


def test_stale_page_cannot_rotate_any_key(admin):
    assert save(admin, 'runninghub', api_key=CANARY).status_code == 200
    revision = card(admin, 'runninghub')['revision']
    assert save(admin, 'runninghub', api_key=CANARY).status_code == 200
    before = admin.get('/api/admin/model-providers').json()
    response = admin.post('/api/admin/provider-presets/runninghub', json={'revision': revision, 'api_key': CANARY})
    assert response.status_code == 409
    assert admin.get('/api/admin/model-providers').json() == before


def test_model_failure_rolls_back_all_provider_and_credential_writes(admin, monkeypatch):
    before = admin.get('/api/admin/model-providers').json()
    catalog_before = admin.get('/api/admin/models').json()
    def fail(*args, **kwargs):
        raise HTTPException(409, 'synthetic model failure')
    monkeypatch.setattr(platform_models, 'save_model', fail)
    response = save(admin, 'runninghub', api_key=CANARY, use_defaults=True)
    assert response.status_code == 409
    assert admin.get('/api/admin/model-providers').json() == before
    assert admin.get('/api/admin/models').json() == catalog_before


def test_empty_key_does_not_erase_and_bad_public_url_rolls_back(admin):
    assert save(admin, 'hc', api_key=CANARY).status_code == 200
    before = admin.get('/api/admin/model-providers').json()
    assert save(admin, 'hc', api_key='').status_code == 400
    response = save(admin, 'hc', public_base_url='http://127.0.0.1:7878')
    assert response.status_code == 400
    assert admin.get('/api/admin/model-providers').json() == before


def test_presets_require_login_and_platform_admin(admin):
    with TestClient(app) as anonymous:
        assert anonymous.get('/api/admin/provider-presets').status_code == 401
    with s.db() as c:
        user = c.execute('SELECT id FROM users WHERE phone=%s', ('+8613800000000',)).fetchone()
        c.execute("UPDATE users SET platform_role='user' WHERE id=%s", (user['id'],))
    try:
        assert admin.get('/api/admin/provider-presets').status_code == 403
        assert admin.post('/api/admin/provider-presets/ark', json={}).status_code == 403
    finally:
        with s.db() as c:
            c.execute("UPDATE users SET platform_role='platform_admin' WHERE id=%s", (user['id'],))
