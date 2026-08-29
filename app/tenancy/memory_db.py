"""In-memory asyncpg-like pool for tenancy unit tests (no live Postgres)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.tenancy.models import BOOTSTRAP_ORG_ID, BOOTSTRAP_ORG_SLUG


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryConn:
    def __init__(self, db: "MemoryDB") -> None:
        self.db = db

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        rows = await self.fetch(sql, *args)
        return rows[0] if rows else None

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        return self.db.query(sql, args)

    async def execute(self, sql: str, *args: Any) -> str:
        self.db.query(sql, args)
        return "OK"

    def transaction(self) -> "MemoryTx":
        return MemoryTx()


class MemoryTx:
    async def start(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class MemoryPool:
    def __init__(self, db: "MemoryDB | None" = None) -> None:
        self.db = db or MemoryDB()
        self.db.ensure_bootstrap()

    async def acquire(self) -> MemoryConn:
        return MemoryConn(self.db)

    async def release(self, _conn: MemoryConn) -> None:
        return None


class MemoryDB:
    def __init__(self) -> None:
        self.organizations: dict[UUID, dict[str, Any]] = {}
        self.users: dict[UUID, dict[str, Any]] = {}
        self.memberships: dict[tuple[UUID, UUID], dict[str, Any]] = {}
        self.org_api_keys: dict[UUID, dict[str, Any]] = {}
        self.audit_events: list[dict[str, Any]] = []

    def ensure_bootstrap(self) -> None:
        if BOOTSTRAP_ORG_ID not in self.organizations:
            now = _now()
            self.organizations[BOOTSTRAP_ORG_ID] = {
                "id": BOOTSTRAP_ORG_ID,
                "name": "Default",
                "slug": BOOTSTRAP_ORG_SLUG,
                "plan": "standard",
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }

    def query(self, sql: str, args: tuple[Any, ...]) -> list[dict[str, Any]]:
        text = " ".join(sql.split())
        low = text.lower()

        if "from organizations where id" in low:
            oid = args[0] if isinstance(args[0], UUID) else UUID(str(args[0]))
            row = self.organizations.get(oid)
            if row and row["status"] != "deleted":
                return [dict(row)]
            return []

        if "from organizations where slug" in low:
            slug = str(args[0]).lower()
            for row in self.organizations.values():
                if row["slug"] == slug and row["status"] != "deleted":
                    return [dict(row)]
            return []

        if low.startswith("insert into organizations"):
            name, slug, plan = str(args[0]), str(args[1]).lower(), str(args[2])
            oid = uuid.uuid4()
            now = _now()
            row = {
                "id": oid,
                "name": name,
                "slug": slug,
                "plan": plan,
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }
            self.organizations[oid] = row
            return [dict(row)]

        if low.startswith("insert into users"):
            email, display_name, password_hash, external_subject = (
                str(args[0]).lower(),
                str(args[1]),
                str(args[2]),
                args[3],
            )
            uid = uuid.uuid4()
            now = _now()
            row = {
                "id": uid,
                "email": email,
                "display_name": display_name,
                "password_hash": password_hash,
                "external_subject": external_subject,
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }
            self.users[uid] = row
            return [dict(row)]

        if "from users where id" in low:
            uid = args[0] if isinstance(args[0], UUID) else UUID(str(args[0]))
            row = self.users.get(uid)
            if row and row["status"] != "deleted":
                return [dict(row)]
            return []

        if "from users where lower(email)" in low or (
            "from users where" in low and "email" in low
        ):
            email = str(args[0]).lower()
            for row in self.users.values():
                if row["email"] == email and row["status"] != "deleted":
                    return [dict(row)]
            return []

        if low.startswith("insert into memberships"):
            uid = args[0] if isinstance(args[0], UUID) else UUID(str(args[0]))
            oid = args[1] if isinstance(args[1], UUID) else UUID(str(args[1]))
            role = str(args[2])
            now = _now()
            key = (uid, oid)
            row = {
                "user_id": uid,
                "org_id": oid,
                "role": role,
                "created_at": self.memberships.get(key, {}).get("created_at", now),
            }
            self.memberships[key] = row
            return [dict(row)]

        if "from memberships" in low and "user_id" in low and "org_id" in low and "join" not in low:
            uid = args[0] if isinstance(args[0], UUID) else UUID(str(args[0]))
            oid = args[1] if isinstance(args[1], UUID) else UUID(str(args[1]))
            row = self.memberships.get((uid, oid))
            return [dict(row)] if row else []

        if "join users" in low and "memberships" in low:
            oid = args[0] if isinstance(args[0], UUID) else UUID(str(args[0]))
            out = []
            for (uid, m_oid), mem in self.memberships.items():
                if m_oid != oid:
                    continue
                user = self.users.get(uid)
                if not user or user["status"] == "deleted":
                    continue
                out.append(
                    {
                        "user_id": uid,
                        "email": user["email"],
                        "display_name": user["display_name"],
                        "role": mem["role"],
                        "created_at": mem["created_at"],
                    }
                )
            out.sort(key=lambda r: r["email"])
            return out

        if low.startswith("insert into org_api_keys"):
            oid = args[0] if isinstance(args[0], UUID) else UUID(str(args[0]))
            name, prefix, key_hash = str(args[1]), str(args[2]), str(args[3])
            scopes = list(args[4] or [])
            created_by = args[5]
            kid = uuid.uuid4()
            now = _now()
            row = {
                "id": kid,
                "org_id": oid,
                "name": name,
                "key_prefix": prefix,
                "key_hash": key_hash,
                "scopes": scopes,
                "created_by": created_by,
                "status": "active",
                "created_at": now,
                "last_used_at": None,
                "revoked_at": None,
            }
            self.org_api_keys[kid] = row
            return [dict(row)]

        if "from org_api_keys" in low and "where org_id" in low and "order by" in low:
            oid = args[0] if isinstance(args[0], UUID) else UUID(str(args[0]))
            rows = [dict(r) for r in self.org_api_keys.values() if r["org_id"] == oid]
            rows.sort(key=lambda r: r["created_at"], reverse=True)
            return rows

        if "update org_api_keys" in low and "revoked" in low:
            kid = args[0] if isinstance(args[0], UUID) else UUID(str(args[0]))
            oid = args[1] if isinstance(args[1], UUID) else UUID(str(args[1]))
            row = self.org_api_keys.get(kid)
            if not row or row["org_id"] != oid or row["status"] != "active":
                return []
            row["status"] = "revoked"
            row["revoked_at"] = _now()
            return [dict(row)]

        if "from org_api_keys" in low and "key_hash" in low:
            digest = str(args[0])
            for row in self.org_api_keys.values():
                if row["key_hash"] == digest and row["status"] == "active":
                    return [dict(row)]
            return []

        if "update org_api_keys set last_used_at" in low:
            kid = args[0] if isinstance(args[0], UUID) else UUID(str(args[0]))
            row = self.org_api_keys.get(kid)
            if row:
                row["last_used_at"] = _now()
            return []

        if low.startswith("insert into audit_events"):
            oid = args[0] if isinstance(args[0], UUID) else UUID(str(args[0]))
            actor_user_id = args[1]
            actor_key_id = args[2]
            actor_type = str(args[3])
            event_type = str(args[4])
            resource_type = str(args[5])
            resource_id = str(args[6])
            detail_json = args[7]
            if isinstance(detail_json, str):
                try:
                    import json as _json

                    detail = _json.loads(detail_json)
                except Exception:
                    detail = {}
            else:
                detail = detail_json or {}
            eid = uuid.uuid4()
            now = _now()
            row = {
                "id": eid,
                "org_id": oid,
                "actor_user_id": actor_user_id,
                "actor_key_id": actor_key_id,
                "actor_type": actor_type,
                "event_type": event_type,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "detail_json": detail,
                "created_at": now,
            }
            self.audit_events.append(row)
            return [dict(row)]

        if "from audit_events" in low and "where org_id" in low:
            oid = args[0] if isinstance(args[0], UUID) else UUID(str(args[0]))
            limit = int(args[1]) if len(args) > 1 else 50
            rows = [dict(r) for r in self.audit_events if r["org_id"] == oid]
            rows.sort(key=lambda r: r["created_at"], reverse=True)
            return rows[:limit]

        if re.search(r"select \* from ([a-z_]+) where", low):
            # generic org_scoped_get
            m = re.search(r"from ([a-z_]+) where ([a-z_]+) = \$1 and ([a-z_]+) = \$2", low)
            if m and m.group(1) == "organizations":
                rid = args[0] if isinstance(args[0], UUID) else UUID(str(args[0]))
                oid = args[1] if isinstance(args[1], UUID) else UUID(str(args[1]))
                row = self.organizations.get(rid)
                if row and row["id"] == rid and str(row.get("id")) and oid:
                    # organizations table has no org_id; not used
                    pass
            return []

        return []
