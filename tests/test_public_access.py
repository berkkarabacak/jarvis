from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from app.db import Database
from app.persistence.migrate import list_migration_files, parse_migration_statements
from app.public_access.errors import AccountResourceNotFound, UsageQuotaExceeded
from app.public_access.security import (
    PUBLIC_MUTATION_HEADER,
    PUBLIC_MUTATION_HEADER_VALUE,
    PUBLIC_SESSION_COOKIE_NAME,
    derive_account_subject_key,
    derive_bootstrap_subject_key,
)
from app.public_access.store import SqlitePublicAccessStore

os.environ.setdefault("API_SECRET", "test-secret")
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "")
os.environ.setdefault("TOKEN_PROVIDER", "api_key")
os.environ.setdefault("XAI_API_KEY", "xai-test-key")
os.environ.setdefault("LLM_PROVIDER", "openrouter")
os.environ.setdefault("OPENROUTER_API_KEY", "or-test-key")

MUTATION_HEADERS = {
    "Origin": "https://test",
    PUBLIC_MUTATION_HEADER: PUBLIC_MUTATION_HEADER_VALUE,
}


@pytest.fixture
async def public_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "public.db"))
    monkeypatch.setenv("API_SECRET", "test-secret")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")

    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, client=("127.0.0.1", 43120))
        async with AsyncClient(transport=transport, base_url="https://test") as ac:
            yield ac, app
    get_settings.cache_clear()


@pytest.fixture
async def public_store(tmp_path):
    db = Database(tmp_path / "store.db")
    await db.connect()
    try:
        yield SqlitePublicAccessStore(db), db
    finally:
        await db.close()


def test_public_access_postgres_migration_is_additive_and_hash_only():
    names = [path.name for path in list_migration_files()]
    assert "005_public_access_accounts.sql" in names
    sql = Path("app/migrations/005_public_access_accounts.sql").read_text(
        encoding="utf-8"
    )
    assert "CREATE TABLE IF NOT EXISTS account_sessions" in sql
    assert "CREATE TABLE IF NOT EXISTS account_resource_bindings" in sql
    assert "CREATE TABLE IF NOT EXISTS account_usage_windows" in sql
    assert "token_hash" in sql
    assert sql.count("REFERENCES memberships (user_id, org_id)") == 2
    assert "session_token TEXT" not in sql
    assert "cookie" not in sql.lower()
    assert len(parse_migration_statements(sql)) >= 6


@pytest.mark.asyncio
async def test_bootstrap_cookie_flags_and_safe_principal_body(public_client):
    client, app = public_client
    response = await client.post("/api/public/session", headers=MUTATION_HEADERS)
    assert response.status_code == 200, response.text
    cookie = response.headers["set-cookie"]
    lower_cookie = cookie.lower()
    assert cookie.startswith(PUBLIC_SESSION_COOKIE_NAME + "=")
    assert "httponly" in lower_cookie
    assert "secure" in lower_cookie
    assert "samesite=lax" in lower_cookie
    assert "path=/" in lower_cookie
    assert "domain=" not in lower_cookie

    body = response.json()
    assert body["schema_version"] == 1
    assert body["authenticated"] is True
    assert body["account"]["kind"] == "guest"
    assert body["organization"]["role"] == "owner"
    assert body["capabilities"] == [
        "account.rename",
        "mission.read",
        "mission.run",
    ]
    encoded = str(body).lower()
    for forbidden in ("token", "cookie", "hash", "email", "api_secret"):
        assert forbidden not in encoded

    cur = await app.state.db.conn.execute(
        "SELECT token_hash FROM public_account_sessions"
    )
    row = await cur.fetchone()
    assert row is not None
    assert len(row["token_hash"]) == 64
    assert row["token_hash"] not in cookie


@pytest.mark.asyncio
async def test_mutations_require_same_origin_and_custom_header(public_client):
    client, _app = public_client
    missing = await client.post("/api/public/session")
    assert missing.status_code == 403

    wrong_origin = await client.post(
        "/api/public/session",
        headers={
            "Origin": "https://attacker.example",
            PUBLIC_MUTATION_HEADER: PUBLIC_MUTATION_HEADER_VALUE,
        },
    )
    assert wrong_origin.status_code == 403

    missing_custom = await client.post(
        "/api/public/session", headers={"Origin": "https://test"}
    )
    assert missing_custom.status_code == 403


@pytest.mark.asyncio
async def test_bootstrap_resumes_without_creating_another_account(public_client):
    client, app = public_client
    first = await client.post("/api/public/session", headers=MUTATION_HEADERS)
    second = await client.post("/api/public/session", headers=MUTATION_HEADERS)
    assert first.status_code == second.status_code == 200
    assert first.json()["account"]["id"] == second.json()["account"]["id"]
    assert first.json()["organization"]["id"] == second.json()["organization"]["id"]

    cur = await app.state.db.conn.execute("SELECT COUNT(*) AS n FROM public_accounts")
    assert (await cur.fetchone())["n"] == 1
    cur = await app.state.db.conn.execute("SELECT hour_used FROM public_usage_quotas")
    assert (await cur.fetchone())["hour_used"] == 1


