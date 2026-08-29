from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture()
async def app_with_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("API_SECRET", "unit-test-secret-value")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "auth.db"))
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application
    get_settings.cache_clear()


async def _get(client, path=" /api/status".strip(), headers=None):
    return await client.get(path, headers=headers or {})


async def test_default_dev_secret_authenticates_nothing(app_with_db=None):
    """The well-known default secret must never pass the gate."""
    import os

    os.environ["API_SECRET"] = "dev-secret-change-me"
    try:
        from app.config import get_settings
        from app.main import create_app

        get_settings.cache_clear()
        application = create_app()
        async with application.router.lifespan_context(application):
            async with AsyncClient(
                transport=ASGITransport(app=application), base_url="http://test"
            ) as client:
                r = await client.get(
                    "/api/status",
                    headers={"X-Api-Key": "dev-secret-change-me"},
                )
        assert r.status_code == 401
    finally:
        os.environ.pop("API_SECRET", None)


async def test_correct_secret_accepted(app_with_secret):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_secret), base_url="http://test"
    ) as client:
        r = await client.get("/api/status", headers={"X-Api-Key": "unit-test-secret-value"})
    assert r.status_code == 200


async def test_wrong_secret_rejected(app_with_secret):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_secret), base_url="http://test"
    ) as client:
        r = await client.get("/api/status", headers={"X-Api-Key": "wrong"})
    assert r.status_code == 401


async def test_bearer_token_accepted(app_with_secret):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_secret), base_url="http://test"
    ) as client:
        r = await client.get(
            "/api/status",
            headers={"Authorization": "Bearer unit-test-secret-value"},
        )
    assert r.status_code == 200
