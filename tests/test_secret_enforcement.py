from __future__ import annotations

import pytest

from app.config import Settings, validate_secret_settings


def _settings(**overrides) -> Settings:
    defaults = dict(
        api_secret="x" * 40,
        token_encryption_key="k" * 44,
        enforce_secure_secrets=True,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_validator_ok_with_real_secrets():
    assert validate_secret_settings(_settings()) == []


@pytest.mark.parametrize(
    "secret",
    ["", "dev-secret-change-me", "change-me-to-a-long-random-string", "public"],
)
def test_validator_flags_default_api_secret(secret):
    problems = validate_secret_settings(_settings(api_secret=secret))
    assert any("API_SECRET" in p for p in problems)


def test_validator_flags_empty_token_encryption_key():
    problems = validate_secret_settings(_settings(token_encryption_key=""))
    assert any("TOKEN_ENCRYPTION_KEY" in p for p in problems)


async def test_lifespan_refuses_to_start_when_enforced(monkeypatch):
    from app import main as main_mod

    insecure = _settings(api_secret="dev-secret-change-me", token_encryption_key="")
    monkeypatch.setattr(main_mod, "get_settings", lambda: insecure)

    app = main_mod.create_app()
    with pytest.raises(RuntimeError) as excinfo:
        async with app.router.lifespan_context(app):
            pass
    message = str(excinfo.value)
    assert "insecure secrets" in message
    assert "ENFORCE_SECURE_SECRETS" in message


async def test_lifespan_starts_when_secrets_secure(monkeypatch):
    from app import main as main_mod

    secure = _settings(
        database_path="./data/test_secret_enforcement.db",
    )
    monkeypatch.setattr(main_mod, "get_settings", lambda: secure)

    app = main_mod.create_app()
    async with app.router.lifespan_context(app):
        assert app.state.settings.enforce_secure_secrets is True
