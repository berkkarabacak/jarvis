"""Sandboxed workspace roots for Jarvis file and shell tools."""

from __future__ import annotations

import os
import re
from pathlib import Path

_SAFE_NAME = re.compile(r"^[A-Za-z0-9._\- /\\]+$")


def default_workspace() -> Path:
    home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or ".")
    # Prefer explicit env, else Documents\Jarvis, else ~/Jarvis-Workspace
    env = (os.environ.get("JARVIS_WORKSPACE") or "").strip()
    if env:
        root = Path(env).expanduser().resolve()
    else:
        docs = home / "Documents" / "Jarvis"
        root = docs if docs.parent.exists() else (home / "Jarvis-Workspace")
        root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "Documents").mkdir(exist_ok=True)
    (root / "Scripts").mkdir(exist_ok=True)
    (root / "Exports").mkdir(exist_ok=True)
    (root / "Inbox").mkdir(exist_ok=True)
    (root / "Memory").mkdir(exist_ok=True)
    return root


class Workspace:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_workspace()).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, rel: str, *, must_exist: bool = False) -> Path:
        raw = (rel or ".").strip().replace("\\", "/")
        if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
            # Absolute paths only allowed if still under root
            candidate = Path(raw).resolve()
        else:
            candidate = (self.root / raw).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise PermissionError(f"Path escapes workspace: {rel}") from exc
        if must_exist and not candidate.exists():
            raise FileNotFoundError(str(candidate.relative_to(self.root)))
        return candidate

    def rel(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.root)).replace("\\", "/")
