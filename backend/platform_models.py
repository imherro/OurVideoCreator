"""Single PostgreSQL source for platform models and frozen job identities."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

from fastapi import HTTPException

from . import identity, model_validation as validation, provider_secrets, store as s
from .provider_egress import validate_url


def _admin():
    actor = identity.current()
    if not actor.is_admin:
        raise HTTPException(403, '需要平台管理员权限')
    return actor.user_id


def _revision(body, row):
    if type(body.get('revision')) is not int or body['revision'] != (row['revision'] if row else 0):
        raise HTTPException(409, '配置已更新或版本无效，请刷新后重试；当前草稿仍保留')


def _bool(body, key, default):
    value = body.get(key, default)
    if type(value) is not bool:
        raise ValueError('启停/发布状态必须是布尔值')
    return value


def _provider(connection, provider_id, *, lock=False):
    row = connection.execute('SELECT * FROM model_providers WHERE id=%s' + (' FOR UPDATE' if lock else ''),
                             (provider_id,)).fetchone()
    if row is None:
        raise HTTPException(404, '模型服务不存在')
    return row


def _credential(connection, credential_id):
    row = connection.execute('SELECT * FROM provider_credential_versions WHERE id=%s', (credential_id,)).fetchone()
    if row is None:
        raise provider_secrets.SecretUnavailable('模型凭证不可用，未回落旧配置')
    return row


def _provider_view(connection, row):
    config = connection.execute('SELECT config FROM provider_config_versions WHERE id=%s',
                                (row['config_version_id'],)).fetchone()
    credentials = connection.execute('''SELECT id,key_id,state,created,revoked_at
        FROM provider_credential_versions WHERE provider_id=%s ORDER BY created DESC,id''', (row['id'],)).fetchall()
    return {**dict(row), 'config': json.loads(config['config']) if config else None,
            'credentials': [dict(item) for item in credentials],
            'api_key_set': any(item['state'] == 'current' for item in credentials)}


def admin_providers():
    _admin()
    with s.db() as connection:
        rows = connection.execute('SELECT * FROM model_providers ORDER BY created,id').fetchall()
        try:
            provider_secrets.checked_cipher(connection)
            key_status = 'ready'
        except provider_secrets.SecretUnavailable:
            key_status = 'unavailable'
        return {'providers': [_provider_view(connection, row) for row in rows], 'key_service': key_status}


def save_provider(provider_id, body):
    actor = _admin()
    validation._object(body, {'revision', 'name', 'enabled', 'config', 'api_key'}, '模型服务')
    name = validation._string(body.get('name'), '服务名称', 100)
    config = validation.provider_config(body.get('config'))
    enabled = _bool(body, 'enabled', True)
    with s.db() as connection:
        # Low-volume platform mutations share a transaction lock, including
        # creates, so same-ID races return a clean revision conflict.
        connection.execute('SELECT pg_advisory_xact_lock(%s)', (0x4F56435F4D444C31,))
        row = connection.execute('SELECT * FROM model_providers WHERE id=%s FOR UPDATE', (provider_id,)).fetchone()
        _revision(body, row)
        if row:
            for existing in connection.execute('''SELECT m.kind,v.definition FROM model_catalog m
                JOIN model_versions v ON v.id=m.version_id WHERE v.provider_id=%s''', (provider_id,)):
                validation.model_definition(json.loads(existing['definition']), config, existing['kind'])
        old_credential = _credential(connection, row['credential_version_id']) if row else None
        # Even a replacement must prove possession of the original master key;
        # a wrong deployment key cannot create a second, divergent keyring.
        if row:
            provider_secrets.checked_cipher(connection)
        credential_id = row['credential_version_id'] if row else None
        replacement = 'api_key' in body
        if not row and not replacement:
            raise ValueError('新建服务需要显式录入凭证；无认证服务请显式留空')
        if replacement:
            if config['auth_mode'] == 'api_key' and not body['api_key']:
                raise ValueError('该服务的 API Key 不能为空；省略字段表示保持原凭证')
            if config['auth_mode'] == 'none' and body['api_key']:
                raise ValueError('无认证服务不能保存 API Key')
            credential_id = s.uid('credential-')
            ciphertext, key_id = provider_secrets.encrypt(connection, provider_id, credential_id, body['api_key'])
        else:
            plaintext = provider_secrets.decrypt(connection, old_credential)
            if bool(plaintext) != (config['auth_mode'] == 'api_key'):
                raise ValueError('更改认证方式时必须显式替换凭证')
            del plaintext
        now = time.time()
        if row is None:
            connection.execute('''INSERT INTO model_providers(id,name,enabled,revision,created,updated)
                VALUES(%s,%s,%s,1,%s,%s)''', (provider_id, name, enabled, now, now))
        config_id = s.uid('provider-config-')
        connection.execute('''INSERT INTO provider_config_versions(id,provider_id,config,created,created_by)
            VALUES(%s,%s,%s,%s,%s)''', (config_id, provider_id, s.dumps(config), now, actor))
        if replacement:
            connection.execute("UPDATE provider_credential_versions SET state='retired' WHERE provider_id=%s AND state='current'", (provider_id,))
            connection.execute('''INSERT INTO provider_credential_versions(id,provider_id,key_id,ciphertext,state,created,created_by)
                VALUES(%s,%s,%s,%s,'current',%s,%s)''', (credential_id, provider_id, key_id, ciphertext, now, actor))
        connection.execute('''UPDATE model_providers SET name=%s,enabled=%s,revision=%s,
            config_version_id=%s,credential_version_id=%s,updated=%s WHERE id=%s''',
            (name, enabled, (row['revision'] + 1) if row else 1, config_id, credential_id, now, provider_id))
        identity.audit(connection, 'model_provider.save', 'model_provider', provider_id,
                       payload={'config_version_id': config_id, 'credential_version_id': credential_id,
                                'key_replaced': replacement, 'enabled': enabled})
        return _provider_view(connection, _provider(connection, provider_id))


def revoke_credential(provider_id, credential_id):
    _admin()
    with s.db() as connection:
        row = _provider(connection, provider_id, lock=True)
        credential = _credential(connection, credential_id)
        if credential['provider_id'] != provider_id:
            raise HTTPException(404, '凭证版本不存在')
        if credential['state'] != 'revoked':
            connection.execute("UPDATE provider_credential_versions SET state='revoked',revoked_at=%s WHERE id=%s",
                               (time.time(), credential_id))
            connection.execute('UPDATE model_providers SET revision=revision+1,updated=%s WHERE id=%s',
                               (time.time(), provider_id))
            identity.audit(connection, 'model_credential.revoke', 'model_provider', provider_id,
                           payload={'credential_version_id': credential_id})
        return _provider_view(connection, _provider(connection, row['id']))


def check_provider(provider_id):
    _admin()
    with s.db() as connection:
        row = _provider(connection, provider_id)
        config = json.loads(connection.execute('SELECT config FROM provider_config_versions WHERE id=%s',
                                               (row['config_version_id'],)).fetchone()['config'])
        provider_secrets.decrypt(connection, _credential(connection, row['credential_version_id']))
        validate_url(config['url'], resolve=True)
    # This deliberately does NOT call existing adapters' catalog methods, some
    # of which return static lists. No network auth or generation is claimed.
    return {'status': 'unverified', 'format_valid': True, 'authentication_verified': False,
            'generation_verified': False, 'message': '配置、密文和地址解析检查通过；未验证上游鉴权，未发起生成或素材上传'}


def _model_view(connection, row, *, private=False):
    version = connection.execute('SELECT * FROM model_versions WHERE id=%s', (row['version_id'],)).fetchone()
    definition = json.loads(version['definition'])
    safe = {key: definition[key] for key in ('name', 'capabilities', 'defaults', 'rules')}
    config = connection.execute('''SELECT cv.config FROM model_providers p
        JOIN provider_config_versions cv ON cv.id=p.config_version_id WHERE p.id=%s''',
        (version['provider_id'],)).fetchone()
    result = {'id': row['id'], 'kind': row['kind'], 'type': json.loads(config['config'])['type'], **safe}
    if private:
        result.update(revision=row['revision'], published=row['published'], enabled=row['enabled'],
                      version_id=row['version_id'], provider_id=version['provider_id'], definition=definition)
    return result


def admin_models():
    _admin()
    with s.db() as connection:
        return {'models': [_model_view(connection, row, private=True)
                           for row in connection.execute('SELECT * FROM model_catalog ORDER BY created,id').fetchall()],
                'defaults': {row['kind']: row['model_id'] for row in connection.execute('SELECT * FROM model_defaults')}}


def save_model(model_id, body):
    actor = _admin()
    validation._object(body, {'revision', 'kind', 'provider_id', 'definition', 'published', 'enabled', 'default'}, '平台模型')
    with s.db() as connection:
        connection.execute('SELECT pg_advisory_xact_lock(%s)', (0x4F56435F4D444C31,))
        row = connection.execute('SELECT * FROM model_catalog WHERE id=%s FOR UPDATE', (model_id,)).fetchone()
        _revision(body, row)
        kind = body.get('kind')
        if row and kind != row['kind']:
            raise ValueError('已有模型用途不可改变；请新建另一个平台模型')
        provider = _provider(connection, body.get('provider_id'), lock=True)
        config = json.loads(connection.execute('SELECT config FROM provider_config_versions WHERE id=%s',
                                               (provider['config_version_id'],)).fetchone()['config'])
        definition = validation.model_definition(body.get('definition'), config, kind)
        published, enabled = _bool(body, 'published', False), _bool(body, 'enabled', True)
        is_default = _bool(body, 'default', False)
        if published:
            provider_secrets.decrypt(connection, _credential(connection, provider['credential_version_id']))
        if is_default and not (published and enabled and provider['enabled']):
            raise ValueError('默认模型必须已发布且服务/模型均启用')
        now, version_id = time.time(), s.uid('model-version-')
        if row is None:
            connection.execute('''INSERT INTO model_catalog(id,kind,published,enabled,revision,created,updated)
                VALUES(%s,%s,%s,%s,1,%s,%s)''', (model_id, kind, published, enabled, now, now))
        connection.execute('''INSERT INTO model_versions(id,model_id,provider_id,definition,created,created_by)
            VALUES(%s,%s,%s,%s,%s,%s)''', (version_id, model_id, provider['id'], s.dumps(definition), now, actor))
        connection.execute('''UPDATE model_catalog SET version_id=%s,published=%s,enabled=%s,revision=%s,updated=%s WHERE id=%s''',
                           (version_id, published, enabled, (row['revision'] + 1) if row else 1, now, model_id))
        if is_default:
            connection.execute('''INSERT INTO model_defaults(kind,model_id) VALUES(%s,%s)
                ON CONFLICT(kind) DO UPDATE SET model_id=excluded.model_id''', (kind, model_id))
        elif 'default' in body or not (published and enabled):
            connection.execute('DELETE FROM model_defaults WHERE kind=%s AND model_id=%s', (kind, model_id))
        identity.audit(connection, 'platform_model.save', 'platform_model', model_id,
                       payload={'model_version_id': version_id, 'provider_id': provider['id'],
                                'published': published, 'enabled': enabled, 'default': is_default})
        saved = connection.execute('SELECT * FROM model_catalog WHERE id=%s', (model_id,)).fetchone()
        return _model_view(connection, saved, private=True)


def catalog(connection=None):
    if connection is None:
        with s.db() as current:
            return catalog(current)
    try:
        provider_secrets.checked_cipher(connection)
    except provider_secrets.SecretUnavailable:
        return {'models': [], 'defaults': {}, 'status': 'unavailable', 'message': '平台模型服务尚未配置或密钥不可用，请联系管理员'}
    rows = connection.execute('''SELECT m.* FROM model_catalog m
        JOIN model_versions v ON v.id=m.version_id JOIN model_providers p ON p.id=v.provider_id
        JOIN provider_credential_versions k ON k.id=p.credential_version_id
        WHERE m.published AND m.enabled AND p.enabled AND k.state='current' ORDER BY m.created,m.id''').fetchall()
    models = []
    for row in rows:
        provider = connection.execute('''SELECT p.* FROM model_providers p
            JOIN model_versions v ON v.provider_id=p.id WHERE v.id=%s''', (row['version_id'],)).fetchone()
        try:
            config = json.loads(connection.execute('SELECT config FROM provider_config_versions WHERE id=%s',
                                (provider['config_version_id'],)).fetchone()['config'])
            validation.supported_protocol(config, row['kind'])
            provider_secrets.decrypt(connection, _credential(connection, provider['credential_version_id']))
        except (provider_secrets.SecretUnavailable, ValueError):
            continue
        models.append(_model_view(connection, row))
    ids = {item['id'] for item in models}
    defaults = {row['kind']: row['model_id'] for row in connection.execute('SELECT * FROM model_defaults') if row['model_id'] in ids}
    return {'models': models, 'defaults': defaults, 'status': 'ready' if models else 'empty',
            'message': '' if models else '暂无已发布且可用的平台模型；不会自动切换服务'}


@dataclass(frozen=True)
class Binding:
    model_id: str
    model_version_id: str
    config_version_id: str
    credential_version_id: str
    parameters: dict
    image_spec: dict | None = None


def resolve(connection, model_id, kind, inp, *, document=None, node_id=None, preview=False):
    validation.reject_private_overrides(inp)
    kind = 'text' if kind == 'storyboard' else kind
    row = connection.execute('''SELECT m.* FROM model_catalog m WHERE id=%s FOR SHARE''', (model_id,)).fetchone()
    if not row or not row['published'] or not row['enabled']:
        raise ValueError('所选平台模型未发布或已停用；不会自动切换其他服务')
    if kind != row['kind']:
        raise ValueError('平台模型用途与任务不匹配')
    version = connection.execute('SELECT * FROM model_versions WHERE id=%s', (row['version_id'],)).fetchone()
    provider = connection.execute('SELECT * FROM model_providers WHERE id=%s FOR SHARE', (version['provider_id'],)).fetchone()
    if not provider['enabled']:
        raise ValueError('模型服务已停用；不会创建新任务')
    config = json.loads(connection.execute('SELECT config FROM provider_config_versions WHERE id=%s',
                        (provider['config_version_id'],)).fetchone()['config'])
    validation.supported_protocol(config, kind)
    credential = _credential(connection, provider['credential_version_id'])
    if credential['state'] != 'current':
        raise provider_secrets.SecretUnavailable('当前模型凭证不可用')
    provider_secrets.decrypt(connection, credential)
    definition = json.loads(version['definition'])
    if not preview:
        validate_capabilities(definition['capabilities'], inp)
    submitted = inp.get('parameters', {})
    if not isinstance(submitted,dict):
        raise ValueError('生成参数必须为对象')
    submitted = dict(submitted)
    for name in validation.PARAMETERS:
        if name in inp:
            if name in submitted and submitted[name] != inp[name]:
                raise ValueError('生成参数存在重复冲突')
            submitted[name] = inp[name]
    spec = None
    if kind == 'image':
        from .image_settings import resolve as image_settings
        normalized, spec = image_settings(definition, submitted, document or {}, node_id, config,
            inp.get('imageSettings'), freeze=not preview)
    else:
        normalized = validation.shot_parameters(definition, submitted, kind, document or {}, node_id)
    return Binding(row['id'], row['version_id'], provider['config_version_id'], credential['id'], normalized, spec)


def validate_capabilities(caps, inp):
    if inp.get('voice_samples') and not (caps.get('voice_sample_reference') and caps.get('audio_reference')):
        raise ValueError('所选平台模型未发布音色样本参考能力')
    if (inp.get('generation_mode') or {}).get('requested') == 'multimodal' and not caps.get('multimodal_reference'):
        raise ValueError('所选平台模型未发布多模态参考能力')
    if inp.get('motion_reference') and not caps.get('video_reference'):
        raise ValueError('所选平台模型未发布视频参考能力')
    prompt = inp.get('prompt', '')
    if not isinstance(prompt, str) or len(prompt) > caps.get('max_prompt_length', 240000):
        raise ValueError('提示词超过平台模型允许长度')
    refs = inp.get('asset_ids', [])
    if not isinstance(refs, list) or any(not isinstance(aid, str) for aid in refs):
        raise ValueError('参考素材必须为素材 ID 列表')
    sources = inp.get('image_reference_sources')
    count = max(len(refs), len(sources) if isinstance(sources, list) else 0)
    if count and (not caps.get('image_reference') or count > caps.get('max_references', 1)):
        raise ValueError('所选平台模型不支持这些参考图或数量超限')
    if caps.get('requires_reference') and not count:
        raise ValueError('所选平台模型需要参考图')
    if inp.get('end_asset_id') and (not caps.get('end_frame') or not count):
        raise ValueError('所选平台模型不支持尾帧或缺少首帧')
    if (inp.get('audio_asset_ids') or inp.get('audio_reference_ids') or inp.get('dialogue_audio_asset_ids') or inp.get('dialogue_audio')) and not caps.get('audio_reference'):
        raise ValueError('所选平台模型不支持参考音频')


def compiler_catalog():
    """Safe platform models for pure compilers; never a credential/URL source."""
    value = catalog()
    return [{**model, 'is_default': value['defaults'].get(model['kind']) == model['id']}
            for model in value['models']]


def config_for_binding(connection, binding, *, remote=False, decrypt=False):
    row = {'model_version_id': binding.model_version_id, 'config_version_id': binding.config_version_id,
           'credential_version_id': binding.credential_version_id, 'parameters': s.dumps(binding.parameters)}
    return _load_binding(connection, row, remote=remote, decrypt=decrypt)


def bind_job(connection, job_id, binding):
    connection.execute('''INSERT INTO job_private(job_id,provider,model_version_id,config_version_id,credential_version_id,parameters)
        VALUES(%s,'{}',%s,%s,%s,%s)''',
        (job_id, binding.model_version_id, binding.config_version_id, binding.credential_version_id, s.dumps(binding.parameters)))


def load_job_provider(connection, job_id, *, remote=False, decrypt=True):
    row = connection.execute('SELECT * FROM job_private WHERE job_id=%s', (job_id,)).fetchone()
    if not row or not row['model_version_id'] or not row['config_version_id'] or not row['credential_version_id']:
        raise ValueError('任务缺少受控模型版本，已阻止旧配置回退；请人工核对后重新提交')
    return _load_binding(connection, row, remote=remote, decrypt=decrypt)


def _load_binding(connection, row, *, remote, decrypt):
    model_version = connection.execute('SELECT * FROM model_versions WHERE id=%s', (row['model_version_id'],)).fetchone()
    config_version = connection.execute('SELECT * FROM provider_config_versions WHERE id=%s', (row['config_version_id'],)).fetchone()
    credential = _credential(connection, row['credential_version_id'])
    if len({model_version['provider_id'], config_version['provider_id'], credential['provider_id']}) != 1:
        raise ValueError('任务模型配置身份不匹配，调用已阻止')
    provider = _provider(connection, config_version['provider_id'])
    model = connection.execute('SELECT * FROM model_catalog WHERE id=%s', (model_version['model_id'],)).fetchone()
    if not remote and (not provider['enabled'] or not model['enabled'] or not model['published']):
        raise ValueError('模型或服务已停用，排队任务不能发起新调用')
    if credential['state'] == 'revoked':
        raise provider_secrets.SecretUnavailable('任务原凭证已吊销；不会换账号查询或重新生成')
    config, definition = json.loads(config_version['config']), json.loads(model_version['definition'])
    validation.supported_protocol(config, model['kind'])
    job_parameters = json.loads(row.get('parameters') or '{}')
    if not remote:
        # Old queued jobs must not reach adapter fallback defaults either. Use
        # only their frozen snapshot; do not silently refill it at execution.
        validation.parameters({**definition, 'defaults': {}}, job_parameters)
    result = {**config['options'], 'id': provider['id'], 'name': provider['name'], 'type': config['type'],
              'url': config['url'], 'kind': model['kind'], 'model': definition['upstream_model'],
              'models': {model['kind']: definition['upstream_model']}, 'local': False,
              'config_version_id': config_version['id'], 'credential_version_id': credential['id'],
              'model_version_id': model_version['id'], 'model_id': model['id'],
              'capabilities': definition['capabilities'],
              'job_parameters': job_parameters}
    if decrypt:
        result['api_key'] = provider_secrets.decrypt(connection, credential)
    return result


def check_job_call(job_id):
    """Recheck revocation/disable before each authenticated network request."""
    with s.db() as connection:
        job=connection.execute('SELECT provider_job_id FROM jobs WHERE id=%s',(job_id,)).fetchone()
        if not job:
            raise ValueError('模型任务不存在')
        load_job_provider(connection,job_id,remote=bool(job['provider_job_id']))
