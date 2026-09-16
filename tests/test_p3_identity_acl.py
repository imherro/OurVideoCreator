from __future__ import annotations

import io
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import uuid
from contextlib import ExitStack
from pathlib import Path

import psycopg
import pytest
import httpx
import uvicorn
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from psycopg import sql
from sqlalchemy.engine import make_url
from starlette.requests import Request

from backend import identity
from backend import store as s
from backend.app import UserStateUpdate, app, update_user_state
from backend.provider_assets import public_asset_url, valid_signature
from scripts.audit_routes import export_routes, guard_exit_code, unclassified_api_routes
from tests.auth_helpers import login_admin
from tests.postgres_test_db import _assert_safe_target


PASSWORD = "P3-integration-password!"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def clients():
    with ExitStack() as stack:
        def make():
            return stack.enter_context(TestClient(app))
        yield make


@pytest.fixture(autouse=True)
def clear_auth_rate_limits():
    with s.db() as connection:
        connection.execute("DELETE FROM auth_rate_limits")


@pytest.fixture
def admin(clients):
    client = clients()
    login_admin(client)
    return client


def phone() -> str:
    # A stable CN-shaped test number whose normalized representation is unique.
    return "1" + str(uuid.uuid4().int % 10_000_000_000).zfill(10)


def invite(admin: TestClient, **payload) -> dict:
    response = admin.post("/api/admin/invitations", json={"expires_hours": 48, **payload})
    assert response.status_code == 200, response.text
    return response.json()


def register(admin: TestClient, clients, *, nickname: str, number: str | None = None):
    client = clients()
    raw = invite(admin)["token"]
    number = number or phone()
    response = client.post("/api/auth/register", json={
        "invitation_token": raw,
        "phone": number,
        "nickname": nickname,
        "password": PASSWORD,
    })
    assert response.status_code == 200, response.text
    client.headers.update({"X-CSRF-Token": client.cookies.get(identity.CSRF_COOKIE)})
    return client, response.json()["user"], number


def add_workspace(admin: TestClient, owner_id: str, name: str) -> str:
    response = admin.post("/api/admin/workspaces", json={"name": name, "owner_user_id": owner_id})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def add_team_member(owner: TestClient, workspace_id: str, user_id: str, role: str = "member"):
    response = owner.put(
        f"/api/workspaces/{workspace_id}/members/{user_id}", json={"role": role}
    )
    assert response.status_code == 200, response.text


def add_production_member(owner: TestClient, production_id: str, user_id: str, role: str):
    response = owner.put(
        f"/api/productions/{production_id}/members/{user_id}", json={"role": role}
    )
    assert response.status_code == 200, response.text


def create_project(owner: TestClient, workspace_id: str, name: str) -> dict:
    response = owner.post("/api/projects", json={"name": name, "workspace_id": workspace_id})
    assert response.status_code == 200, response.text
    return response.json()


def png_bytes() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (8, 8), "#1d3446").save(stream, format="PNG")
    return stream.getvalue()


