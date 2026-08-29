from __future__ import annotations

import pytest

from app.config import Settings


def _settings() -> Settings:
    return Settings(api_secret="x" * 40)


def test_apply_updates_applies_valid_fields():
    s = _settings()
    s.apply_updates({"database_provider": "postgres", "postgres_port": 5433})
    assert s.database_provider == "postgres"
    assert s.postgres_port == 5433


def test_apply_updates_rejects_unknown_fields():
    s = _settings()
    with pytest.raises(ValueError, match="unknown settings fields"):
        s.apply_updates({"not_a_real_field": 1})
    assert not hasattr(s, "not_a_real_field")


def test_apply_updates_rejects_invalid_values():
    s = _settings()
    with pytest.raises(Exception):
        s.apply_updates({"postgres_port": "not-a-number"})
    # original value untouched after failed update
    assert isinstance(s.postgres_port, int)


def test_other_fields_unchanged_after_update():
    s = _settings()
    before = s.api_secret
    s.apply_updates({"tz": "Europe/Berlin"})
    assert s.tz == "Europe/Berlin"
    assert s.api_secret == before
