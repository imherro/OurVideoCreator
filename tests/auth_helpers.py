"""Shared P3 identity prerequisite for legacy behavior tests."""
from __future__ import annotations

import time

from backend import identity
from backend import store as s


ADMIN_PHONE = '+8613800000000'
ADMIN_PASSWORD = 'Integration-test-only!'


def ensure_test_admin() -> tuple[str, str]:
    now = time.time()
    with s.db() as connection:
        user = connection.execute('SELECT id FROM users WHERE phone=%s', (ADMIN_PHONE,)).fetchone()
        if not user:
            user_id = s.uid('user-test-admin-')
            connection.execute(
                '''INSERT INTO users(id,phone,nickname,password_hash,platform_role,is_active,created,updated)
                   VALUES(%s,%s,'Test Administrator',%s,'platform_admin',TRUE,%s,%s)''',
                (user_id, ADMIN_PHONE, identity.hash_password(ADMIN_PASSWORD), now, now),
            )
        else:
            user_id = user['id']
            connection.execute(
                '''UPDATE users SET password_hash=%s,platform_role='platform_admin',is_active=TRUE,updated=%s
                   WHERE id=%s''',
                (identity.hash_password(ADMIN_PASSWORD), now, user_id),
            )
        membership = connection.execute(
            "SELECT workspace_id FROM workspace_members WHERE user_id=%s AND role='owner' ORDER BY workspace_id LIMIT 1",
            (user_id,),
        ).fetchone()
        if membership:
            workspace_id = membership['workspace_id']
        else:
            workspace_id = s.uid('workspace-test-')
            connection.execute(
                'INSERT INTO workspaces(id,name,created_by,created,updated) VALUES(%s,%s,%s,%s,%s)',
                (workspace_id, 'Test Workspace', user_id, now, now),
            )
            connection.execute(
                "INSERT INTO workspace_members(workspace_id,user_id,role,created) VALUES(%s,%s,'owner',%s)",
                (workspace_id, user_id, now),
            )
    return user_id, workspace_id


def login_admin(client):
    user_id, workspace_id = ensure_test_admin()
    response = client.post('/api/auth/login', json={'phone': ADMIN_PHONE, 'password': ADMIN_PASSWORD})
    assert response.status_code == 200, response.text
    client.headers.update({'X-CSRF-Token': client.cookies.get(identity.CSRF_COOKIE)})
    return {'user_id': user_id, 'workspace_id': workspace_id}
