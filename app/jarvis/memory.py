"""Long-term Jarvis memory (SQLite) — desktop source of truth ==GRoK== (ORCH-255).

Schema (local only; no TencentDB):
  meta              — schema_version, pruned_at
  facts             — durable user/project facts (soft-delete via tombstoned_at)
  turns             — conversation turns per session
  mission_summaries — end-of-mission / weekly digests
  tool_audit_idx    — optional light index into tool_audit.db rows of interest

Retention: configurable via JARVIS_MEMORY_RETENTION_DAYS (default 90).
Export: Memory/backups/jarvis-YYYYMMDD.db
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2


class JarvisMemory:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                  key TEXT PRIMARY KEY,
                  value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS facts (
                  id TEXT PRIMARY KEY,
                  fact TEXT NOT NULL,
                  tags TEXT,
                  source TEXT DEFAULT 'user',
                  importance INTEGER DEFAULT 0,
                  created_at REAL NOT NULL,
                  updated_at REAL,
                  tombstoned_at REAL
                );
                CREATE TABLE IF NOT EXISTS turns (
                  id TEXT PRIMARY KEY,
                  session_id TEXT NOT NULL,
                  role TEXT NOT NULL,
                  content TEXT NOT NULL,
                  created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mission_summaries (
                  id TEXT PRIMARY KEY,
                  mission_id TEXT,
                  title TEXT,
                  summary TEXT NOT NULL,
                  tools_used TEXT,
                  prime_session_id TEXT,
                  created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tool_audit_idx (
                  id TEXT PRIMARY KEY,
                  ts REAL NOT NULL,
                  source TEXT,
                  tool TEXT,
                  tier TEXT,
                  ok INTEGER,
                  preview TEXT
                );
                """
            )
            # migrate v1 → v2 columns BEFORE indexes that reference new cols
            cols = {
                r[1]
                for r in conn.execute("PRAGMA table_info(facts)").fetchall()
            }
            if "source" not in cols:
                conn.execute("ALTER TABLE facts ADD COLUMN source TEXT DEFAULT 'user'")
            if "importance" not in cols:
                conn.execute(
                    "ALTER TABLE facts ADD COLUMN importance INTEGER DEFAULT 0"
                )
            if "updated_at" not in cols:
                conn.execute("ALTER TABLE facts ADD COLUMN updated_at REAL")
            if "tombstoned_at" not in cols:
                conn.execute("ALTER TABLE facts ADD COLUMN tombstoned_at REAL")
            conn.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_facts_created ON facts(created_at);
                CREATE INDEX IF NOT EXISTS idx_facts_live ON facts(tombstoned_at, created_at);
                CREATE INDEX IF NOT EXISTS idx_summaries_created ON mission_summaries(created_at);
                """
            )
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )
            if not conn.execute(
                "SELECT 1 FROM meta WHERE key='created_at'"
            ).fetchone():
                conn.execute(
                    "INSERT INTO meta(key, value) VALUES('created_at', ?)",
                    (str(time.time()),),
                )

    def schema_version(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
        return int(row["value"]) if row else 0

    def add_fact(
        self,
        fact: str,
        tags: str = "",
        *,
        source: str = "user",
        importance: int = 0,
    ) -> str:
        mid = str(uuid.uuid4())
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO facts(id, fact, tags, source, importance, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    mid,
                    fact.strip(),
                    tags.strip(),
                    (source or "user")[:40],
                    int(importance),
                    now,
                    now,
                ),
            )
        return mid

    def forget_fact(self, fact_id: str) -> bool:
        """Soft-delete (tombstone) a fact — C2 forget tool."""
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE facts SET tombstoned_at=?, updated_at=? WHERE id=? AND tombstoned_at IS NULL",
                (time.time(), time.time(), fact_id),
            )
            return cur.rowcount > 0

    def forget_matching(self, query: str) -> int:
        q = (query or "").strip()
        if not q:
            return 0
        like = f"%{q}%"
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE facts SET tombstoned_at=?, updated_at=? "
                "WHERE tombstoned_at IS NULL AND (fact LIKE ? OR tags LIKE ?)",
                (now, now, like, like),
            )
            return int(cur.rowcount)

    def search_facts(self, query: str = "", limit: int = 12) -> list[dict[str, Any]]:
        q = (query or "").strip()
        with self._connect() as conn:
            if q:
                like = f"%{q}%"
                rows = conn.execute(
                    "SELECT id, fact, tags, source, importance, created_at FROM facts "
                    "WHERE tombstoned_at IS NULL AND (fact LIKE ? OR tags LIKE ?) "
                    "ORDER BY importance DESC, created_at DESC LIMIT ?",
                    (like, like, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, fact, tags, source, importance, created_at FROM facts "
                    "WHERE tombstoned_at IS NULL "
                    "ORDER BY importance DESC, created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    def add_turn(self, session_id: str, role: str, content: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO turns(id, session_id, role, content, created_at) VALUES (?,?,?,?,?)",
                (str(uuid.uuid4()), session_id, role, content[:20000], time.time()),
            )

    def recent_turns(self, session_id: str, limit: int = 30) -> list[dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, content FROM turns WHERE session_id=? "
                "ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        out = [{"role": r["role"], "content": r["content"]} for r in rows]
        out.reverse()
        return out

    def global_recent_turns(self, limit: int = 20) -> list[dict[str, str]]:
        """Cross-session recall for multi-week continuity hints."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, content, session_id, created_at FROM turns "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "role": r["role"],
                "content": r["content"][:500],
                "session_id": r["session_id"],
            }
            for r in reversed(list(rows))
        ]

    def add_mission_summary(
        self,
        summary: str,
        *,
        title: str = "",
        mission_id: str | None = None,
        tools_used: list[str] | None = None,
        prime_session_id: str | None = None,
    ) -> str:
        mid = mission_id or ("msn_" + uuid.uuid4().hex[:12])
        sid = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO mission_summaries("
                "id, mission_id, title, summary, tools_used, prime_session_id, created_at"
                ") VALUES (?,?,?,?,?,?,?)",
                (
                    sid,
                    mid,
                    (title or "")[:200],
                    summary.strip()[:8000],
                    json.dumps(tools_used or []),
                    prime_session_id,
                    time.time(),
                ),
            )
        # also write markdown sidecar
        try:
            root = self.db_path.parent
            sdir = root / "summaries"
            sdir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            path = sdir / f"{stamp}_{mid}.md"
            path.write_text(
                f"# {title or mid}\n\n{summary.strip()}\n",
                encoding="utf-8",
            )
        except Exception:
            pass
        return sid

    def recent_summaries(self, limit: int = 8) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, mission_id, title, summary, tools_used, prime_session_id, created_at "
                "FROM mission_summaries ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["tools_used"] = json.loads(d.get("tools_used") or "[]")
            except Exception:
                d["tools_used"] = []
            out.append(d)
        return out

    def index_tool_event(
        self,
        *,
        source: str,
        tool: str,
        tier: str,
        ok: bool | None,
        preview: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO tool_audit_idx(id, ts, source, tool, tier, ok, preview) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    time.time(),
                    source[:40],
                    tool[:64],
                    tier[:8],
                    None if ok is None else (1 if ok else 0),
                    (preview or "")[:300],
                ),
            )


    def find_fact_by_tag(self, tag: str) -> dict[str, Any] | None:
        """Return newest live fact whose tags contain `tag` (comma-separated match)."""
        t = (tag or "").strip()
        if not t:
            return None
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, fact, tags, source, importance, created_at, updated_at FROM facts "
                "WHERE tombstoned_at IS NULL AND ("
                "tags = ? OR tags LIKE ? OR tags LIKE ? OR tags LIKE ?"
                ") ORDER BY COALESCE(updated_at, created_at) DESC LIMIT 20",
                (t, f"{t},%", f"%,{t}", f"%,{t},%"),
            ).fetchall()
        for r in rows:
            tags = [x.strip() for x in str(r["tags"] or "").split(",") if x.strip()]
            if t in tags:
                return dict(r)
        return None

    def upsert_fact_by_tag(
        self,
        tag: str,
        fact: str,
        *,
        extra_tags: str = "",
        source: str = "daily-journal",
        importance: int = 1,
    ) -> str:
        """Insert or update a live fact identified by a required tag."""
        t = (tag or "").strip()
        body = (fact or "").strip()
        if not t or not body:
            raise ValueError("tag and fact required")
        extras = [x.strip() for x in (extra_tags or "").split(",") if x.strip()]
        tag_parts = [t, "daily-journal"] + [x for x in extras if x not in {t, "daily-journal"}]
        # keep unique order; always include tag + daily-journal (ORCH-329)
        seen: list[str] = []
        for p in tag_parts:
            if p and p not in seen:
                seen.append(p)
        tags = ",".join(seen)
        existing = self.find_fact_by_tag(t)
        now = time.time()
        if existing:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE facts SET fact=?, tags=?, source=?, importance=?, updated_at=? "
                    "WHERE id=?",
                    (
                        body[:8000],
                        tags,
                        (source or "daily-journal")[:40],
                        int(importance),
                        now,
                        existing["id"],
                    ),
                )
            return str(existing["id"])
        return self.add_fact(
            body,
            tags=tags,
            source=source,
            importance=importance,
        )

    def turns_between(
        self,
        start_ts: float,
        end_ts: float,
        *,
        session_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        lim = max(1, min(int(limit), 500))
        with self._connect() as conn:
            if session_id:
                rows = conn.execute(
                    "SELECT role, content, session_id, created_at FROM turns "
                    "WHERE session_id=? AND created_at >= ? AND created_at < ? "
                    "ORDER BY created_at ASC LIMIT ?",
                    (session_id, float(start_ts), float(end_ts), lim),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT role, content, session_id, created_at FROM turns "
                    "WHERE created_at >= ? AND created_at < ? "
                    "ORDER BY created_at ASC LIMIT ?",
                    (float(start_ts), float(end_ts), lim),
                ).fetchall()
        return [dict(r) for r in rows]

    def context_blob(self, *, max_chars: int = 1800) -> str:
        """Size-capped memory block for Realtime / Prime session inject (C2)."""
        parts: list[str] = ["[Jarvis durable memory]"]
        journals = self.search_facts("daily-journal", limit=6)
        journal_rows: list[dict[str, Any]] = []
        seen_j: set[str] = set()
        for j in journals:
            tags = str(j.get("tags") or "")
            fid = str(j.get("id") or "")
            if "daily-journal" not in tags or fid in seen_j:
                continue
            seen_j.add(fid)
            journal_rows.append(j)
            if len(journal_rows) >= 3:
                break
        if journal_rows:
            parts.append("Daily journals:")
            for j in journal_rows:
                body = (j.get("fact") or "").strip().replace("\n", " | ")
                parts.append(f"- {body[:360]}")
        facts = self.search_facts(limit=10)
        if facts:
            parts.append("Facts:")
            for f in facts:
                if "daily-journal" in str(f.get("tags") or ""):
                    continue
                line = f"- {f['fact']}"
                if f.get("tags"):
                    line += f" [{f['tags']}]"
                parts.append(line)
        summaries = self.recent_summaries(limit=4)
        if summaries:
            parts.append("Recent mission summaries:")
            for s in summaries:
                title = s.get("title") or s.get("mission_id") or "mission"
                body = (s.get("summary") or "")[:240]
                parts.append(f"- {title}: {body}")
        text = "\n".join(parts)
        if len(text) > max_chars:
            text = text[: max_chars - 20] + "\n…[truncated]"
        return text

    def retention_days(self) -> int:
        raw = (os.environ.get("JARVIS_MEMORY_RETENTION_DAYS") or "90").strip()
        try:
            return max(7, min(3650, int(raw)))
        except ValueError:
            return 90

    def prune(self, *, days: int | None = None) -> dict[str, int]:
        """Delete turns/summaries older than retention; keep non-tombstoned facts."""
        d = days if days is not None else self.retention_days()
        cutoff = time.time() - d * 86400
        with self._connect() as conn:
            t = conn.execute(
                "DELETE FROM turns WHERE created_at < ?", (cutoff,)
            ).rowcount
            s = conn.execute(
                "DELETE FROM mission_summaries WHERE created_at < ?", (cutoff,)
            ).rowcount
            a = conn.execute(
                "DELETE FROM tool_audit_idx WHERE ts < ?", (cutoff,)
            ).rowcount
            # hard-delete long-tombstoned facts
            f = conn.execute(
                "DELETE FROM facts WHERE tombstoned_at IS NOT NULL AND tombstoned_at < ?",
                (cutoff,),
            ).rowcount
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('pruned_at', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(time.time()),),
            )
        return {
            "turns": int(t),
            "summaries": int(s),
            "audit_idx": int(a),
            "tombstoned_facts": int(f),
            "retention_days": d,
        }

    def export_backup(self) -> Path:
        """Copy DB to Memory/backups/jarvis-YYYYMMDD_HHMMSS.db"""
        bdir = self.db_path.parent / "backups"
        bdir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest = bdir / f"jarvis-{stamp}.db"
        # checkpoint WAL then copy
        with self._connect() as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        shutil.copy2(self.db_path, dest)
        return dest
