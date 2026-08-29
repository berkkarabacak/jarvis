from __future__ import annotations

import importlib
import os
from pathlib import Path


def _reload():
    os.environ.pop("OPENAI_API_KEY", None)
    import app.jarvis.hosted_openai as mod

    importlib.reload(mod)
    return mod


def test_no_key_in_source():
    """The module must not embed any credential in source (issue #144)."""
    source = Path("app/jarvis/hosted_openai.py").read_text(encoding="utf-8")
    assert "sk-proj" not in source


def test_hosted_openai_env_file_is_not_in_the_tree():
    """A committed host env file must never ship in a public clone."""
    assert not Path("deploy/hosted-openai.env").exists()


def test_env_only_resolution(monkeypatch):
    monkeypatch.setenv("HOSTED_OPENAI_KEY", "hosted-test-key")
    mod = _reload()
    try:
        assert mod.openai_api_key() == "hosted-test-key"
    finally:
        monkeypatch.delenv("HOSTED_OPENAI_KEY", raising=False)
        _reload()


def test_empty_when_nothing_set(monkeypatch):
    monkeypatch.delenv("HOSTED_OPENAI_KEY", raising=False)
    mod = _reload()
    assert mod.openai_api_key() == ""