@pytest.mark.asyncio
async def test_me_rename_and_revoke_lifecycle(public_client):
    client, _app = public_client
    assert (
        await client.post("/api/public/session", headers=MUTATION_HEADERS)
    ).status_code == 200

    me = await client.get("/api/public/session")
    assert me.status_code == 200
    assert me.json()["account"]["display_name"] == "Guest"

    renamed = await client.patch(
        "/api/public/session",
        headers=MUTATION_HEADERS,
        json={"display_name": "  Ada   Lovelace  "},
    )
    assert renamed.status_code == 200
    assert renamed.json()["account"]["display_name"] == "Ada Lovelace"
    assert (await client.get("/api/public/session")).json()["account"][
        "display_name"
    ] == "Ada Lovelace"

    revoked = await client.delete("/api/public/session", headers=MUTATION_HEADERS)
    assert revoked.status_code == 200
    assert revoked.json() == {"schema_version": 1, "revoked": True}
    assert "max-age=0" in revoked.headers["set-cookie"].lower()
    assert (await client.get("/api/public/session")).status_code == 401


@pytest.mark.asyncio
async def test_session_expiry_and_revocation_are_indistinguishable(public_store):
    store, _db = public_store
    issued = await store.create_guest_session(now=1000, ttl_seconds=60)
    assert await store.resolve_session(issued.session_token + "x", now=1001) is None
    assert await store.resolve_session(issued.session_token, now=1059) is not None
    assert await store.resolve_session(issued.session_token, now=1060) is None

    active = await store.create_guest_session(now=2000, ttl_seconds=60)
    assert await store.revoke_session(active.session_token, now=2001) is True
    assert await store.resolve_session(active.session_token, now=2002) is None
    assert active.session_token not in repr(active)


@pytest.mark.asyncio
async def test_distinct_guest_accounts_and_resource_binding_isolation(public_store):
    store, _db = public_store
    first = await store.create_guest_session(now=1000)
    second = await store.create_guest_session(now=1000)
    assert first.principal.user_id != second.principal.user_id
    assert first.principal.org_id != second.principal.org_id

    bound = await store.bind_resource(
        resource_type="executive_session",
        resource_id="session-001",
        principal=first.principal,
        now=1001,
    )
    again = await store.bind_resource(
        resource_type="executive_session",
        resource_id="session-001",
        principal=first.principal,
        now=1002,
    )
    assert bound == again
    assert (
        await store.require_owned_resource(
            resource_type="executive_session",
            resource_id="session-001",
            principal=first.principal,
        )
    ) == bound

    with pytest.raises(AccountResourceNotFound, match="not found"):
        await store.require_owned_resource(
            resource_type="executive_session",
            resource_id="session-001",
            principal=second.principal,
        )
    with pytest.raises(AccountResourceNotFound, match="not found"):
        await store.bind_resource(
            resource_type="executive_session",
            resource_id="session-001",
            principal=second.principal,
        )


@pytest.mark.asyncio
async def test_hourly_daily_quota_is_atomic_under_concurrency(public_store):
    store, _db = public_store
    subject = "account:v1:" + ("a" * 64)

    async def consume() -> bool:
        try:
            await store.consume_quota(
                subject_key=subject,
                quota_name="executive_turn",
                hourly_limit=5,
                daily_limit=5,
                now=7201,
            )
            return True
        except UsageQuotaExceeded:
            return False

    accepted = await asyncio.gather(*(consume() for _ in range(20)))
    assert sum(accepted) == 5
    snapshot = await store.quota_snapshot(
        subject_key=subject,
        quota_name="executive_turn",
        hourly_limit=5,
        daily_limit=5,
        now=7201,
    )
    assert snapshot.hourly.used == 5
    assert snapshot.daily.used == 5


def test_account_quota_subject_is_deterministic_pseudonymous_and_isolated():
    first = derive_account_subject_key(
        "00000000-0000-4000-8000-000000000001",
        "00000000-0000-4000-8000-000000000101",
        "server-secret",
    )
    repeated = derive_account_subject_key(
        "00000000-0000-4000-8000-000000000001",
        "00000000-0000-4000-8000-000000000101",
        "server-secret",
    )
    other = derive_account_subject_key(
        "00000000-0000-4000-8000-000000000002",
        "00000000-0000-4000-8000-000000000101",
        "server-secret",
    )
    assert first == repeated
    assert first != other
    assert first.startswith("account:v1:")
    assert "00000000" not in first


