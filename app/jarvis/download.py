"""A7 download safety: quarantine + hash + MotW; never auto-execute ==GRoK== (ORCH-302)."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_MAX_BYTES = int(os.environ.get("JARVIS_DOWNLOAD_MAX_MB") or "50") * 1024 * 1024
_URL_RE = re.compile(r"^https://", re.I)


def quarantine_root() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    root = Path(local) / "Jarvis" / "Quarantine"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_name(url: str, content_disposition: str = "") -> str:
    name = ""
    if content_disposition and "filename=" in content_disposition.lower():
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', content_disposition, re.I)
        if m:
            name = m.group(1).strip()
    if not name:
        path = urlparse(url).path
        name = Path(path).name or "download.bin"
    name = re.sub(r"[^\w.\- ()\[\]]+", "_", name)[:120]
    return name or "download.bin"


def _write_motw(path: Path, url: str) -> None:
    """Mark-of-the-Web Zone.Identifier ADS (Windows)."""
    host = urlparse(url).netloc
    data = (
        "[ZoneTransfer]\r\n"
        "ZoneId=3\r\n"
        f"ReferrerUrl={url}\r\n"
        f"HostUrl={url}\r\n"
    )
    try:
        ads = Path(str(path) + ":Zone.Identifier")
        ads.write_text(data, encoding="utf-8")
    except OSError:
        # Non-NTFS or non-Windows — write sidecar
        side = path.with_suffix(path.suffix + ".zone.txt")
        side.write_text(f"ZoneId=3\nurl={url}\nhost={host}\n", encoding="utf-8")


def _defender_scan(path: Path) -> dict[str, Any]:
    mp = Path(os.environ.get("JARVIS_MPCMDRUN") or r"C:\Program Files\Windows Defender\MpCmdRun.exe")
    if not mp.is_file():
        return {"scanned": False, "reason": "MpCmdRun not found"}
    try:
        completed = subprocess.run(
            [str(mp), "-Scan", "-ScanType", "3", "-File", str(path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return {
            "scanned": True,
            "exit_code": completed.returncode,
            "stdout": (completed.stdout or "")[-500:],
            "clean": completed.returncode == 0,
        }
    except Exception as exc:
        return {"scanned": False, "reason": str(exc)[:200]}


def fetch_to_quarantine(url: str, *, release: bool = False) -> dict[str, Any]:
    """HTTPS-only fetch into quarantine. Never executes. release moves after confirm."""
    u = (url or "").strip()
    if not _URL_RE.match(u):
        return {"ok": False, "error": "only https:// URLs are allowed"}
    parsed = urlparse(u)
    if not parsed.netloc or parsed.netloc.lower() in {"localhost", "127.0.0.1"}:
        return {"ok": False, "error": "invalid or local host blocked"}

    try:
        import httpx
    except ImportError:
        return {"ok": False, "error": "httpx not installed"}

    qroot = quarantine_root()
    job_id = "dl_" + uuid.uuid4().hex[:12]
    dest_dir = qroot / job_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    try:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            with client.stream("GET", u) as resp:
                if resp.status_code >= 400:
                    return {"ok": False, "error": f"HTTP {resp.status_code}"}
                ctype = resp.headers.get("content-type", "")
                name = _safe_name(u, resp.headers.get("content-disposition", ""))
                dest = dest_dir / name
                h = hashlib.sha256()
                size = 0
                with dest.open("wb") as f:
                    for chunk in resp.iter_bytes():
                        size += len(chunk)
                        if size > _MAX_BYTES:
                            f.close()
                            dest.unlink(missing_ok=True)
                            return {
                                "ok": False,
                                "error": f"file exceeds max size {_MAX_BYTES} bytes",
                            }
                        h.update(chunk)
                        f.write(chunk)
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}

    sha = h.hexdigest()
    _write_motw(dest, u)
    scan = _defender_scan(dest)
    meta = {
        "ok": True,
        "job_id": job_id,
        "path": str(dest),
        "filename": name,
        "bytes": size,
        "sha256": sha,
        "content_type": ctype,
        "source_host": parsed.netloc,
        "source_url": u,
        "quarantine": True,
        "executed": False,
        "scan": scan,
        "note": (
            "File is quarantined and was NOT executed. "
            "Say confirm to release_download into workspace Inbox, or leave it in quarantine."
        ),
        "needs_confirm": True,
        "confirm_action": "release_download",
    }
    (dest_dir / "meta.json").write_text(
        __import__("json").dumps(meta, indent=2), encoding="utf-8"
    )
    return meta


def release_download(job_id: str, *, workspace_inbox: Path) -> dict[str, Any]:
    """Move quarantined file into workspace Inbox (still never execute)."""
    jid = (job_id or "").strip()
    if not jid.startswith("dl_") or ".." in jid or "/" in jid or "\\" in jid:
        return {"ok": False, "error": "invalid job_id"}
    src_dir = quarantine_root() / jid
    if not src_dir.is_dir():
        return {"ok": False, "error": "unknown quarantine job"}
    files = [p for p in src_dir.iterdir() if p.is_file() and p.name != "meta.json" and not p.name.endswith(".zone.txt")]
    if not files:
        return {"ok": False, "error": "no file in quarantine job"}
    src = files[0]
    workspace_inbox.mkdir(parents=True, exist_ok=True)
    dest = workspace_inbox / src.name
    if dest.exists():
        dest = workspace_inbox / f"{src.stem}_{int(time.time())}{src.suffix}"
    import shutil

    shutil.copy2(src, dest)
    try:
        _write_motw(dest, f"quarantine:{jid}")
    except Exception:
        pass
    return {
        "ok": True,
        "released_to": str(dest),
        "job_id": jid,
        "executed": False,
        "note": "Released to workspace Inbox. Still not executed by Jarvis.",
    }