def test_auth01_protected_cli_bootstraps_once_and_public_setup_is_retired(tmp_path):
    admin_url = make_url(os.environ["OVC_TEST_ADMIN_URL"])
    database_name = "ovc_test_p3_bootstrap_" + uuid.uuid4().hex[:12]
    _assert_safe_target(database_name)
    admin_dsn = admin_url.set(drivername="postgresql").render_as_string(hide_password=False)
    target = admin_url.set(database=database_name, drivername="postgresql+psycopg")
    target_url = target.render_as_string(hide_password=False)
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    env = {
        **os.environ,
        "OVC_DATABASE_URL": target_url,
        "MVC_DATA_DIR": str(tmp_path / "bootstrap-media"),
        "OVC_BOOTSTRAP_PASSWORD": PASSWORD,
    }
    try:
        baseline = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "0001_postgresql_baseline"],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=40,
        )
        assert baseline.returncode == 0, baseline.stderr
        with psycopg.connect(target.set(drivername="postgresql").render_as_string(hide_password=False)) as connection:
            now = time.time()
            connection.execute(
                "INSERT INTO productions(id,name,shared_context,created,updated) VALUES('legacy-p','Legacy','{}',%s,%s)",
                (now, now),
            )
            connection.execute(
                "INSERT INTO projects(id,name,document,created,updated,production_id,episode_no,episode_title) "
                "VALUES('legacy-e','Legacy EP','{}',%s,%s,'legacy-p',1,'Legacy EP')", (now, now),
            )
            connection.execute(
                "INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated) "
                "VALUES('legacy-j','legacy-sub','legacy-e','n','text','succeeded','{}',%s,%s)", (now, now),
            )
            connection.execute(
                "INSERT INTO events(project_id,payload,created) VALUES('legacy-e','{}',%s)", (now,),
            )
        migrated = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=40,
        )
        assert migrated.returncode == 0, migrated.stderr
        first = subprocess.run(
            [sys.executable, "-m", "backend.admin_cli", "bootstrap-admin",
             "--phone", "13800009999", "--nickname", "Initial Operator"],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=40,
        )
        assert first.returncode == 0, first.stderr
        env["OVC_BOOTSTRAP_PASSWORD"] = "Different-password-that-must-not-win!"
        repeated = subprocess.run(
            [sys.executable, "-m", "backend.admin_cli", "bootstrap-admin",
             "--phone", "13800009999", "--nickname", "Replacement"],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=40,
        )
        assert repeated.returncode != 0
        setup = subprocess.run(
            [sys.executable, "-c",
             "from fastapi.testclient import TestClient; from backend.app import app; "
             "c=TestClient(app); print(c.post('/api/auth/setup',json={'password':'x'}).status_code)"],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=40,
        )
        assert setup.returncode == 0 and setup.stdout.strip() == "410", setup.stderr
        with psycopg.connect(target.set(drivername="postgresql").render_as_string(hide_password=False)) as connection:
            rows = connection.execute(
                "SELECT phone,nickname,password_hash,platform_role FROM users"
            ).fetchall()
            scoped = connection.execute('''SELECT p.workspace_id,j.workspace_id,j.production_id,
                e.workspace_id,e.production_id FROM productions p JOIN jobs j ON j.id='legacy-j'
                JOIN events e ON e.project_id='legacy-e' WHERE p.id='legacy-p' ''').fetchone()
        assert len(rows) == 1
        assert rows[0][0] == "+8613800009999" and rows[0][1] == "Initial Operator"
        assert rows[0][2].startswith("$argon2id$") and rows[0][3] == "platform_admin"
        assert identity.verify_password(rows[0][2], PASSWORD)
        assert not identity.verify_password(rows[0][2], env["OVC_BOOTSTRAP_PASSWORD"])
        assert len(set(scoped)) == 2 and scoped[1] == scoped[0] and scoped[2] == "legacy-p"
        assert scoped[3] == scoped[0] and scoped[4] == "legacy-p"
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname=%s AND pid<>pg_backend_pid()", (database_name,),
            )
            _assert_safe_target(database_name)
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name)))


def test_auth02_03_04_invites_are_transactional_one_time_hashed_and_role_safe(admin, clients):
    first_phone = phone()
    first, first_user, _ = register(admin, clients, nickname="邀请用户", number=first_phone)
    assert first.get("/api/auth/status").json()["workspaces"] == []

    # Equivalent phone formatting must not create another identity, while the
    # failed user insert must leave the fresh invitation safely reusable.
    retry_invite = invite(admin)["token"]
    duplicate = clients().post("/api/auth/register", json={
        "invitation_token": retry_invite,
        "phone": "+86 " + first_phone[:3] + " " + first_phone[3:7] + " " + first_phone[7:],
        "nickname": "重复号码",
        "password": PASSWORD,
    })
    assert duplicate.status_code == 409
    retry = clients().post("/api/auth/register", json={
        "invitation_token": retry_invite,
        "phone": phone(),
        "nickname": "安全重试",
        "password": PASSWORD,
    })
    assert retry.status_code == 200, retry.text

    expired = invite(admin)
    revoked = invite(admin)
    with s.db() as connection:
        connection.execute(
            "UPDATE invitations SET expires=%s WHERE token_hash=%s",
            (time.time() - 1, identity.digest(expired["token"])),
        )
    assert clients().post("/api/auth/register", json={
        "invitation_token": expired["token"], "phone": phone(), "nickname": "过期", "password": PASSWORD,
    }).status_code == 400
    assert admin.delete(f"/api/admin/invitations/{revoked['id']}").status_code == 200
    assert clients().post("/api/auth/register", json={
        "invitation_token": revoked["token"], "phone": phone(), "nickname": "撤销", "password": PASSWORD,
    }).status_code == 400

    injected = clients().post("/api/auth/register", json={
        "invitation_token": invite(admin)["token"],
        "phone": phone(), "nickname": "越权", "password": PASSWORD,
        "platform_role": "platform_admin", "workspace_id": "foreign", "is_active": True,
    })
    assert injected.status_code == 422

    concurrent = invite(admin)["token"]
    barrier = threading.Barrier(3)
    outcomes: list[int] = []
    lock = threading.Lock()

    def contender(label: str):
        with TestClient(app) as client:
            barrier.wait()
            result = client.post("/api/auth/register", json={
                "invitation_token": concurrent,
                "phone": phone(), "nickname": label, "password": PASSWORD,
            })
        with lock:
            outcomes.append(result.status_code)

    threads = [threading.Thread(target=contender, args=(label,)) for label in ("并发甲", "并发乙")]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    assert sorted(outcomes) == [200, 400]

    with s.db() as connection:
        row = connection.execute("SELECT * FROM users WHERE id=%s", (first_user["id"],)).fetchone()
        stored_invites = connection.execute(
            "SELECT token_hash FROM invitations WHERE token_hash=%s", (identity.digest(concurrent),)
        ).fetchall()
        assert row["password_hash"] != PASSWORD
        assert row["password_hash"].startswith("$argon2id$")
        assert row["platform_role"] == "user"
        assert stored_invites and all(item["token_hash"] != concurrent for item in stored_invites)