def test_bootstrap_quota_uses_overwritten_real_ip_and_ignores_spoof_headers():
    def request(peer: str, headers: dict[str, str] | None = None) -> Request:
        return Request(
            {
                "type": "http",
                "method": "POST",
                "scheme": "https",
                "path": "/api/public/session",
                "raw_path": b"/api/public/session",
                "query_string": b"",
                "headers": [
                    (name.lower().encode(), value.encode())
                    for name, value in (headers or {}).items()
                ],
                "client": (peer, 43120),
                "server": ("test", 443),
            }
        )

    first = derive_bootstrap_subject_key(
        request(
            "127.0.0.1",
            {
                "X-Real-IP": "198.51.100.44",
                "X-AI-Guest-Subject": "caller_rotated_subject_1",
                "X-Forwarded-For": "203.0.113.7",
            },
        ),
        "server-secret",
    )
    repeated = derive_bootstrap_subject_key(
        request(
            "127.0.0.1",
            {
                "X-Real-IP": "198.51.100.44",
                "X-AI-Guest-Subject": "caller_rotated_subject_2",
                "X-Forwarded-For": "192.0.2.99",
            },
        ),
        "server-secret",
    )
    other = derive_bootstrap_subject_key(
        request("127.0.0.1", {"X-Real-IP": "198.51.100.45"}),
        "server-secret",
    )
    untrusted = derive_bootstrap_subject_key(
        request(
            "203.0.113.27",
            {
                "X-Real-IP": "198.51.100.44",
                "X-AI-Guest-Subject": "caller_rotated_subject_3",
            },
        ),
        "server-secret",
    )
    direct = derive_bootstrap_subject_key(
        request("203.0.113.27"),
        "server-secret",
    )
    spoofed_forwarded = derive_bootstrap_subject_key(
        request("127.0.0.1", {"X-Forwarded-For": "198.51.100.44"}),
        "server-secret",
    )
    loopback = derive_bootstrap_subject_key(
        request("127.0.0.1"),
        "server-secret",
    )

    assert first == repeated
    assert first != other
    assert untrusted == direct
    assert spoofed_forwarded == loopback
    assert "198.51.100.44" not in first
    assert "caller_rotated_subject" not in first


@pytest.mark.asyncio
async def test_daily_rejection_does_not_partially_increment_hour(public_store):
    store, _db = public_store
    subject = "account:v1:" + ("b" * 64)
    await store.consume_quota(
        subject_key=subject,
        quota_name="executive_turn",
        hourly_limit=10,
        daily_limit=1,
        now=10,
    )
    with pytest.raises(UsageQuotaExceeded) as rejected:
        await store.consume_quota(
            subject_key=subject,
            quota_name="executive_turn",
            hourly_limit=10,
            daily_limit=1,
            now=11,
        )
    assert rejected.value.window == "day"
    snapshot = await store.quota_snapshot(
        subject_key=subject,
        quota_name="executive_turn",
        hourly_limit=10,
        daily_limit=1,
        now=11,
    )
    assert snapshot.hourly.used == 1
    assert snapshot.daily.used == 1


@pytest.mark.asyncio
async def test_bootstrap_subject_is_pseudonymous_and_raw_network_data_is_absent(
    public_client,
):
    client, app = public_client
    raw_ip = "203.0.113.27"
    spoofed_forwarded_ip = "198.51.100.44"
    response = await client.post(
        "/api/public/session",
        headers={
            **MUTATION_HEADERS,
            "X-Real-IP": raw_ip,
            "X-Forwarded-For": spoofed_forwarded_ip,
        },
    )
    assert response.status_code == 200
    cur = await app.state.db.conn.execute(
        "SELECT subject_key FROM public_usage_quotas LIMIT 1"
    )
    stored = str((await cur.fetchone())["subject_key"])
    assert stored.startswith("bootstrap:v1:")
    assert raw_ip not in stored
    assert spoofed_forwarded_ip not in stored
    cur = await app.state.db.conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table'"
    )
    schema = " ".join(str(row["sql"] or "") for row in await cur.fetchall()).lower()
    assert "ip_address" not in schema
    assert "user_agent" not in schema


@pytest.mark.asyncio
async def test_public_session_never_authorizes_admin_router(public_client):
    client, _app = public_client
    assert (
        await client.post("/api/public/session", headers=MUTATION_HEADERS)
    ).status_code == 200
    for method, path in (
        (client.get, "/api/status"),
        (client.get, "/api/jobs"),
        (client.get, "/api/settings/llm"),
        (client.post, "/oauth/import"),
    ):
        response = await method(path)
        assert response.status_code == 401, (path, response.text)
    assert (
        await client.get("/api/status", headers={"X-Api-Key": "test-secret"})
    ).status_code == 200
