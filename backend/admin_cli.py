"""Protected operator CLI for the first platform administrator."""
from __future__ import annotations

import argparse
import getpass
import os
import time

from . import identity
from . import store as s


def bootstrap_admin(phone: str, nickname: str, password: str) -> dict:
    normalized = identity.normalize_phone(phone)
    nickname = nickname.strip()
    if not nickname:
        raise ValueError('Administrator nickname cannot be empty.')
    encoded = identity.hash_password(password)
    now = time.time()
    with s.db() as connection:
        connection.execute('SELECT pg_advisory_xact_lock(%s)', (0x4F56435F41444D31,))
        existing_admin = connection.execute(
            "SELECT id FROM users WHERE platform_role='platform_admin' AND is_active LIMIT 1"
        ).fetchone()
        if existing_admin:
            raise RuntimeError('An active platform administrator already exists; bootstrap never resets it.')
        if connection.execute('SELECT 1 FROM users WHERE phone=%s', (normalized,)).fetchone():
            raise RuntimeError('That phone already belongs to an account; bootstrap will not change its role.')
        user_id = s.uid('user-')
        connection.execute(
            '''INSERT INTO users(id,phone,nickname,password_hash,platform_role,is_active,created,updated)
               VALUES(%s,%s,%s,%s,'platform_admin',TRUE,%s,%s)''',
            (user_id, normalized, nickname, encoded, now, now),
        )
        workspace_id = s.uid('workspace-')
        workspace_name = os.environ.get('OVC_BOOTSTRAP_WORKSPACE_NAME', '安影工作室').strip() or '安影工作室'
        connection.execute(
            'INSERT INTO workspaces(id,name,created_by,created,updated) VALUES(%s,%s,%s,%s,%s)',
            (workspace_id, workspace_name, user_id, now, now),
        )
        connection.execute(
            "INSERT INTO workspace_members(workspace_id,user_id,role,created) VALUES(%s,%s,'owner',%s)",
            (workspace_id, user_id, now),
        )
        # P2 had no tenant identity. The first protected bootstrap claims only
        # legacy unassigned rows; it never moves already scoped business data.
        connection.execute(
            'UPDATE productions SET workspace_id=%s WHERE workspace_id IS NULL', (workspace_id,)
        )
        connection.execute('''UPDATE jobs j SET
            production_id=p.production_id,
            workspace_id=pr.workspace_id
            FROM projects p JOIN productions pr ON pr.id=p.production_id
            WHERE p.id=j.project_id AND (j.production_id IS NULL OR j.workspace_id IS NULL)''')
        connection.execute('''UPDATE events e SET
            production_id=p.production_id,workspace_id=pr.workspace_id
            FROM projects p JOIN productions pr ON pr.id=p.production_id
            WHERE p.id=e.project_id AND (e.production_id IS NULL OR e.workspace_id IS NULL)''')
        identity.audit(
            connection, 'platform_admin.bootstrap', 'user', user_id,
            actor_user_id=user_id, workspace_id=workspace_id,
            payload={'method': 'protected_cli', 'legacy_unassigned_claimed': True},
        )
    return {
        'id': user_id, 'phone': normalized, 'nickname': nickname,
        'platform_role': 'platform_admin', 'workspace_id': workspace_id,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='OurVideoCreator protected administration CLI')
    sub = parser.add_subparsers(dest='command', required=True)
    bootstrap = sub.add_parser('bootstrap-admin', help='create the first platform administrator once')
    bootstrap.add_argument('--phone', required=True)
    bootstrap.add_argument('--nickname', required=True)
    bootstrap.add_argument('--password-env', default='OVC_BOOTSTRAP_PASSWORD')
    args = parser.parse_args()
    if args.command == 'bootstrap-admin':
        password = os.environ.get(args.password_env) or getpass.getpass('Password (15–128 chars): ')
        user = bootstrap_admin(args.phone, args.nickname, password)
        print(f"Created platform administrator {user['id']} ({user['phone']}).")
        return 0
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
