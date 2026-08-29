"""L3 app allowlist + PowerShell denylist ==GRoK== (ORCH-247 / ORCH-295)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

# Basenames / commands that may auto-run at L3 without extra confirm
DEFAULT_APP_ALLOWLIST = frozenset(
    {
        "notepad",
        "notepad.exe",
        "calc",
        "calc.exe",
        "calculator",
        "calculator.exe",
        "mspaint",
        "mspaint.exe",
        "explorer",
        "explorer.exe",
        "code",
        "code.exe",
        "excel",
        "excel.exe",
        "winword",
        "winword.exe",
        "powerpnt",
        "powerpnt.exe",
        "msedge",
        "msedge.exe",
        "chrome",
        "chrome.exe",
        "firefox",
        "firefox.exe",
        "wt",
        "wt.exe",
        "windows terminal",
    }
)

# Strip PS comments before matching so `# invoke-webrequest https://` cannot bypass
_RE_BLOCK_COMMENT = re.compile(r"<#.*?#>", re.DOTALL)
_RE_LINE_COMMENT = re.compile(r"#[^\n]*")
_RE_STRING_DQ = re.compile(r'"(?:\\.|[^"\\])*"')
_RE_STRING_SQ = re.compile(r"'(?:''|[^'])*'")
_RE_WS = re.compile(r"\s+")

# Token/regex denylist — matched against comment-stripped, lowercased command
_BLOCKED_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE | re.DOTALL)
    for p in (
        r"\bshutdown\b",
        r"\bstop-computer\b",
        r"\brestart-computer\b",
        r"\bformat-volume\b",
        r"\bclear-disk\b",
        r"\bdiskpart\b",
        r"\bformat\.com\b",
        r"\binitialize-disk\b",
        r"\binvoke-expression\b",
        r"\biex\s*\(",
        r"\biex\b",
        r"-encodedcommand\b",
        r"(?<![a-z])-enc\b",
        r"\bfrombase64string\b",
        r"\bremove-item\b[\s\S]{0,200}?\-(recurse|r)\b",
        r"\bremove-item\b[\s\S]{0,80}?(c:\\|c:/|/\s|$env:system)",
        r"(?<![a-z])ri\b[\s\S]{0,200}?\-(recurse|r|force)\b",
        r"(?<![a-z])ri\b[\s\S]{0,80}?(c:\\|c:/)",
        r"\brm\s+(-[a-z]*r|/s)\b",
        r"\brd\s+/s\b",
        r"\brmdir\s+/s\b",
        r"\bdel\s+/s\b",
        r"\binvoke-webrequest\b",
        r"\biwr\b",
        r"\binvoke-restmethod\b",
        r"(?<![a-z])irm\b",
        r"\bstart-bitstransfer\b",
        r"\bwget\b",
        r"\bcurl\b",
        r"\binvoke-command\b",
        r"\bstart-process\b[\s\S]{0,120}?https?://",
        r"\breg\s+delete\b",
        r"\bremove-item\b[\s\S]{0,40}?hk(lm|cu|cr|u):",
        r"\bnet\s+user\b",
        r"\bnet\s+localgroup\b",
        r"\badd-computer\b",
        r"\bremove-computer\b",
        r"\breset-computermachinepassword\b",
        r"\bdisable-computerrestore\b",
        r"\bcipher\s+/w\b",
        r"\btakeown\b",
        r"\bicacls\b",
        r"\bsfc\s+/scannow\b",
        r"\bbcdedit\b",
        r"\bschtasks\b.*/create",
        r"\bnew-service\b",
        r"\bset-service\b",
        r"\bstop-service\b",
        r"\bset-executionpolicy\b",
        r"\bnew-object\b[\s\S]{0,80}?net\.webclient",
        r"\bdownloadstring\b",
        r"\bdownloadfile\b",
        r"\bdownloaddata\b",
        r"\[system\.net\.webclient\]",
        r"\brm\s+-rf\s+/",
    )
)


def _load_extra() -> set[str]:
    raw = (os.environ.get("JARVIS_APP_ALLOWLIST") or "").strip()
    extra: set[str] = set()
    if raw:
        for part in raw.split(","):
            p = part.strip().lower()
            if p:
                extra.add(p)
    path = (os.environ.get("JARVIS_APP_ALLOWLIST_FILE") or "").strip()
    if path and Path(path).is_file():
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(data, list):
                extra.update(str(x).strip().lower() for x in data if str(x).strip())
            elif isinstance(data, dict) and isinstance(data.get("allow"), list):
                extra.update(str(x).strip().lower() for x in data["allow"] if str(x).strip())
        except Exception:
            pass
    return extra


def app_allowlist() -> set[str]:
    return set(DEFAULT_APP_ALLOWLIST) | _load_extra()


def normalize_app_target(target: str) -> str:
    t = (target or "").strip().strip('"').lower()
    t = t.replace("\\", "/").split("/")[-1]
    return t


def is_http_url(value: str) -> bool:
    t = (value or "").strip().lower()
    return t.startswith("http://") or t.startswith("https://")


def is_app_allowlisted(target: str) -> bool:
    t = (target or "").strip().lower()
    if is_http_url(t):
        return True
    base = normalize_app_target(t)
    allow = app_allowlist()
    if base in allow:
        return True
    if base.endswith(".exe") and base[:-4] in allow:
        return True
    if (base + ".exe") in allow:
        return True
    return False


def run_app_requested_url(args: dict | None) -> str:
    """The http(s) URL run_app would open, if any (ORCH-375 / ORCH-376)."""
    args = args or {}
    target = str(args.get("target") or "").strip()
    url = str(args.get("url") or "").strip()
    extra = str(args.get("args") or "").strip()
    if is_http_url(url):
        return url
    if is_http_url(extra):
        return extra
    if is_http_url(target):
        return target
    return ""


def is_run_app_allowlisted(args: dict | None) -> bool:
    """ORCH-375: URL-open is not stricter than run_app chrome.

    Allowlisted when target is an allowlisted app or http(s) URL, or when
    url=/args= is an http(s) URL and the app is omitted or allowlisted.
    """
    args = args or {}
    target = str(args.get("target") or "").strip()
    if is_app_allowlisted(target):
        return True
    page = run_app_requested_url(args)
    if not page:
        return False
    return (not target) or is_app_allowlisted(target)


def normalize_ps_command(command: str) -> str:
    """Lowercase command with comments removed (best-effort) for denylist matching."""
    text = command or ""
    # Blank out strings so comment markers inside strings don't confuse stripping,
    # and so denylist doesn't match only-string content for some patterns — we still
    # want to catch dangerous cmdlets outside strings.
    def _blank(m: re.Match[str]) -> str:
        return " " * (m.end() - m.start())

    tmp = _RE_STRING_DQ.sub(_blank, text)
    tmp = _RE_STRING_SQ.sub(_blank, tmp)
    tmp = _RE_BLOCK_COMMENT.sub(" ", tmp)
    tmp = _RE_LINE_COMMENT.sub(" ", tmp)
    tmp = _RE_WS.sub(" ", tmp).strip().lower()
    return tmp


def is_command_blocked(command: str) -> bool:
    """Return True if command matches a dangerous pattern (ORCH-295 hardened)."""
    if not (command or "").strip():
        return False
    norm = normalize_ps_command(command)
    raw = (command or "").lower()
    # Also scan raw (comment-inclusive) for shutdown etc. that might be split oddly
    haystacks = (norm, raw)
    for hay in haystacks:
        for pat in _BLOCKED_PATTERNS:
            if pat.search(hay):
                return True
    return False


def blocked_reason(command: str) -> str | None:
    if not (command or "").strip():
        return None
    norm = normalize_ps_command(command)
    for pat in _BLOCKED_PATTERNS:
        m = pat.search(norm) or pat.search((command or "").lower())
        if m:
            return f"blocked command pattern: {m.group(0)[:60]}"
    return None


def action_summary(tool: str, args: dict) -> str:
    if tool in {"run_app"}:
        parts = [
            str(args.get("target") or "").strip(),
            str(args.get("url") or "").strip(),
            str(args.get("args") or "").strip(),
        ]
        return f"Start app: {' '.join(p for p in parts if p)}".strip()
    if tool in {"run_powershell"}:
        cmd = str(args.get("command") or "")
        return f"Run PowerShell: {cmd[:120]}"
    if tool in {"open_path"}:
        return f"Open path: {args.get('path', '')}"
    return f"Run tool {tool}"
