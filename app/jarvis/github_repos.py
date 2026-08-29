"""List the signed-in user's GitHub repositories (read-only).

Credential order, first match wins:
1. GitHub MCP token stored in Settings → Connectors
2. GH_TOKEN or GITHUB_TOKEN in the process environment
3. ``gh`` CLI already logged in on this machine

If none of those exist, return a plain Settings message — never a generic
"there was a problem".
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any, Callable

NOT_CONNECTED = (
    "GitHub is not connected. Add a GitHub token in Settings → Connectors, "
    "or set GH_TOKEN / GITHUB_TOKEN, or run gh auth login on this machine."
)

_API_URL = "https://api.github.com/user/repos"
_USER_AGENT = "jarvis-agent-orchestrator"


def github_token_from_settings(root=None) -> str:
    """Decrypt the GitHub MCP preset token, if Settings has one."""
    try:
        from app.jarvis.mcp_registry import get_server
        from app.jarvis.mcp_tokens import decrypt_token

        server = get_server("github", root=root)
        if not server:
            return ""
        return (decrypt_token(server.get("token_enc")) or "").strip()
    except Exception:
        return ""


def github_token_from_env(env: dict[str, str] | None = None) -> str:
    environ = env if env is not None else os.environ
    for key in ("GH_TOKEN", "GITHUB_TOKEN"):
        val = (environ.get(key) or "").strip()
        if val:
            return val
    return ""


def resolve_github_token(*, root=None, env: dict[str, str] | None = None) -> str:
    return github_token_from_settings(root=root) or github_token_from_env(env)


def _repo_row(raw: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    full = str(raw.get("full_name") or raw.get("nameWithOwner") or name).strip()
    if not name and full:
        name = full.rsplit("/", 1)[-1]
    if not name:
        return None
    private = raw.get("private")
    if private is None:
        vis = str(raw.get("visibility") or raw.get("isPrivate") or "").lower()
        private = vis in {"private", "true", "1"}
    return {
        "name": name,
        "full_name": full or name,
        "private": bool(private),
        "html_url": str(raw.get("html_url") or raw.get("url") or "").strip(),
    }


def repos_from_api_payload(payload: Any) -> list[dict[str, Any]]:
    rows = payload if isinstance(payload, list) else []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in rows:
        row = _repo_row(item) if isinstance(item, dict) else None
        if not row:
            continue
        key = row["full_name"].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def list_repos_via_token(
    token: str,
    *,
    fetch: Callable[..., Any] | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """GET /user/repos with a PAT / GitHub MCP token. ``fetch`` is a test seam."""
    tok = (token or "").strip()
    if not tok:
        raise ValueError("empty token")
    per_page = max(1, min(int(limit), 100))
    url = f"{_API_URL}?per_page={per_page}&sort=updated&affiliation=owner,collaborator,organization_member"
    headers = {
        "Authorization": f"Bearer {tok}",
        "Accept": "application/vnd.github+json",
        "User-Agent": _USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if fetch is not None:
        payload = fetch(url, headers)
        return repos_from_api_payload(payload)

    import httpx

    res = httpx.get(url, headers=headers, timeout=20.0)
    if res.status_code in {401, 403}:
        raise PermissionError("GitHub token was rejected")
    res.raise_for_status()
    return repos_from_api_payload(res.json())


def list_repos_via_gh(
    *,
    run: Callable[..., Any] | None = None,
    which: Callable[[str], str | None] | None = None,
    limit: int = 50,
) -> list[dict[str, Any]] | None:
    """Use ``gh repo list`` when the CLI is installed and logged in.

    Returns None when gh is missing or not authenticated (so callers can
    fall through to the not-connected message).
    """
    finder = which or shutil.which
    if finder("gh") is None:
        return None
    argv = [
        "gh",
        "repo",
        "list",
        "--limit",
        str(max(1, min(int(limit), 100))),
        "--json",
        "name,nameWithOwner,isPrivate,url",
    ]
    runner = run or subprocess.run
    try:
        completed = runner(
            argv,
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    code = int(getattr(completed, "returncode", 1) or 0)
    stdout = str(getattr(completed, "stdout", "") or "")
    stderr = str(getattr(completed, "stderr", "") or "").lower()
    if code != 0:
        if "not logged" in stderr or "auth" in stderr or "gh auth login" in stderr:
            return None
        return None
    try:
        payload = json.loads(stdout)
    except ValueError:
        return None
    rows: list[dict[str, Any]] = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict):
            continue
        mapped = {
            "name": item.get("name"),
            "full_name": item.get("nameWithOwner") or item.get("name"),
            "private": item.get("isPrivate"),
            "html_url": item.get("url"),
        }
        row = _repo_row(mapped)
        if row:
            rows.append(row)
    return rows


def summarize_repos_for_voice(repos: list[dict[str, Any]] | None, *, limit: int = 12) -> str:
    rows = [r for r in (repos or []) if isinstance(r, dict) and r.get("name")]
    if not rows:
        return "I did not find any GitHub repositories for this account."
    names = [str(r.get("full_name") or r.get("name")) for r in rows[: max(1, min(limit, 20))]]
    head = f"You have {len(rows)} GitHub repositor{'y' if len(rows) == 1 else 'ies'}"
    body = ": " + ", ".join(names)
    if len(rows) > limit:
        body += f", and {len(rows) - limit} more"
    return head + body + "."


def list_github_repos(
    *,
    root=None,
    env: dict[str, str] | None = None,
    fetch: Callable[..., Any] | None = None,
    run: Callable[..., Any] | None = None,
    which: Callable[[str], str | None] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Return repo names, or a plain not-connected message. Never a generic failure."""
    token = resolve_github_token(root=root, env=env)
    source = ""
    repos: list[dict[str, Any]] | None = None
    if token:
        try:
            repos = list_repos_via_token(token, fetch=fetch, limit=limit)
            source = "token"
        except PermissionError as exc:
            return {
                "ok": True,
                "connected": False,
                "repos": [],
                "names": [],
                "error": str(exc),
                "summary": (
                    "GitHub rejected the stored token. Add a new token in "
                    "Settings → Connectors."
                ),
            }
        except Exception as exc:
            # Token existed but the HTTP call failed — still try gh before giving up.
            token_error = str(exc)[:200]
            repos = None
        else:
            token_error = ""
    else:
        token_error = ""

    if repos is None:
        gh_rows = list_repos_via_gh(run=run, which=which, limit=limit)
        if gh_rows is not None:
            repos = gh_rows
            source = "gh"

    if repos is None:
        return {
            "ok": True,
            "connected": False,
            "repos": [],
            "names": [],
            "summary": NOT_CONNECTED,
        }

    names = [str(r.get("full_name") or r.get("name")) for r in repos if r.get("name")]
    summary = summarize_repos_for_voice(repos)
    out: dict[str, Any] = {
        "ok": True,
        "connected": True,
        "source": source,
        "repos": repos,
        "names": names,
        "count": len(names),
        "summary": summary,
    }
    if token_error and source == "gh":
        out["note"] = "Used gh CLI after the Settings/env token request failed."
    return out
