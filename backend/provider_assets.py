"""Short-lived signed URLs for media fetched by remote model providers."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import quote, urlparse

from . import store as s


DEFAULT_TTL = 3600


def _secret() -> str:
    candidate = secrets.token_urlsafe(48)
    with s.db() as connection:
        connection.execute(
            '''INSERT INTO settings(key,value) VALUES('provider_asset_signing_secret',%s)
               ON CONFLICT(key) DO NOTHING''', (s.dumps(candidate),),
        )
        row = connection.execute(
            "SELECT value FROM settings WHERE key='provider_asset_signing_secret'"
        ).fetchone()
    return str(json.loads(row['value']))


def signature(asset_id: str, expires: int, method: str = 'GET', purpose: str = 'provider-input') -> str:
    message = f'v1:{method.upper()}:{purpose}:{asset_id}:{int(expires)}'.encode('utf-8')
    return hmac.new(_secret().encode('utf-8'), message, hashlib.sha256).hexdigest()


def valid_signature(asset_id: str, expires: int, supplied: str, method: str = 'GET', purpose: str = 'provider-input') -> bool:
    now = int(time.time())
    if expires < now or expires > now + DEFAULT_TTL + 300:
        return False
    if purpose != 'provider-input' or method.upper() not in {'GET', 'HEAD'}:
        return False
    signed_method = 'GET' if method.upper() == 'HEAD' else method.upper()
    return hmac.compare_digest(signature(asset_id, expires, signed_method, purpose), str(supplied or ''))


def public_asset_url(provider: dict, asset_id: str, ttl: int = DEFAULT_TTL) -> str:
    section = (provider.get('parameters') or {}).get('video') or {}
    base = str(
        section.get('public_base_url')
        or provider.get('public_base_url')
        or s.get_setting('public_base_url', '')
        or ''
    ).strip().rstrip('/')
    parsed = urlparse(base)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username:
        raise ValueError('请在幻场 AI 设置中填写安影的公网访问地址，例如 https://vc.goroc.com')
    expires = int(time.time()) + max(60, min(int(ttl), DEFAULT_TTL))
    purpose = 'provider-input'
    token = signature(asset_id, expires, 'GET', purpose)
    return f'{base}/api/provider-assets/{quote(asset_id, safe="")}?expires={expires}&purpose={purpose}&signature={token}'
