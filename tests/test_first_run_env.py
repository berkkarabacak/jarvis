"""ORCH-359 — first-run .env helper (Windows installer key window)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.first_run_env import (
    apply_generated_secrets,
    apply_jarvis_defaults,
    default_documents_jarvis,
    ensure_env_file,
    is_missing_openrouter_key,
    main,
    needs_openrouter_key,
    parse_env_text,
    upsert_env_value,
    write_openrouter_key,
)

EXAMPLE = """# local windows example
API_SECRET=change-me-to-a-long-random-string
TOKEN_ENCRYPTION_KEY=
OPENROUTER_API_KEY=
JARVIS_ENABLED=false
EXECUTIVE_PRIME_ADAPTER=openrouter
HOST=0.0.0.0
PORT=8787
# JARVIS_WORKSPACE=C:\\Users\\YOU\\Documents\\Jarvis
DATABASE_PATH=./data/control_room.db
"""


def test_upsert_replaces_existing_and_keeps_comments():
    text = "FOO=1\n# OPENROUTER_API_KEY=skip\nOPENROUTER_API_KEY=\nBAR=2\n"
    out = upsert_env_value(text, "OPENROUTER_API_KEY", "sk-or-real")
    data = parse_env_text(out)
    assert data["OPENROUTER_API_KEY"] == "sk-or-real"
    assert data["FOO"] == "1"
    assert data["BAR"] == "2"
    assert "# OPENROUTER_API_KEY=skip" in out


def test_upsert_appends_when_missing():
    out = upsert_env_value("FOO=1\n", "OPENROUTER_API_KEY", "abc")
    assert parse_env_text(out)["OPENROUTER_API_KEY"] == "abc"
    assert parse_env_text(out)["FOO"] == "1"


def test_upsert_preserves_crlf():
    out = upsert_env_value("FOO=1\r\nBAR=2\r\n", "FOO", "x")
    assert "\r\n" in out
    assert parse_env_text(out)["FOO"] == "x"


def test_missing_key_placeholders():
    assert is_missing_openrouter_key("")
    assert is_missing_openrouter_key("sk-or-...")
    assert is_missing_openrouter_key('""')
    assert not is_missing_openrouter_key("sk-or-v1-real-key")


def test_ensure_generates_secrets_and_jarvis_defaults(tmp_path):
    example = tmp_path / "example.env"
    example.write_text(EXAMPLE, encoding="utf-8")
    env_path = tmp_path / "user" / ".env"
    ws = tmp_path / "Documents" / "Jarvis"
    db = tmp_path / "user" / "data" / "control_room.db"

    ensure_env_file(
        env_path, example, workspace=ws, database_path=db, force_local=True
    )
    data = parse_env_text(env_path.read_text(encoding="utf-8"))

    assert data["API_SECRET"] != "change-me-to-a-long-random-string"
    assert len(data["API_SECRET"]) >= 32
    assert data["TOKEN_ENCRYPTION_KEY"]
    assert data["TOKEN_ENCRYPTION_KEY"].endswith("=") or len(data["TOKEN_ENCRYPTION_KEY"]) >= 32
    assert data["JARVIS_ENABLED"] == "true"
    assert data["EXECUTIVE_PRIME_ADAPTER"] == "jarvis"
    assert data["HOST"] == "127.0.0.1"
    assert data["JARVIS_WORKSPACE"] == str(ws)
    assert data["DATABASE_PATH"] == str(db)
    assert data["OPENROUTER_API_KEY"] == ""
    assert needs_openrouter_key(env_path) is True


def test_ensure_without_force_local_keeps_existing_host(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "API_SECRET=already-set-secret-value-not-a-placeholder\n"
        "TOKEN_ENCRYPTION_KEY=already-fernet-key-value\n"
        "OPENROUTER_API_KEY=\n"
        "HOST=0.0.0.0\n"
        "PORT=9999\n",
        encoding="utf-8",
    )
    ensure_env_file(env_path, force_local=False)
    data = parse_env_text(env_path.read_text(encoding="utf-8"))
    assert data["HOST"] == "0.0.0.0"
    assert data["PORT"] == "9999"
    assert data["JARVIS_ENABLED"] == "true"


def test_ensure_does_not_rotate_existing_secrets(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "API_SECRET=already-set-secret-value-not-a-placeholder\n"
        "TOKEN_ENCRYPTION_KEY=already-fernet-key-value\n"
        "OPENROUTER_API_KEY=\n",
        encoding="utf-8",
    )
    ensure_env_file(env_path)
    data = parse_env_text(env_path.read_text(encoding="utf-8"))
    assert data["API_SECRET"] == "already-set-secret-value-not-a-placeholder"
    assert data["TOKEN_ENCRYPTION_KEY"] == "already-fernet-key-value"


def test_write_openrouter_key_creates_env_and_saves(tmp_path):
    example = tmp_path / "ex.env"
    example.write_text(EXAMPLE, encoding="utf-8")
    env_path = tmp_path / ".env"
    write_openrouter_key(env_path, "  sk-or-v1-mom-key  ", example_path=example)
    data = parse_env_text(env_path.read_text(encoding="utf-8"))
    assert data["OPENROUTER_API_KEY"] == "sk-or-v1-mom-key"
    assert data["API_SECRET"] != "change-me-to-a-long-random-string"
    assert needs_openrouter_key(env_path) is False


def test_write_openrouter_key_rejects_empty(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        write_openrouter_key(tmp_path / ".env", "   ")


def test_write_does_not_clobber_other_keys(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "API_SECRET=keep-me\nTOKEN_ENCRYPTION_KEY=keep-fernet\nOPENROUTER_API_KEY=old\nFOO=bar\n",
        encoding="utf-8",
    )
    write_openrouter_key(env_path, "sk-or-new")
    data = parse_env_text(env_path.read_text(encoding="utf-8"))
    assert data["API_SECRET"] == "keep-me"
    assert data["TOKEN_ENCRYPTION_KEY"] == "keep-fernet"
    assert data["FOO"] == "bar"
    assert data["OPENROUTER_API_KEY"] == "sk-or-new"


def test_cli_ensure_and_write_key(tmp_path, capsys):
    example = tmp_path / "ex.env"
    example.write_text(EXAMPLE, encoding="utf-8")
    env_path = tmp_path / ".env"
    code = main(
        [
            "ensure",
            "--env",
            str(env_path),
            "--example",
            str(example),
            "--workspace",
            str(tmp_path / "ws"),
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["ok"] is True
    assert payload["needs_key"] is True

    code = main(["write-key", "--env", str(env_path), "--key", "sk-or-from-cli"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["needs_key"] is False
    assert parse_env_text(env_path.read_text(encoding="utf-8"))["OPENROUTER_API_KEY"] == (
        "sk-or-from-cli"
    )


def test_cli_write_key_empty_fails(tmp_path, capsys):
    code = main(["write-key", "--env", str(tmp_path / ".env"), "--key", "  "])
    assert code == 1
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["ok"] is False


def test_module_does_not_import_web_stack():
    import app.first_run_env as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    assert "fastapi" not in source
    assert "uvicorn" not in source
    assert "tkinter" not in source


def test_apply_helpers_on_plain_text():
    text = apply_generated_secrets(EXAMPLE)
    data = parse_env_text(text)
    assert not is_missing_openrouter_key("x") or data["API_SECRET"]
    assert data["API_SECRET"] != "change-me-to-a-long-random-string"
    text = apply_jarvis_defaults(text, workspace=Path("/tmp/Jarvis"), force_local=True)
    data = parse_env_text(text)
    assert data["JARVIS_ENABLED"] == "true"
    assert data["EXECUTIVE_PRIME_ADAPTER"] == "jarvis"


def test_default_workspace_is_documents_jarvis(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert default_documents_jarvis() == (tmp_path / "Documents" / "Jarvis").resolve()


def test_real_local_windows_example_roundtrip(tmp_path):
    repo_example = (
        Path(__file__).resolve().parents[1] / "deploy" / "local-windows.env.example"
    )
    if not repo_example.is_file():
        pytest.skip("deploy/local-windows.env.example missing")
    env_path = tmp_path / ".env"
    write_openrouter_key(env_path, "sk-or-v1-from-real-example", example_path=repo_example)
    data = parse_env_text(env_path.read_text(encoding="utf-8"))
    assert data["OPENROUTER_API_KEY"] == "sk-or-v1-from-real-example"
    assert data["JARVIS_ENABLED"] == "true"
    assert data["API_SECRET"] != "change-me-to-a-long-random-string"
