"""First-run .env helper for the Windows Jarvis installer.

Pure file/text logic: copy the example, generate API_SECRET and
TOKEN_ENCRYPTION_KEY. Family users never type a talk key.

Operator (Berk): set the key on the hosted talk server, or inject
``JARVIS_OPERATOR_OPENROUTER_KEY`` / ``OPENROUTER_API_KEY`` /
``JARVIS_HOSTED_TALK_URL`` in the private build env. Users never see it.

``write-key`` remains for operators and tests. The packaged app does not
open a key window. No FastAPI import.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path

PLACEHOLDER_SECRETS = {
    "",
    "change-me",
    "changeme",
    "change-me-to-a-long-random-string",
    "dev-secret-change-me",
}

PLACEHOLDER_KEYS = {
    "",
    "changeme",
    "change-me",
    "your-key-here",
    "sk-or-...",
    "sk-or-v1-...",
}

JARVIS_DEFAULTS = {
    "JARVIS_ENABLED": "true",
    "EXECUTIVE_PRIME_ADAPTER": "jarvis",
    "HOST": "127.0.0.1",
    "PORT": "8787",
    "PUBLIC_BASE_URL": "http://127.0.0.1:8787",
    "LLM_PROVIDER": "openrouter",
}


def default_documents_jarvis() -> Path:
    home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or ".")
    return (home / "Documents" / "Jarvis").resolve()


def generate_api_secret() -> str:
    return secrets.token_urlsafe(48)


def generate_fernet_key() -> str:
    try:
        from cryptography.fernet import Fernet

        return Fernet.generate_key().decode("ascii")
    except Exception:
        import base64

        return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


def _strip_quotes(value: str) -> str:
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in {"'", '"'}:
        return v[1:-1]
    return v


def parse_env_text(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        out[key] = _strip_quotes(value)
    return out


def read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    return parse_env_text(path.read_text(encoding="utf-8"))


def upsert_env_value(text: str, key: str, value: str) -> str:
    """Set KEY=value, replacing an existing uncommented assignment."""
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    replaced = False
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        existing_key = stripped.split("=", 1)[0].strip()
        if existing_key == key:
            out.append(f"{key}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        if out and out[-1].strip() != "":
            out.append("")
        out.append(f"{key}={value}")
    body = newline.join(out)
    if not body.endswith(newline):
        body += newline
    return body


def is_placeholder_secret(value: str | None) -> bool:
    return _strip_quotes(value or "").strip() in PLACEHOLDER_SECRETS


def is_missing_openrouter_key(value: str | None) -> bool:
    return _strip_quotes(value or "").strip() in PLACEHOLDER_KEYS


def needs_openrouter_key(env_path: Path) -> bool:
    if not env_path.is_file():
        return True
    return is_missing_openrouter_key(read_env_file(env_path).get("OPENROUTER_API_KEY"))


def apply_generated_secrets(text: str) -> str:
    data = parse_env_text(text)
    if is_placeholder_secret(data.get("API_SECRET")):
        text = upsert_env_value(text, "API_SECRET", generate_api_secret())
    if is_placeholder_secret(data.get("TOKEN_ENCRYPTION_KEY")):
        text = upsert_env_value(text, "TOKEN_ENCRYPTION_KEY", generate_fernet_key())
    return text


def apply_jarvis_defaults(
    text: str,
    *,
    workspace: Path | None = None,
    database_path: Path | None = None,
    force_local: bool = False,
) -> str:
    data = parse_env_text(text)
    always = {"JARVIS_ENABLED", "EXECUTIVE_PRIME_ADAPTER"}
    local_net = {"HOST", "PORT", "PUBLIC_BASE_URL"}
    for key, value in JARVIS_DEFAULTS.items():
        current = data.get(key)
        should = (
            key in always
            or is_placeholder_secret(current)
            or current is None
            or (force_local and key in local_net)
        )
        if should:
            text = upsert_env_value(text, key, value)
        data = parse_env_text(text)

    ws = workspace or default_documents_jarvis()
    if is_placeholder_secret(data.get("JARVIS_WORKSPACE")):
        text = upsert_env_value(text, "JARVIS_WORKSPACE", str(ws))

    if database_path is not None:
        text = upsert_env_value(text, "DATABASE_PATH", str(database_path))
        text = upsert_env_value(text, "DATABASE_PROVIDER", "sqlite")

    return text


def ensure_env_file(
    env_path: Path,
    example_path: Path | None = None,
    *,
    workspace: Path | None = None,
    database_path: Path | None = None,
    force_local: bool = False,
) -> Path:
    env_path = Path(env_path)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    created = not env_path.is_file()
    if env_path.is_file():
        text = env_path.read_text(encoding="utf-8")
    elif example_path and Path(example_path).is_file():
        text = Path(example_path).read_text(encoding="utf-8")
    else:
        text = (
            "API_SECRET=change-me-to-a-long-random-string\n"
            "TOKEN_ENCRYPTION_KEY=\n"
            "OPENROUTER_API_KEY=\n"
            "JARVIS_ENABLED=true\n"
            "EXECUTIVE_PRIME_ADAPTER=jarvis\n"
            "HOST=127.0.0.1\n"
            "PORT=8787\n"
        )
    text = apply_generated_secrets(text)
    text = apply_jarvis_defaults(
        text,
        workspace=workspace,
        database_path=database_path,
        force_local=force_local or created,
    )
    env_path.write_text(text, encoding="utf-8")
    return env_path


def write_openrouter_key(
    env_path: Path,
    key: str,
    *,
    example_path: Path | None = None,
    workspace: Path | None = None,
    database_path: Path | None = None,
    force_local: bool = False,
) -> Path:
    cleaned = _strip_quotes(key or "").strip()
    if not cleaned:
        raise ValueError("API key is empty")
    ensure_env_file(
        env_path,
        example_path,
        workspace=workspace,
        database_path=database_path,
        force_local=force_local,
    )
    text = env_path.read_text(encoding="utf-8")
    text = upsert_env_value(text, "OPENROUTER_API_KEY", cleaned)
    env_path.write_text(text, encoding="utf-8")
    return env_path


def _json_out(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Jarvis first-run .env helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_shared(p: argparse.ArgumentParser) -> None:
        p.add_argument("--env", required=True, help="Path to .env")
        p.add_argument("--example", default="", help="Example env to copy when missing")
        p.add_argument("--workspace", default="", help="JARVIS_WORKSPACE path")
        p.add_argument("--database", default="", help="DATABASE_PATH")
        p.add_argument(
            "--force-local",
            action="store_true",
            help="Force loopback HOST/PORT (packaged installer)",
        )

    p_ensure = sub.add_parser("ensure", help="Create .env and generate secrets")
    add_shared(p_ensure)

    p_need = sub.add_parser("needs-key", help="Check whether OPENROUTER_API_KEY is missing")
    add_shared(p_need)

    p_write = sub.add_parser("write-key", help="Write OPENROUTER_API_KEY")
    add_shared(p_write)
    p_write.add_argument("--key", required=True)

    args = parser.parse_args(argv)
    env_path = Path(args.env)
    example = Path(args.example) if args.example else None
    workspace = Path(args.workspace) if args.workspace else None
    database = Path(args.database) if args.database else None
    force_local = bool(args.force_local)

    try:
        if args.cmd == "ensure":
            ensure_env_file(
                env_path,
                example,
                workspace=workspace,
                database_path=database,
                force_local=force_local,
            )
            _json_out(
                {
                    "ok": True,
                    "env": str(env_path),
                    "needs_key": needs_openrouter_key(env_path),
                    "workspace": str(workspace or default_documents_jarvis()),
                }
            )
            return 0
        if args.cmd == "needs-key":
            _json_out(
                {
                    "ok": True,
                    "needs_key": needs_openrouter_key(env_path),
                    "env": str(env_path),
                }
            )
            return 0
        write_openrouter_key(
            env_path,
            args.key,
            example_path=example,
            workspace=workspace,
            database_path=database,
            force_local=force_local,
        )
        _json_out(
            {
                "ok": True,
                "env": str(env_path),
                "needs_key": False,
            }
        )
        return 0
    except Exception as exc:
        _json_out({"ok": False, "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
