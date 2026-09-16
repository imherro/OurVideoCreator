"""Personal identity, tenant authorization, CSRF, and audit primitives."""
from __future__ import annotations

import contextvars
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from typing import Iterable

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import HTTPException, Request, Response

from . import store as s


SESSION_COOKIE = 'ovc_session'
CSRF_COOKIE = 'ovc_csrf'
SESSION_SECONDS = 7 * 86400
AUTH_RECHECK_SECONDS = 5
IDENTITY_INVARIANT_LOCK_KEY = 0x4F56435F494E5631
_passwords = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2, type=Type.ID)
_principal: contextvars.ContextVar['Principal | None'] = contextvars.ContextVar('ovc_principal', default=None)


@dataclass(frozen=True)
class Principal:
    user_id: str
    phone: str
    nickname: str
    platform_role: str
    session_hash: str
    expires: float

    @property
    def is_admin(self) -> bool:
        return self.platform_role == 'platform_admin'


def set_current(value: Principal | None):
    return _principal.set(value)


def reset_current(token) -> None:
    _principal.reset(token)


def current(required: bool = True) -> Principal | None:
    value = _principal.get()
    if required and value is None:
        raise HTTPException(401, '请登录工作室')
    return value


def digest(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def hash_password(password: str) -> str:
    validate_password(password)
    return _passwords.hash(password)


def verify_password(encoded: str, password: str) -> bool:
    try:
        return _passwords.verify(encoded, password)
    except (VerifyMismatchError, InvalidHashError, TypeError):
        return False


def validate_password(password: str) -> None:
    if not 15 <= len(password) <= 128:
        raise ValueError('密码长度必须为 15–128 个字符')


def normalize_phone(value: str, default_country: str = '+86') -> str:
    raw = re.sub(r'[\s()\-]', '', str(value or ''))
    if raw.startswith('00'):
        raw = '+' + raw[2:]
    if raw.startswith('+'):
        digits = raw[1:]
    elif raw.startswith('86') and len(raw) == 13:
        digits = raw
    else:
        digits = default_country.lstrip('+') + raw.lstrip('0')
    if not digits.isdigit() or not 8 <= len(digits) <= 15:
        raise ValueError('手机号格式无效')
    return '+' + digits


def _trusted_proxy(client_ip: str) -> bool:
    configured = [item.strip() for item in os.environ.get('OVC_TRUSTED_PROXY_CIDRS', '').split(',') if item.strip()]
    if not configured:
        return False
    try:
        address = ipaddress.ip_address(client_ip)
        return any(address in ipaddress.ip_network(item, strict=False) for item in configured)
    except ValueError:
        return False


def client_ip(request: Request) -> str:
    direct = request.client.host if request.client else 'unknown'
    if _trusted_proxy(direct):
        forwarded = request.headers.get('x-forwarded-for', '').split(',')[0].strip()
        try:
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
    return direct


def secure_cookie(request: Request) -> bool:
    if os.environ.get('OVC_COOKIE_SECURE', '').lower() in {'1', 'true', 'yes'}:
        return True
    direct = request.client.host if request.client else 'unknown'
    if _trusted_proxy(direct):
        return request.headers.get('x-forwarded-proto', '').split(',')[0].strip().lower() == 'https'
    return request.url.scheme == 'https'


def resolve_session(request: Request) -> Principal | None:
    raw = request.cookies.get(SESSION_COOKIE, '')
    if not raw:
        return None
    now = time.time()
    with s.db() as connection:
        row = connection.execute(
            '''SELECT se.token_hash,se.expires,u.id user_id,u.phone,u.nickname,u.platform_role,u.is_active
               FROM sessions se JOIN users u ON u.id=se.user_id
               WHERE se.token_hash=%s AND se.revoked_at IS NULL AND se.expires>%s''',
            (digest(raw), now),
        ).fetchone()
        if not row or not row['is_active']:
            return None
        connection.execute('UPDATE sessions SET last_seen=%s WHERE token_hash=%s', (now, row['token_hash']))
    return Principal(
        row['user_id'], row['phone'], row['nickname'], row['platform_role'], row['token_hash'], row['expires']
    )


def issue_session(connection, response: Response, request: Request, user_id: str) -> str:
    session_token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    now = time.time()
    connection.execute('DELETE FROM sessions WHERE expires<%s OR revoked_at IS NOT NULL', (now,))
    connection.execute(
        '''INSERT INTO sessions(token_hash,user_id,csrf_hash,created,expires,last_seen)
           VALUES(%s,%s,%s,%s,%s,%s)''',
        (digest(session_token), user_id, digest(csrf_token), now, now + SESSION_SECONDS, now),
    )
    flags = dict(max_age=SESSION_SECONDS, secure=secure_cookie(request), samesite='strict', path='/')
    response.set_cookie(SESSION_COOKIE, session_token, httponly=True, **flags)
    response.set_cookie(CSRF_COOKIE, csrf_token, httponly=False, **flags)
    return session_token


def clear_session(response: Response, request: Request) -> None:
    raw = request.cookies.get(SESSION_COOKIE, '')
    if raw:
        with s.db() as connection:
            connection.execute('UPDATE sessions SET revoked_at=%s WHERE token_hash=%s', (time.time(), digest(raw)))
    response.delete_cookie(SESSION_COOKIE, path='/')
    response.delete_cookie(CSRF_COOKIE, path='/')


def require_csrf(request: Request, principal: Principal) -> None:
    supplied = request.headers.get('x-csrf-token', '')
    cookie = request.cookies.get(CSRF_COOKIE, '')
    if not supplied or not cookie or not hmac.compare_digest(supplied, cookie):
        raise HTTPException(403, 'CSRF 校验失败')
    with s.db() as connection:
        row = connection.execute('SELECT csrf_hash FROM sessions WHERE token_hash=%s', (principal.session_hash,)).fetchone()
    if not row or not hmac.compare_digest(row['csrf_hash'], digest(supplied)):
        raise HTTPException(403, 'CSRF 校验失败')


def rate_limit(connection, keys: Iterable[str], *, limit: int = 10, window: int = 300) -> None:
    now = time.time()
    for key in keys:
        row = connection.execute('SELECT * FROM auth_rate_limits WHERE key=%s FOR UPDATE', (key,)).fetchone()
        if not row:
            continue
        if row['blocked_until'] and row['blocked_until'] > now:
            raise HTTPException(429, '尝试次数过多，请稍后重试')
        if row['window_started'] + window <= now:
            connection.execute('DELETE FROM auth_rate_limits WHERE key=%s', (key,))


def record_failure(connection, keys: Iterable[str], *, limit: int = 10, window: int = 300) -> None:
    now = time.time()
    for key in keys:
        connection.execute(
            '''INSERT INTO auth_rate_limits(key,window_started,attempts,blocked_until)
               VALUES(%s,%s,1,NULL)
               ON CONFLICT(key) DO UPDATE SET
                 window_started=CASE WHEN auth_rate_limits.window_started<%s THEN %s ELSE auth_rate_limits.window_started END,
                 attempts=CASE WHEN auth_rate_limits.window_started<%s THEN 1 ELSE auth_rate_limits.attempts+1 END,
                 blocked_until=CASE
                   WHEN (CASE WHEN auth_rate_limits.window_started<%s THEN 1 ELSE auth_rate_limits.attempts+1 END)>=%s
                   THEN %s ELSE auth_rate_limits.blocked_until END''',
            (key, now, now-window, now, now-window, now-window, limit, now+window),
        )


def clear_rate_limit(connection, keys: Iterable[str]) -> None:
    for key in keys:
        connection.execute('DELETE FROM auth_rate_limits WHERE key=%s', (key,))


def lock_identity_invariants(connection) -> None:
    """Serialize mutations that can change admin or tenant membership invariants."""
    connection.execute('SELECT pg_advisory_xact_lock(%s)', (IDENTITY_INVARIANT_LOCK_KEY,))


def audit(connection, action: str, target_type: str, target_id: str | None = None, *,
          actor_user_id: str | None = None, workspace_id: str | None = None,
          production_id: str | None = None, payload: dict | None = None) -> None:
    actor = actor_user_id or (current(False).user_id if current(False) else None)
    connection.execute(
        '''INSERT INTO audit_events(actor_user_id,action,target_type,target_id,workspace_id,production_id,payload,created)
           VALUES(%s,%s,%s,%s,%s,%s,%s,%s)''',
        (actor, action, target_type, target_id, workspace_id, production_id, s.dumps(payload or {}), time.time()),
    )


_ROLE_LEVEL = {'viewer': 1, 'editor': 2, 'manager': 3}


def production_role(connection, principal: Principal, production_id: str) -> tuple[str | None, str | None]:
    row = connection.execute(
        '''SELECT wm.role workspace_role,pm.role production_role
           FROM productions p
           LEFT JOIN workspace_members wm ON wm.workspace_id=p.workspace_id AND wm.user_id=%s
           LEFT JOIN production_members pm ON pm.production_id=p.id AND pm.user_id=%s
           WHERE p.id=%s''',
        (principal.user_id, principal.user_id, production_id),
    ).fetchone()
    if not row:
        return None, None
    return row['workspace_role'], row['production_role']


def can_production(connection, principal: Principal, production_id: str, needed: str = 'viewer') -> bool:
    workspace_role, role = production_role(connection, principal, production_id)
    if workspace_role == 'owner':
        return True
    if workspace_role is None:
        return False
    return _ROLE_LEVEL.get(role or '', 0) >= _ROLE_LEVEL[needed]


def require_production(connection, principal: Principal, production_id: str, needed: str = 'viewer') -> None:
    workspace_membership, production_membership = production_role(connection, principal, production_id)
    visible = workspace_membership == 'owner' or (
        workspace_membership is not None and production_membership is not None
    )
    if not visible:
        # Do not disclose that a cross-workspace or unassigned Production ID exists.
        raise HTTPException(404, '资源不存在或无权访问')
    level = 3 if workspace_membership == 'owner' else _ROLE_LEVEL.get(production_membership or '', 0)
    if level < _ROLE_LEVEL[needed]:
        raise HTTPException(403, '当前作品角色无权执行此操作')


def workspace_role(connection, principal: Principal, workspace_id: str) -> str | None:
    row = connection.execute(
        'SELECT role FROM workspace_members WHERE workspace_id=%s AND user_id=%s',
        (workspace_id, principal.user_id),
    ).fetchone()
    return row['role'] if row else None


def require_workspace_owner(connection, principal: Principal, workspace_id: str) -> None:
    if workspace_role(connection, principal, workspace_id) != 'owner':
        raise HTTPException(403, '仅团队 owner 可执行此操作')


def production_for_resource(connection, kind: str, resource_id: str) -> str | None:
    queries = {
        'project': 'SELECT production_id FROM projects WHERE id=%s',
        'asset': 'SELECT production_id FROM assets WHERE id=%s',
        'job': '''SELECT COALESCE(j.production_id,p.production_id) production_id
                  FROM jobs j LEFT JOIN projects p ON p.id=j.project_id WHERE j.id=%s''',
        'source': 'SELECT production_id FROM source_documents WHERE id=%s',
        'chapter': '''SELECT sd.production_id FROM source_chapters sc
                      JOIN source_documents sd ON sd.id=sc.source_id WHERE sc.id=%s''',
        'revision': '''SELECT p.production_id FROM revisions r JOIN projects p ON p.id=r.project_id WHERE r.id=%s''',
    }
    query = queries.get(kind)
    if not query:
        return None
    row = connection.execute(query, (resource_id,)).fetchone()
    return row['production_id'] if row else None


def visible_production_ids(connection, principal: Principal) -> list[str]:
    rows = connection.execute(
        '''SELECT DISTINCT p.id FROM productions p
           LEFT JOIN workspace_members wm ON wm.workspace_id=p.workspace_id AND wm.user_id=%s
           LEFT JOIN production_members pm ON pm.production_id=p.id AND pm.user_id=%s
           WHERE wm.user_id IS NOT NULL AND (wm.role='owner' OR pm.user_id IS NOT NULL)''',
        (principal.user_id, principal.user_id),
    ).fetchall()
    return [row['id'] for row in rows]


def public_user(row) -> dict:
    return {'id': row['id'], 'nickname': row['nickname'], 'platform_role': row.get('platform_role', 'user')}


def json_value(value):
    return json.loads(value) if isinstance(value, str) else value


def authorize_request(request: Request, principal: Principal) -> None:
    """Enforce the legacy route surface before its endpoint executes.

    List endpoints still apply scoped SQL filters in their endpoint. Detail and
    mutation endpoints are denied here so a newly added UI cannot bypass the
    same resource lookup.
    """
    path = request.url.path
    method = request.method
    if path.startswith('/api/admin/'):
        if not principal.is_admin:
            raise HTTPException(403, '需要平台管理员权限')
        return
    if ((path == '/api/settings' and method != 'GET') or
            (path.startswith('/api/providers/') and method != 'GET')):
        if not principal.is_admin:
            raise HTTPException(403, '需要平台管理员权限')
        return
    if path.startswith('/api/prompt-library/') and method != 'GET':
        if not principal.is_admin:
            raise HTTPException(403, '需要平台管理员权限')
        return

    production_match = re.match(r'^/api/productions/([^/]+)(?:/(.*))?$', path)
    project_match = re.match(r'^/api/projects/([^/]+)(?:/(.*))?$', path)
    job_match = re.match(r'^/api/jobs/([^/]+)(?:/(.*))?$', path)
    asset_match = re.match(r'^/api/assets/([^/]+)/file$', path)
    with s.db() as connection:
        if production_match:
            production_id, suffix = production_match.group(1), production_match.group(2) or ''
            needed = 'viewer'
            if method not in {'GET', 'HEAD', 'OPTIONS'}:
                needed = 'editor'
            if method == 'DELETE' or (method == 'PATCH' and not suffix):
                needed = 'manager'
            if method == 'POST' and suffix == 'episodes':
                needed = 'manager'
            if method == 'POST' and suffix == 'chapters/trash':
                needed = 'manager'
            if suffix.endswith('/approve') or suffix.endswith('/needs-changes'):
                needed = 'manager'
            require_production(connection, principal, production_id, needed)
            return
        if project_match:
            project_id, suffix = project_match.group(1), project_match.group(2) or ''
            production_id = production_for_resource(connection, 'project', project_id)
            if not production_id:
                raise HTTPException(404, '项目不存在')
            needed = 'viewer'
            if method not in {'GET', 'HEAD', 'OPTIONS'}:
                needed = 'editor'
            if method in {'PUT', 'DELETE'} and not suffix:
                needed = 'manager'
            if method == 'DELETE' and suffix.startswith('assets/'):
                needed = 'manager'
            require_production(connection, principal, production_id, needed)
            # Nested asset IDs must belong to the same Production, not merely
            # to some Production the actor can access.
            nested = re.match(r'^assets/([^/]+)$', suffix)
            if nested:
                nested_production = production_for_resource(connection, 'asset', nested.group(1))
                if nested_production != production_id:
                    raise HTTPException(404, '素材不存在')
            return
        if job_match:
            job_id, suffix = job_match.group(1), job_match.group(2) or ''
            production_id = production_for_resource(connection, 'job', job_id)
            if not production_id:
                raise HTTPException(404, '任务不存在')
            if method == 'GET':
                needed = 'viewer'
            else:
                job = connection.execute('SELECT actor_user_id FROM jobs WHERE id=%s', (job_id,)).fetchone()
                needed = 'editor' if job and job['actor_user_id'] == principal.user_id else 'manager'
            require_production(connection, principal, production_id, needed)
            return
        if asset_match:
            production_id = production_for_resource(connection, 'asset', asset_match.group(1))
            if not production_id:
                raise HTTPException(404, '素材不存在')
            require_production(connection, principal, production_id, 'viewer')
            return
        trash_match = re.match(r'^/api/trash/([^/]+)/([^/]+)/restore$', path)
        if trash_match:
            kind, item_id = trash_match.groups()
            resource_kind = {'project': 'project', 'asset': 'asset', 'source': 'source', 'chapter': 'chapter'}.get(kind)
            production_id = production_for_resource(connection, resource_kind or '', item_id)
            if not production_id:
                raise HTTPException(404, '回收站条目不存在')
            require_production(connection, principal, production_id, 'manager')