def test_auth05_06_07_08_09_sessions_reset_rate_limit_csrf_and_last_role_guards(admin, clients, monkeypatch):
    user_client, user, number = register(admin, clients, nickname="会话用户")
    second = clients()
    assert second.post("/api/auth/login", json={"phone": number, "password": PASSWORD}).status_code == 200
    second.headers.update({"X-CSRF-Token": second.cookies.get(identity.CSRF_COOKIE)})

    # Logout revokes only the caller's session.
    assert user_client.post("/api/auth/logout").status_code == 200
    assert not user_client.get("/api/auth/status").json()["authenticated"]
    assert second.get("/api/auth/status").json()["authenticated"]

    reset = admin.post("/api/admin/password-resets", json={"user_id": user["id"]}).json()
    owner_like = second.post("/api/admin/password-resets", json={"user_id": user["id"]})
    assert owner_like.status_code == 403
    reset_client = clients()
    new_password = "P3-new-integration-password!"
    assert reset_client.post("/api/auth/password-reset", json={
        "token": reset["token"], "password": new_password,
    }).status_code == 200
    assert not second.get("/api/auth/status").json()["authenticated"]
    assert clients().post("/api/auth/password-reset", json={
        "token": reset["token"], "password": new_password,
    }).status_code == 400

    reset_client.headers.update({"X-CSRF-Token": reset_client.cookies.get(identity.CSRF_COOKIE)})
    no_csrf = clients()
    assert no_csrf.post("/api/auth/login", json={"phone": number, "password": new_password}).status_code == 200
    assert no_csrf.post("/api/auth/logout").status_code == 403
    assert reset_client.post(
        "/api/auth/logout", headers={"Origin": "https://attacker.example"}
    ).status_code == 403

    # Database-backed account/IP limits survive independent clients.
    rate_script = (
        "from backend import identity,store; "
        "c=store.db(); db=c.__enter__(); identity.record_failure(db,['multiprocess-proof']); "
        "c.__exit__(None,None,None)"
    )
    for _ in range(2):
        process = subprocess.run(
            [sys.executable, "-c", rate_script], cwd=ROOT, env=os.environ.copy(),
            capture_output=True, text=True, timeout=20,
        )
        assert process.returncode == 0, process.stderr
    with s.db() as connection:
        assert connection.execute(
            "SELECT attempts FROM auth_rate_limits WHERE key='multiprocess-proof'"
        ).fetchone()["attempts"] == 2
    wrong_statuses = []
    for _ in range(11):
        wrong_statuses.append(clients().post("/api/auth/login", json={
            "phone": number, "password": "definitely-wrong",
        }).status_code)
    assert wrong_statuses[:9] == [401] * 9
    assert 429 in wrong_statuses[9:]
    with s.db() as connection:
        assert connection.execute(
            "SELECT MAX(attempts) attempts FROM auth_rate_limits"
        ).fetchone()["attempts"] >= 10
        admin_id = connection.execute(
            "SELECT id FROM users WHERE platform_role='platform_admin' AND is_active ORDER BY created LIMIT 1"
        ).fetchone()["id"]
    assert admin.patch(f"/api/admin/users/{admin_id}", json={"is_active": False}).status_code == 409

    with s.db() as connection:
        connection.execute("DELETE FROM auth_rate_limits")
    assert admin.patch(f"/api/admin/users/{user['id']}", json={"is_active": False}).status_code == 200
    assert not no_csrf.get("/api/auth/status").json()["authenticated"]
    assert admin.patch(f"/api/admin/users/{user['id']}", json={"is_active": True}).status_code == 200

    workspace = add_workspace(admin, user["id"], "最后 owner 保护")
    owner_session = clients()
    assert owner_session.post("/api/auth/login", json={"phone": number, "password": new_password}).status_code == 200
    owner_session.headers.update({"X-CSRF-Token": owner_session.cookies.get(identity.CSRF_COOKIE)})
    assert owner_session.delete(f"/api/workspaces/{workspace}/members/{user['id']}").status_code == 409
    assert owner_session.put(
        f"/api/workspaces/{workspace}/members/{user['id']}", json={"role": "member"}
    ).status_code == 409
    assert admin.patch(f"/api/admin/users/{user['id']}", json={"is_active": False}).status_code == 409
    injected = admin.patch(f"/api/admin/users/{user['id']}", json={
        "is_active": False, "platform_role": "platform_admin",
    })
    assert injected.status_code == 422

    monkeypatch.setenv("OVC_COOKIE_SECURE", "1")
    secure_login = clients().post("/api/auth/login", json={"phone": number, "password": new_password})
    cookie_headers = "; ".join(secure_login.headers.get_list("set-cookie")).lower()
    assert "secure" in cookie_headers and "httponly" in cookie_headers and "samesite=strict" in cookie_headers

    def proxy_request(client_ip: str, forwarded_ip: str, forwarded_proto: str = "https"):
        return Request({
            "type": "http", "http_version": "1.1", "method": "GET", "scheme": "http",
            "path": "/", "raw_path": b"/", "query_string": b"", "server": ("test", 80),
            "client": (client_ip, 1234),
            "headers": [(b"x-forwarded-for", forwarded_ip.encode()),
                        (b"x-forwarded-proto", forwarded_proto.encode())],
        })

    monkeypatch.setenv("OVC_COOKIE_SECURE", "0")
    monkeypatch.setenv("OVC_TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    untrusted = proxy_request("198.51.100.4", "203.0.113.9")
    trusted = proxy_request("10.1.2.3", "203.0.113.9")
    assert identity.client_ip(untrusted) == "198.51.100.4" and not identity.secure_cookie(untrusted)
    assert identity.client_ip(trusted) == "203.0.113.9" and identity.secure_cookie(trusted)


def test_p3_r1_password_reset_serializes_old_password_login(admin, clients):
    _, user, number = register(admin, clients, nickname="重置并发用户")
    reset = admin.post("/api/admin/password-resets", json={"user_id": user["id"]}).json()
    login_client, reset_client = clients(), clients()
    barrier = threading.Barrier(3)
    results: dict[str, int] = {}

    def late_login():
        barrier.wait()
        results["login"] = login_client.post(
            "/api/auth/login", json={"phone": number, "password": PASSWORD}
        ).status_code

    def reset_password():
        barrier.wait()
        results["reset"] = reset_client.post("/api/auth/password-reset", json={
            "token": reset["token"], "password": "P3-R1-new-password!",
        }).status_code

    threads = [threading.Thread(target=late_login), threading.Thread(target=reset_password)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()

    assert results["reset"] == 200
    assert results["login"] in {200, 401}
    # If the old-password login won the row lock it committed first and the
    # reset revoked it. If reset won, the old password was rejected. Either
    # ordering leaves no usable old-credential session after reset commits.
    assert not login_client.get("/api/auth/status").json()["authenticated"]
    assert reset_client.get("/api/auth/status").json()["authenticated"]
    assert clients().post("/api/auth/login", json={
        "phone": number, "password": "P3-R1-new-password!",
    }).status_code == 200


def test_p3_r1_rate_limits_precede_hashing_and_success_preserves_shared_ip(admin, clients, monkeypatch):
    _, user, number = register(admin, clients, nickname="限流顺序用户")
    raw_invite = invite(admin)["token"]
    reset = admin.post("/api/admin/password-resets", json={"user_id": user["id"]}).json()
    now = time.time()
    blocked = [
        "register:invite:" + identity.digest(raw_invite),
        "reset:token:" + identity.digest(reset["token"]),
    ]
    with s.db() as connection:
        for key in blocked:
            connection.execute(
                "INSERT INTO auth_rate_limits(key,window_started,attempts,blocked_until) VALUES(%s,%s,8,%s)",
                (key, now, now + 60),
            )

    calls = 0
    original_hash = identity.hash_password

    def observed_hash(password: str):
        nonlocal calls
        calls += 1
        return original_hash(password)

    monkeypatch.setattr(identity, "hash_password", observed_hash)
    assert clients().post("/api/auth/register", json={
        "invitation_token": raw_invite, "phone": phone(), "nickname": "应先限流", "password": PASSWORD,
    }).status_code == 429
    assert clients().post("/api/auth/password-reset", json={
        "token": reset["token"], "password": "P3-R1-rate-password!",
    }).status_code == 429
    assert calls == 0

    monkeypatch.setattr(identity, "client_ip", lambda _request: "198.51.100.77")
    ip_key = "login:ip:198.51.100.77"
    account_key = "login:account:" + identity.digest(identity.normalize_phone(number))
    with s.db() as connection:
        connection.execute("DELETE FROM auth_rate_limits")
        identity.record_failure(connection, [ip_key, account_key])
    assert clients().post("/api/auth/login", json={"phone": number, "password": PASSWORD}).status_code == 200
    with s.db() as connection:
        assert connection.execute("SELECT attempts FROM auth_rate_limits WHERE key=%s", (ip_key,)).fetchone()["attempts"] == 1
        assert connection.execute("SELECT 1 FROM auth_rate_limits WHERE key=%s", (account_key,)).fetchone() is None


def test_p3_r1_last_platform_admin_guard_is_concurrent(admin):
    with s.db() as connection:
        first = connection.execute(
            "SELECT * FROM users WHERE platform_role='platform_admin' AND is_active ORDER BY created LIMIT 1"
        ).fetchone()
        second_id = s.uid("user-admin-race-")
        now = time.time()
        connection.execute(
            """INSERT INTO users(id,phone,nickname,password_hash,platform_role,is_active,created,updated)
               VALUES(%s,%s,'并发管理员',%s,'platform_admin',TRUE,%s,%s)""",
            (second_id, identity.normalize_phone(phone()), identity.hash_password(PASSWORD), now, now),
        )
        second = connection.execute("SELECT * FROM users WHERE id=%s", (second_id,)).fetchone()

    barrier = threading.Barrier(3)
    outcomes: list[int] = []
    lock = threading.Lock()

    def deactivate(actor, target_id):
        principal = identity.Principal(
            actor["id"], actor["phone"], actor["nickname"], "platform_admin", "direct-test", time.time() + 60
        )
        token = identity.set_current(principal)
        try:
            barrier.wait()
            try:
                update_user_state(target_id, UserStateUpdate(is_active=False))
                status = 200
            except HTTPException as exc:
                status = exc.status_code
        finally:
            identity.reset_current(token)
        with lock:
            outcomes.append(status)

    threads = [
        threading.Thread(target=deactivate, args=(first, second_id)),
        threading.Thread(target=deactivate, args=(second, first["id"])),
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    assert sorted(outcomes) == [200, 409]
    with s.db() as connection:
        assert connection.execute(
            "SELECT COUNT(*) count FROM users WHERE platform_role='platform_admin' AND is_active"
        ).fetchone()["count"] == 1


def test_acl01_to_08_role_matrix_nested_ids_files_jobs_trash_and_admin_boundary(admin, clients):
    owner_a, owner_a_user, _ = register(admin, clients, nickname="A owner")
    owner_b, owner_b_user, _ = register(admin, clients, nickname="B owner")
    manager, manager_user, _ = register(admin, clients, nickname="A1 manager")
    editor, editor_user, _ = register(admin, clients, nickname="A1 editor")
    viewer, viewer_user, _ = register(admin, clients, nickname="A1 viewer")
    no_production, no_production_user, _ = register(admin, clients, nickname="A team only")
    workspace_a = add_workspace(admin, owner_a_user["id"], "团队 A")
    workspace_b = add_workspace(admin, owner_b_user["id"], "团队 B")
    a1 = create_project(owner_a, workspace_a, "A1")
    a2 = create_project(owner_a, workspace_a, "A2")
    b1 = create_project(owner_b, workspace_b, "B1")

    for member in (manager_user, editor_user, viewer_user, no_production_user):
        add_team_member(owner_a, workspace_a, member["id"])
    add_production_member(owner_a, a1["production_id"], manager_user["id"], "manager")
    add_production_member(owner_a, a1["production_id"], editor_user["id"], "editor")
    add_production_member(owner_a, a1["production_id"], viewer_user["id"], "viewer")

    assert {item["id"] for item in editor.get("/api/projects").json()} == {a1["id"]}
    assert editor.get(f"/api/projects/{a1['id']}").status_code == 200
    assert editor.get(f"/api/projects/{a2['id']}").status_code == 404
    assert editor.get(f"/api/projects/{b1['id']}").status_code == 404
    assert editor.get(
        f"/api/projects/{b1['id']}", headers={"X-Workspace-ID": workspace_a}
    ).status_code == 404
    assert no_production.get(f"/api/projects/{a1['id']}").status_code == 404
    assert admin.get(f"/api/projects/{a1['id']}").status_code == 404

    assert viewer.post(
        f"/api/productions/{a1['production_id']}/sources",
        json={"title": "viewer forbidden", "type": "manual"},
    ).status_code == 403
    editor_source = editor.post(
        f"/api/productions/{a1['production_id']}/sources",
        json={"title": "editor source", "type": "manual"},
    )
    assert editor_source.status_code == 200
    chapter = editor.post(
        f"/api/productions/{a1['production_id']}/sources/{editor_source.json()['id']}/chapters",
        json={"title": "不得批量绕过", "content": "正文"},
    ).json()
    assert editor.post(
        f"/api/productions/{a1['production_id']}/chapters/trash",
        json={"chapter_ids": [chapter["id"]]},
    ).status_code == 403
    assert manager.post(
        f"/api/productions/{a1['production_id']}/chapters/trash",
        json={"chapter_ids": [chapter["id"]]},
    ).status_code == 200
    assert editor.delete(
        f"/api/productions/{a1['production_id']}/sources/{editor_source.json()['id']}"
    ).status_code == 403
    assert editor.put(f"/api/projects/{a1['id']}", json={
        "name": a1["name"], "revision": a1["revision"],
        "production_revision": a1["production_revision"], "document": a1["document"],
    }).status_code == 403
    manager_copy = manager.get(f"/api/projects/{a1['id']}").json()
    manager_save = manager.put(f"/api/projects/{a1['id']}", json={
        "name": "A1 manager save", "revision": manager_copy["revision"],
        "production_revision": manager_copy["production_revision"], "document": manager_copy["document"],
    })
    assert manager_save.status_code == 200
    b_copy = owner_b.get(f"/api/projects/{b1['id']}").json()
    assert owner_b.put(f"/api/projects/{b1['id']}", json={
        "name": "B1 history", "revision": b_copy["revision"],
        "production_revision": b_copy["production_revision"], "document": b_copy["document"],
    }).status_code == 200
    b_revision_id = owner_b.get(f"/api/projects/{b1['id']}/revisions").json()[0]["id"]
    assert editor.get(f"/api/projects/{b1['id']}/revisions/{b_revision_id}").status_code == 404
    assert editor.get(f"/api/projects/{a1['id']}/revisions/{b_revision_id}").status_code == 404

    a1_asset = editor.post(
        f"/api/projects/{a1['id']}/assets?category=reference",
        files={"file": ("a1.png", png_bytes(), "image/png")},
    ).json()
    a2_asset = owner_a.post(
        f"/api/projects/{a2['id']}/assets?category=reference",
        files={"file": ("a2.png", png_bytes(), "image/png")},
    ).json()
    b_asset = owner_b.post(
        f"/api/projects/{b1['id']}/assets?category=reference",
        files={"file": ("b.png", png_bytes(), "image/png")},
    ).json()
    assert viewer.get(f"/api/assets/{a1_asset['id']}/file", headers={"Range": "bytes=0-7"}).status_code == 206
    assert editor.get(f"/api/assets/{a2_asset['id']}/file").status_code == 404
    assert editor.get(f"/api/assets/{b_asset['id']}/file").status_code == 404
    assert editor.patch(
        f"/api/projects/{a1['id']}/assets/{a2_asset['id']}", json={"category": "other"}
    ).status_code == 404

    now = time.time()
    with s.db() as connection:
        connection.execute(
            '''INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated,
               workspace_id,production_id,actor_user_id)
               VALUES(%s,%s,%s,'acl-node','text','queued','{}',%s,%s,%s,%s,%s)''',
            ("job-b-" + uuid.uuid4().hex, "sub-b-" + uuid.uuid4().hex, b1["id"], now, now,
             workspace_b, b1["production_id"], owner_b_user["id"]),
        )
        foreign_job = connection.execute(
            "SELECT id FROM jobs WHERE production_id=%s ORDER BY created DESC LIMIT 1", (b1["production_id"],)
        ).fetchone()["id"]
        same_production_job = "job-a-" + uuid.uuid4().hex
        connection.execute(
            '''INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated,
               workspace_id,production_id,actor_user_id)
               VALUES(%s,%s,%s,'acl-node','text','queued','{}',%s,%s,%s,%s,%s)''',
            (same_production_job, "sub-a-" + uuid.uuid4().hex, a1["id"], now, now,
             workspace_a, a1["production_id"], manager_user["id"]),
        )
    assert editor.get(f"/api/jobs/{foreign_job}").status_code == 404
    assert editor.post(f"/api/jobs/{same_production_job}/cancel").status_code == 403
    assert manager.post(f"/api/jobs/{same_production_job}/cancel").status_code == 200

    with s.db() as connection:
        connection.execute("UPDATE jobs SET status='succeeded' WHERE id=%s", (foreign_job,))
    assert owner_b.delete(f"/api/projects/{b1['id']}").status_code == 200
    trash = editor.get("/api/trash").json()
    assert b1["id"] not in {item["id"] for item in trash["projects"]}
    assert editor.post(f"/api/trash/project/{b1['id']}/restore").status_code == 404

    ordinary_settings = editor.get("/api/settings").json()
    assert ordinary_settings["read_only"] is True
    assert all("api_key" not in item for item in ordinary_settings["providers"])
    assert editor.put("/api/settings", json={"providers": []}).status_code == 403
    assert editor.get("/api/providers/not-configured/models").status_code == 400
    assert editor.post("/api/providers/not-configured/verify").status_code == 403
    assert editor.get("/api/admin/users").status_code == 403
    assert admin.get("/api/admin/audit-events").status_code == 200

    # Removing an active member preserves content but immediately revokes the
    # old session's resource capability on the next request.
    assert owner_a.delete(
        f"/api/productions/{a1['production_id']}/members/{editor_user['id']}"
    ).status_code == 200
    assert editor.get(f"/api/projects/{a1['id']}").status_code == 404
    assert owner_a.get(f"/api/projects/{a1['id']}").status_code == 200


def test_p3_r1_workspace_removal_and_production_grant_leave_no_orphan_access(admin, clients):
    owner, owner_user, owner_phone = register(admin, clients, nickname="撤权 owner")
    target, target_user, _ = register(admin, clients, nickname="撤权目标")
    workspace = add_workspace(admin, owner_user["id"], "撤权竞态团队")
    project = create_project(owner, workspace, "撤权竞态作品")
    add_team_member(owner, workspace, target_user["id"])
    owner_two = clients()
    assert owner_two.post("/api/auth/login", json={"phone": owner_phone, "password": PASSWORD}).status_code == 200
    owner_two.headers.update({"X-CSRF-Token": owner_two.cookies.get(identity.CSRF_COOKIE)})
    barrier = threading.Barrier(3)
    outcomes: list[int] = []
    lock = threading.Lock()

    def grant():
        barrier.wait()
        status = owner.put(
            f"/api/productions/{project['production_id']}/members/{target_user['id']}",
            json={"role": "viewer"},
        ).status_code
        with lock:
            outcomes.append(status)

    def remove():
        barrier.wait()
        status = owner_two.delete(
            f"/api/workspaces/{workspace}/members/{target_user['id']}"
        ).status_code
        with lock:
            outcomes.append(status)

    threads = [threading.Thread(target=grant), threading.Thread(target=remove)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    assert 200 in outcomes and all(status in {200, 409} for status in outcomes)
    with s.db() as connection:
        assert connection.execute(
            "SELECT 1 FROM workspace_members WHERE workspace_id=%s AND user_id=%s",
            (workspace, target_user["id"]),
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM production_members WHERE production_id=%s AND user_id=%s",
            (project["production_id"], target_user["id"]),
        ).fetchone() is None
        # Even a legacy/orphan row cannot grant access at read time.
        connection.execute(
            "INSERT INTO production_members(production_id,user_id,role,created) VALUES(%s,%s,'viewer',%s)",
            (project["production_id"], target_user["id"], time.time()),
        )
    assert target.get(f"/api/projects/{project['id']}").status_code == 404
    assert project["id"] not in {item["id"] for item in target.get("/api/projects").json()}
    add_team_member(owner, workspace, target_user["id"])
    with s.db() as connection:
        assert connection.execute(
            "SELECT 1 FROM production_members WHERE production_id=%s AND user_id=%s",
            (project["production_id"], target_user["id"]),
        ).fetchone() is None
    assert target.get(f"/api/projects/{project['id']}").status_code == 404


def test_p3_r1_concurrent_owner_demotion_preserves_one_active_owner(admin, clients):
    owner_a, user_a, _ = register(admin, clients, nickname="并发 owner A")
    owner_b, user_b, _ = register(admin, clients, nickname="并发 owner B")
    workspace = add_workspace(admin, user_a["id"], "owner 并发团队")
    add_team_member(owner_a, workspace, user_b["id"], "owner")
    barrier = threading.Barrier(3)
    outcomes: list[int] = []
    lock = threading.Lock()

    def demote(client, user_id):
        barrier.wait()
        status = client.put(
            f"/api/workspaces/{workspace}/members/{user_id}", json={"role": "member"}
        ).status_code
        with lock:
            outcomes.append(status)

    threads = [
        threading.Thread(target=demote, args=(owner_a, user_a["id"])),
        threading.Thread(target=demote, args=(owner_b, user_b["id"])),
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    assert sorted(outcomes) == [200, 409]
    with s.db() as connection:
        assert connection.execute(
            """SELECT COUNT(*) count FROM workspace_members wm JOIN users u ON u.id=wm.user_id
               WHERE wm.workspace_id=%s AND wm.role='owner' AND u.is_active""", (workspace,),
        ).fetchone()["count"] == 1


def test_acl09_route_guard_fails_for_a_new_unclassified_api_route():
    route_map = (ROOT / "docs" / "multiuser-rollout" / "design" / "ROUTE_AUTH_MAP.md").read_text(
        encoding="utf-8"
    )
    assert guard_exit_code(export_routes(app), route_map) == 0
    original_count = len(app.routes)

    def fake_unclassified_resource():
        return {"unexpected": True}

    app.add_api_route(
        "/api/new-unclassified-resource", fake_unclassified_resource,
        methods=["POST"], name="p3_r1_unclassified_probe",
    )
    try:
        actual_routes = export_routes(app)
        assert "POST /api/new-unclassified-resource" in unclassified_api_routes(actual_routes, route_map)
        assert guard_exit_code(actual_routes, route_map) == 1
    finally:
        del app.router.routes[original_count:]
    assert guard_exit_code(export_routes(app), route_map) == 0


def test_media04_signed_capability_binds_asset_method_purpose_expiry_and_revocation(admin, clients):
    owner, owner_user, _ = register(admin, clients, nickname="Capability owner")
    workspace = add_workspace(admin, owner_user["id"], "Capability team")
    project = create_project(owner, workspace, "Capability production")
    asset = owner.post(
        f"/api/projects/{project['id']}/assets?category=reference",
        files={"file": ("cap.png", png_bytes(), "image/png")},
    ).json()
    url = public_asset_url({"public_base_url": "http://testserver"}, asset["id"], ttl=60)
    from urllib.parse import parse_qs, urlsplit
    parsed = urlsplit(url)
    params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
    expiry = int(params["expires"])
    signature = params["signature"]
    assert valid_signature(asset["id"], expiry, signature, "GET", "provider-input")
    assert not valid_signature(asset["id"] + "x", expiry, signature, "GET", "provider-input")
    assert not valid_signature(asset["id"], expiry, signature, "POST", "provider-input")
    assert not valid_signature(asset["id"], expiry, signature, "GET", "other")
    assert not valid_signature(asset["id"], int(time.time()) - 1, signature, "GET", "provider-input")
    assert clients().get(url).status_code == 200
    assert owner.delete(f"/api/projects/{project['id']}/assets/{asset['id']}").status_code == 200
    assert clients().get(url).status_code == 404


def test_event01_02_live_sse_filters_tenants_and_stops_after_membership_and_session_revocation(admin, clients):
    owner_a, owner_a_user, _ = register(admin, clients, nickname="SSE A owner")
    owner_b, owner_b_user, _ = register(admin, clients, nickname="SSE B owner")
    viewer, viewer_user, viewer_phone = register(admin, clients, nickname="SSE viewer")
    workspace_a = add_workspace(admin, owner_a_user["id"], "SSE team A")
    workspace_b = add_workspace(admin, owner_b_user["id"], "SSE team B")
    a1 = create_project(owner_a, workspace_a, "SSE A1")
    b1 = create_project(owner_b, workspace_b, "SSE B1")
    add_team_member(owner_a, workspace_a, viewer_user["id"])
    add_production_member(owner_a, a1["production_id"], viewer_user["id"], "viewer")

    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    server.install_signal_handlers = lambda: None
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started

    connected = threading.Event()
    closed = threading.Event()
    received: queue.Queue[dict] = queue.Queue()

    def read_stream():
        try:
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}", timeout=10, trust_env=False
            ) as browser:
                logged_in = browser.post(
                    "/api/auth/login", json={"phone": viewer_phone, "password": PASSWORD}
                )
                assert logged_in.status_code == 200
                with browser.stream("GET", "/api/events") as response:
                    assert response.status_code == 200
                    connected.set()
                    for line in response.iter_lines():
                        if line.startswith("data: "):
                            received.put(json.loads(line[6:]))
        finally:
            closed.set()

    reader = threading.Thread(target=read_stream, daemon=True)
    reader.start()
    try:
        assert connected.wait(5)
        s.event(b1["id"], {"type": "acl-sse-b", "marker": "must-not-leak"})
        s.event(a1["id"], {"type": "acl-sse-a", "marker": "visible"})
        visible = received.get(timeout=6)
        assert visible["project_id"] == a1["id"] and visible["marker"] == "visible"
        assert received.empty()

        assert owner_a.delete(
            f"/api/productions/{a1['production_id']}/members/{viewer_user['id']}"
        ).status_code == 200
        # Allow one configured 2-second authorization refresh, then prove a
        # newly committed event is not delivered to the still-open old stream.
        time.sleep(2.4)
        s.event(a1["id"], {"type": "acl-sse-revoked", "marker": "must-not-arrive"})
        time.sleep(2.4)
        assert received.empty()

        assert admin.patch(
            f"/api/admin/users/{viewer_user['id']}", json={"is_active": False}
        ).status_code == 200
        assert closed.wait(5), "revoked database session did not stop SSE within the 5-second window"
    finally:
        server.should_exit = True
        server_thread.join(timeout=10)
        assert not server_thread.is_alive()
