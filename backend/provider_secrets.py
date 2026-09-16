"""Authenticated, context-bound credentials; no fallback or startup key creation.

Only the model service uses this module. Plaintext is returned solely for an
immediate adapter call, never for persistence or an HTTP response.
"""
from __future__ import annotations

import json
import os

from cryptography.fernet import Fernet, InvalidToken

KEY_ENV = 'OVC_PROVIDER_MASTER_KEY'
KEY_ID_ENV = 'OVC_PROVIDER_MASTER_KEY_ID'
_CHECK = b'OurVideoCreator/provider-credentials/v1'
_INIT_LOCK = 0x4F56435F4B455931  # OVC_KEY1


class SecretUnavailable(ValueError):
    """Safe to display; never includes raw key, ciphertext or crypto exception."""


def _cipher():
    raw = os.environ.get(KEY_ENV, '')
    key_id = os.environ.get(KEY_ID_ENV, 'v1').strip()
    if not raw or not key_id or len(key_id) > 80:
        raise SecretUnavailable('模型密钥服务不可用：请配置独立主密钥及其版本标识')
    try:
        return Fernet(raw.encode('ascii')), key_id
    except (ValueError, UnicodeError):
        raise SecretUnavailable('模型密钥服务不可用：主密钥格式错误') from None


def checked_cipher(connection, *, initialize=False):
    cipher, key_id = _cipher()
    row = connection.execute('SELECT * FROM provider_keyring WHERE singleton=1').fetchone()
    if row is None and initialize:
        connection.execute('SELECT pg_advisory_xact_lock(%s)', (_INIT_LOCK,))
        row = connection.execute('SELECT * FROM provider_keyring WHERE singleton=1').fetchone()
        if row is None:
            connection.execute('''INSERT INTO provider_keyring(singleton,key_id,verification_ciphertext)
                VALUES(1,%s,%s)''', (key_id, cipher.encrypt(_CHECK).decode('ascii')))
            return cipher, key_id
    if row is None:
        raise SecretUnavailable('模型密钥服务尚未配置')
    try:
        valid = row['key_id'] == key_id and cipher.decrypt(row['verification_ciphertext'].encode('ascii')) == _CHECK
    except (InvalidToken, ValueError, UnicodeError, TypeError):
        valid = False
    if not valid:
        raise SecretUnavailable('模型密钥服务不可用：主密钥不匹配或校验密文损坏') from None
    return cipher, key_id


def encrypt(connection, provider_id, credential_id, secret):
    if not isinstance(secret, str) or len(secret) > 8192 or '\r' in secret or '\n' in secret:
        raise ValueError('凭证格式无效')
    cipher, key_id = checked_cipher(connection, initialize=True)
    # Binding inside the authenticated envelope prevents valid ciphertext from
    # another provider/version being transplanted and silently used here.
    envelope = json.dumps({'provider_id': provider_id, 'credential_id': credential_id, 'secret': secret})
    return cipher.encrypt(envelope.encode('utf-8')).decode('ascii'), key_id


def decrypt(connection, row):
    if row['state'] == 'revoked':
        raise SecretUnavailable('原凭证已吊销，任务受阻；请核对供应商状态，不会换账号或重新生成')
    cipher, key_id = checked_cipher(connection)
    try:
        if row['key_id'] != key_id:
            raise ValueError()
        envelope = json.loads(cipher.decrypt(row['ciphertext'].encode('ascii')))
        if (envelope.get('provider_id') != row['provider_id'] or
                envelope.get('credential_id') != row['id'] or not isinstance(envelope.get('secret'), str)):
            raise ValueError()
        return envelope['secret']
    except (InvalidToken, ValueError, UnicodeError, TypeError, AttributeError):
        raise SecretUnavailable('原凭证无法解密，模型调用已阻止；请检查主密钥和密文') from None
