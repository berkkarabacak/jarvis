from __future__ import annotations

import base64
import logging
from collections import defaultdict
from typing import Any

import httpx

from app.config import Settings

log = logging.getLogger("grok_automater.jira")

DEFAULT_EXCLUDE_PROJECTS = ("HW9K",)


class JiraClient:
    def __init__(self, settings: Settings) -> None:
        self.base = (settings.jira_base or "").rstrip("/")
        self.email = (settings.jira_email or "").strip()
        self.token = (settings.jira_api_token or "").strip()
        self.exclude = {
            p.strip().upper()
            for p in (settings.jira_exclude_projects or "HW9K").split(",")
            if p.strip()
        }

    @property
    def configured(self) -> bool:
        return bool(self.base and self.email and self.token)

    def _headers(self) -> dict[str, str]:
        raw = f"{self.email}:{self.token}".encode("utf-8")
        return {
            "Authorization": f"Basic {base64.b64encode(raw).decode('ascii')}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def search(self, jql: str, *, max_results: int = 100) -> list[dict[str, Any]]:
        if not self.configured:
            raise RuntimeError("Jira is not configured (JIRA_BASE / JIRA_EMAIL / JIRA_API_TOKEN)")

        issues: list[dict[str, Any]] = []
        next_page_token: str | None = None
        async with httpx.AsyncClient(timeout=60.0) as client:
            while len(issues) < max_results:
                payload: dict[str, Any] = {
                    "jql": jql,
                    "maxResults": min(100, max_results - len(issues)),
                    "fields": [
                        "summary",
                        "status",
                        "priority",
                        "project",
                        "assignee",
                        "updated",
                        "issuetype",
                    ],
                }
                if next_page_token:
                    payload["nextPageToken"] = next_page_token
                resp = await client.post(
                    f"{self.base}/rest/api/3/search/jql",
                    headers=self._headers(),
                    json=payload,
                )
                if not resp.is_success:
                    raise RuntimeError(
                        f"Jira search failed HTTP {resp.status_code}: {resp.text[:400]}"
                    )
                data = resp.json()
                batch = data.get("issues") or []
                issues.extend(batch)
                next_page_token = data.get("nextPageToken")
                if not next_page_token or not batch:
                    break
        return issues

    async def list_projects(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(
                f"{self.base}/rest/api/3/project/search",
                headers=self._headers(),
                params={"maxResults": 100},
            )
            if not resp.is_success:
                raise RuntimeError(
                    f"Jira projects failed HTTP {resp.status_code}: {resp.text[:300]}"
                )
            return list((resp.json() or {}).get("values") or [])

    def _exclude_jql(self) -> str:
        if not self.exclude:
            return ""
        parts = [f'project != {key}' for key in sorted(self.exclude)]
        return " AND " + " AND ".join(parts)

    async def build_open_items_brief(self) -> str:
        """Compact snapshot for Grok: counts + my items + high priority + recent."""
        excl = self._exclude_jql()
        projects = await self.list_projects()
        projects = [
            p
            for p in projects
            if str(p.get("key") or "").upper() not in self.exclude
        ]

        lines: list[str] = []
        lines.append("# Jira open-items snapshot")
        lines.append(
            f"Excluded projects: {', '.join(sorted(self.exclude)) or '(none)'}"
        )
        lines.append("")

        # Per-project counts (bounded: stop counting a project after 200)
        lines.append("## Open counts by project")
        counts: list[tuple[str, str, int]] = []
        for p in sorted(projects, key=lambda x: x.get("key") or ""):
            key = p.get("key") or "?"
            name = p.get("name") or key
            jql = f'project = {key} AND statusCategory != Done'
            try:
                issues = await self.search(jql, max_results=200)
                n = len(issues)
                # if we hit cap, mark as 200+
                label_n = n if n < 200 else f"{n}+"
            except Exception as exc:
                log.warning("count failed for %s: %s", key, exc)
                label_n = "err"
                n = -1
            if n == 0:
                continue
            counts.append((key, name, n if isinstance(label_n, int) else 200))
            lines.append(f"- {key} ({name}): {label_n} open")

        lines.append("")
        lines.append("## Assigned to me (open)")
        mine = await self.search(
            f'assignee = currentUser() AND statusCategory != Done{excl} '
            f"ORDER BY priority ASC, updated DESC",
            max_results=80,
        )
        if not mine:
            lines.append("(none)")
        for i in mine:
            lines.append(self._fmt_issue(i))

        lines.append("")
        lines.append("## High / Highest priority (open, any assignee)")
        high = await self.search(
            f'statusCategory != Done AND priority in (Highest, High){excl} '
            f"ORDER BY priority ASC, updated DESC",
            max_results=50,
        )
        if not high:
            lines.append("(none)")
        for i in high:
            lines.append(self._fmt_issue(i))

        lines.append("")
        lines.append("## Recently updated open (any assignee)")
        recent = await self.search(
            f"statusCategory != Done{excl} ORDER BY updated DESC",
            max_results=30,
        )
        for i in recent:
            lines.append(self._fmt_issue(i))

        text = "\n".join(lines)
        # hard cap for model context
        if len(text) > 60000:
            text = text[:60000] + "\n\n[truncated]"
        return text

    @staticmethod
    def _fmt_issue(issue: dict[str, Any]) -> str:
        fields = issue.get("fields") or {}
        key = issue.get("key") or "?"
        summary = fields.get("summary") or ""
        status = ((fields.get("status") or {}).get("name")) or "?"
        pri = ((fields.get("priority") or {}).get("name")) or "-"
        proj = ((fields.get("project") or {}).get("key")) or "?"
        itype = ((fields.get("issuetype") or {}).get("name")) or "?"
        assignee = fields.get("assignee") or {}
        who = assignee.get("displayName") if assignee else "Unassigned"
        updated = fields.get("updated") or ""
        return (
            f"- {key} [{proj} · {itype} · {status} · {pri}] {summary} "
            f"(assignee={who}; updated={updated})"
        )


async def expand_prompt_placeholders(template: str, settings: Settings, *, date_str: str) -> str:
    text = (template or "").replace("{{date}}", date_str).replace("{{DATE}}", date_str)
    if "{{jira_open_summary}}" not in text and "{{JIRA_OPEN_SUMMARY}}" not in text:
        return text

    client = JiraClient(settings)
    if not client.configured:
        brief = (
            "[Jira not configured on server — set JIRA_BASE, JIRA_EMAIL, JIRA_API_TOKEN]"
        )
    else:
        brief = await client.build_open_items_brief()

    return (
        text.replace("{{jira_open_summary}}", brief).replace(
            "{{JIRA_OPEN_SUMMARY}}", brief
        )
    )
