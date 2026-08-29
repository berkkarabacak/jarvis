from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from app.agents.registry import DEFAULT_AGENT_ID
from app.config import Settings
from app.integrations.jira import expand_prompt_placeholders
from app.jobs.tab_analysis import invoke_desktop_look_goal
from app.jarvis.agent import is_desktop_look_job
from app.llm.base import LlmProvider
from app.llm.factory import resolve_model
from app.memory.context import build_memory_context, make_log_entry_from_run
from app.memory.sanitize import sanitize_text
from app.notify.diagnostics import NotifyDiagnostics
from app.notify.email import send_email
from app.notify.slack import notify_run_slack
from app.runner.parse import COMPACTION_SYSTEM_PROMPT, SYSTEM_PROMPT, parse_job_output
from app.store.jobs import Job, JobStore, Run
from app.store.memories import MemoryStore
from app.store.messages import MessageStore

log = logging.getLogger("agent_orchestrator.runner")


class JobRunner:
    def __init__(
        self,
        *,
        jobs: JobStore,
        llm: LlmProvider,
        settings: Settings,
        notify_diag: NotifyDiagnostics | None = None,
        memories: MemoryStore | None = None,
        messages: MessageStore | None = None,
        agent_id: str = DEFAULT_AGENT_ID,
    ) -> None:
        self.jobs = jobs
        self.llm = llm
        self.settings = settings
        self.notify_diag = notify_diag
        self.memories = memories
        self.messages = messages
        self.agent_id = agent_id

    async def run_job(self, job_id: str, *, idempotency_key: str | None = None) -> Run:
        if idempotency_key:
            existing = await self.jobs.find_run_by_idempotency(job_id, idempotency_key)
            if existing is not None:
                return existing

        job = await self.jobs.get_job(job_id)
        if job is None:
            raise KeyError(f"job not found: {job_id}")
        if not job.enabled:
            raise RuntimeError(f"job {job_id} is disabled")

        runner_kind = (getattr(job, "runner", None) or "llm").strip().lower()
        if runner_kind == "herdr":
            return await self._run_herdr_job(job, idempotency_key=idempotency_key)

        # Look+keys tab analysis is a regular job goal on this same clock
        # (cron + POST /api/jobs/{id}/run). Not a second scheduler.
        if is_desktop_look_job(job.prompt_template or ""):
            return await self._run_desktop_look_job(
                job, idempotency_key=idempotency_key
            )

        llm_status = await self.llm.status()
        model_requested, model_mode = resolve_model(
            settings=self.settings,
            job_model=job.model,
            job_model_mode=job.model_mode,
        )

        if not llm_status.healthy:
            run = await self.jobs.create_run(
                job_id=job_id,
                status="failed",
                input_snapshot=None,
                idempotency_key=idempotency_key,
            )
            return await self.jobs.finish_run(
                run.id,
                status="failed",
                error=f"LLM not healthy: {llm_status.last_error or 'check provider settings'}",
                llm_provider=self.llm.name,
                model_requested=model_requested,
            )

        short_memory = job.memory_doc or ""
        if len(short_memory) > self.settings.memory_max_chars:
            compacted = await self._compact_memory(model_requested, short_memory)
            if (compacted or "").strip():
                short_memory = sanitize_text(compacted, max_chars=self.settings.memory_max_chars)
                try:
                    await self.jobs.update_memory_safe(job_id, short_memory)
                except Exception as exc:
                    log.warning("short memory compact persist failed: %s", exc)

        try:
            await self.jobs.compact_memory_log(
                job_id,
                keep_recent=max(5, self.settings.memory_log_keep // 2),
                compact_after=self.settings.memory_log_compact_after,
            )
        except Exception as exc:
            log.warning("memory log compact failed: %s", exc)

        memory_context = await build_memory_context(
            self.jobs,
            self.settings,
            job_id=job_id,
            short_memory=short_memory,
        )
        bank = ""
        if self.memories is not None:
            try:
                bank = await self.memories.context_for_agent(
                    actor_agent_id=self.agent_id,
                    max_chars=min(8000, self.settings.memory_context_max_chars // 2),
                )
            except Exception as exc:
                log.warning("agent memory bank failed: %s", exc)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        try:
            user_instruction = await expand_prompt_placeholders(
                job.prompt_template,
                self.settings,
                date_str=today,
            )
        except Exception as exc:
            run = await self.jobs.create_run(
                job_id=job_id,
                status="failed",
                input_snapshot=None,
                idempotency_key=idempotency_key,
            )
            return await self.jobs.finish_run(
                run.id,
                status="failed",
                error=f"Prompt expansion failed: {exc}"[:4000],
                llm_provider=self.llm.name,
                model_requested=model_requested,
            )

        user_content = (
            f"## Date\n{today}\n\n"
            f"{memory_context}\n\n"
            f"{bank}\n\n"
            f"## Today's task\n{user_instruction}\n"
        )

        input_snapshot = json.dumps(
            {
                "model": model_requested,
                "model_mode": model_mode,
                "llm_provider": self.llm.name,
                "agent_id": self.agent_id,
                "memory_version": job.memory_version,
                "date": today,
                "prompt_chars": len(user_instruction),
                "memory_context_chars": len(memory_context),
                "memory_bank_chars": len(bank),
            },
            ensure_ascii=False,
        )
        run = await self.jobs.create_run(
            job_id=job_id,
            status="running",
            input_snapshot=input_snapshot,
            idempotency_key=idempotency_key,
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        if self.messages is not None:
            try:
                await self.messages.append_many(
                    run_id=run.id, messages=messages, agent_id=self.agent_id
                )
            except Exception as exc:
                log.warning("message persist (input) failed: %s", exc)

        try:
            chat = await self.llm.chat(
                model=model_requested,
                messages=messages,
            )
            if self.messages is not None:
                try:
                    await self.messages.append(
                        run_id=run.id,
                        role="assistant",
                        content=chat.content or "",
                        agent_id=self.agent_id,
                    )
                except Exception as exc:
                    log.warning("message persist (output) failed: %s", exc)
            parsed = parse_job_output(chat.content)
            if parsed.update_memory and (parsed.memory or "").strip():
                await self.jobs.update_memory_safe(job_id, parsed.memory)

            result_text = (
                parsed.result
                if isinstance(parsed.result, str)
                else json.dumps(parsed.result, ensure_ascii=False, indent=2)
            )
            result_text = sanitize_text(result_text)

            finished = await self.jobs.finish_run(
                run.id,
                status="succeeded",
                result=result_text,
                raw_response=(chat.content or "")[:50000],
                tokens_in=chat.tokens_in,
                tokens_out=chat.tokens_out,
                llm_provider=chat.provider or self.llm.name,
                model_requested=model_requested,
                model_effective=chat.model or model_requested,
            )
            await self._append_run_to_log(job_id, finished)
            await self._maybe_email(job.name, job.notify_email, finished)
            await self._maybe_slack(job, finished)
            return finished
        except Exception as exc:
            finished = await self.jobs.finish_run(
                run.id,
                status="failed",
                error=str(exc)[:4000],
                raw_response=None,
                llm_provider=self.llm.name,
                model_requested=model_requested,
            )
            try:
                await self._append_run_to_log(job_id, finished)
            except Exception as log_exc:
                log.warning("failed-run log append error: %s", log_exc)
            try:
                await self._maybe_slack(job, finished)
            except Exception as slack_exc:
                log.warning("slack notify error (non-fatal): %s", slack_exc)
            return finished

    async def _run_desktop_look_job(
        self, job: Job, *, idempotency_key: str | None = None
    ) -> Run:
        """Same JobRunner clock: expand the stored goal and invoke Jarvis look+keys."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        try:
            user_instruction = await expand_prompt_placeholders(
                job.prompt_template, self.settings, date_str=today
            )
        except Exception as exc:
            run = await self.jobs.create_run(
                job_id=job.id, status="failed", idempotency_key=idempotency_key
            )
            return await self.jobs.finish_run(
                run.id,
                status="failed",
                error=f"Prompt expansion failed: {exc}"[:4000],
                llm_provider="jarvis",
            )

        model_requested, model_mode = resolve_model(
            settings=self.settings,
            job_model=job.model,
            job_model_mode=job.model_mode,
        )
        snap = {
            "runner": "llm",
            "path": "desktop_look",
            "goal": user_instruction,
            "date": today,
            "model": model_requested,
            "model_mode": model_mode,
            "prompt_chars": len(user_instruction),
        }
        run = await self.jobs.create_run(
            job_id=job.id,
            status="running",
            input_snapshot=json.dumps(snap, ensure_ascii=False),
            idempotency_key=idempotency_key,
        )
        try:
            invoked = await invoke_desktop_look_goal(
                user_instruction,
                model=model_requested,
                api_key=getattr(self.settings, "openrouter_api_key", None),
            )
            result_text = sanitize_text((invoked.get("text") or "").strip())
            if not result_text:
                result_text = "(Jarvis returned empty combined analysis)"
            try:
                await self.jobs.update_memory_safe(
                    job.id,
                    (job.memory_doc or "")
                    + f"\n\n## Tab analysis {today}\n{result_text[:2000]}",
                )
            except Exception as exc:
                log.warning("desktop look memory update failed: %s", exc)
            if self.messages is not None:
                try:
                    await self.messages.append_many(
                        run_id=run.id,
                        messages=[
                            {"role": "user", "content": user_instruction[:8000]},
                            {"role": "assistant", "content": result_text[:20000]},
                        ],
                        agent_id=self.agent_id,
                    )
                except Exception as exc:
                    log.warning("desktop look message persist failed: %s", exc)
            finished = await self.jobs.finish_run(
                run.id,
                status="succeeded",
                result=result_text[:50000],
                raw_response=json.dumps(
                    {
                        "text": result_text[:20000],
                        "tools_called": invoked.get("tools_called") or [],
                        "path": "desktop_look",
                    },
                    ensure_ascii=False,
                )[:50000],
                llm_provider="jarvis",
                model_requested=model_requested,
                model_effective=str(invoked.get("model") or model_requested),
            )
            await self._append_run_to_log(job.id, finished)
            await self._maybe_email(job.name, job.notify_email, finished)
            await self._maybe_slack(job, finished)
            return finished
        except Exception as exc:
            finished = await self.jobs.finish_run(
                run.id,
                status="failed",
                error=str(exc)[:4000],
                llm_provider="jarvis",
                model_requested=model_requested,
            )
            try:
                await self._append_run_to_log(job.id, finished)
            except Exception:
                pass
            try:
                await self._maybe_slack(job, finished)
            except Exception:
                pass
            return finished

    async def _run_herdr_job(self, job: Job, *, idempotency_key: str | None = None) -> Run:
        """Execute via Herdr CLI: workspace → agent start → prompt → read."""
        import json as _json
        import tempfile
        from pathlib import Path

        from app.integrations.herdr import (
            HerdrClient,
            HerdrConfig,
            HerdrError,
            sanitize_agent_name,
        )

        cfg = HerdrConfig.from_settings(self.settings)
        if not cfg.enabled:
            run = await self.jobs.create_run(
                job_id=job.id, status="failed", idempotency_key=idempotency_key
            )
            return await self.jobs.finish_run(
                run.id,
                status="failed",
                error="HERDR_ENABLED is false — enable Herdr in env to use runner=herdr",
                llm_provider="herdr",
            )

        client = HerdrClient(cfg)
        st = await client.status()
        if not st.get("available"):
            run = await self.jobs.create_run(
                job_id=job.id, status="failed", idempotency_key=idempotency_key
            )
            return await self.jobs.finish_run(
                run.id,
                status="failed",
                error=f"Herdr unavailable: {st.get('error') or 'binary not found'}",
                llm_provider="herdr",
            )

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        try:
            user_instruction = await expand_prompt_placeholders(
                job.prompt_template, self.settings, date_str=today
            )
        except Exception as exc:
            run = await self.jobs.create_run(
                job_id=job.id, status="failed", idempotency_key=idempotency_key
            )
            return await self.jobs.finish_run(
                run.id,
                status="failed",
                error=f"Prompt expansion failed: {exc}"[:4000],
                llm_provider="herdr",
            )

        kind = (job.herdr_agent_kind or cfg.default_kind or "opencode").strip()
        agent_name = sanitize_agent_name(
            job.herdr_agent_name or f"orch-{job.name}",
            fallback=f"orch-{job.id[:8]}",
        )
        cwd = (job.herdr_cwd or "").strip() or tempfile.mkdtemp(prefix="herdr-orch-")
        Path(cwd).mkdir(parents=True, exist_ok=True)
        label = (job.herdr_workspace_label or f"orch-{job.id[:8]}").strip()
        try:
            extra = _json.loads(job.herdr_extra_args or "[]")
            if not isinstance(extra, list):
                extra = []
            extra = [str(x) for x in extra]
        except Exception:
            extra = []

        snap = {
            "runner": "herdr",
            "kind": kind,
            "agent_name": agent_name,
            "cwd": cwd,
            "label": label,
            "date": today,
            "prompt_chars": len(user_instruction),
        }
        run = await self.jobs.create_run(
            job_id=job.id,
            status="running",
            input_snapshot=_json.dumps(snap, ensure_ascii=False),
            idempotency_key=idempotency_key,
        )

        try:
            pane_id = await client.workspace_create(cwd=cwd, label=label)
            await client.agent_start(agent_name, kind, pane_id, extra_args=extra)
            target = agent_name
            await client.agent_prompt(
                target,
                user_instruction,
                wait=True,
                until=("idle", "done", "blocked"),
                timeout_ms=cfg.timeout_ms,
            )
            text = await client.agent_read(target, source="recent-unwrapped", lines=200)
            result_text = sanitize_text(text or "")
            if not result_text.strip():
                result_text = "(Herdr returned empty output)"

            # Best-effort memory: store last result as short memory update
            try:
                await self.jobs.update_memory_safe(
                    job.id, (job.memory_doc or "") + f"\n\n## Herdr {today}\n{result_text[:2000]}"
                )
            except Exception as exc:
                log.warning("herdr memory update failed: %s", exc)

            if self.messages is not None:
                try:
                    await self.messages.append_many(
                        run_id=run.id,
                        messages=[
                            {"role": "user", "content": user_instruction[:8000]},
                            {"role": "assistant", "content": result_text[:20000]},
                        ],
                        agent_id=self.agent_id,
                    )
                except Exception as exc:
                    log.warning("herdr message persist failed: %s", exc)

            finished = await self.jobs.finish_run(
                run.id,
                status="succeeded",
                result=result_text[:50000],
                raw_response=result_text[:50000],
                llm_provider="herdr",
                model_requested=kind,
                model_effective=f"herdr:{kind}",
            )
            await self._append_run_to_log(job.id, finished)
            await self._maybe_email(job.name, job.notify_email, finished)
            await self._maybe_slack(job, finished)
            return finished
        except HerdrError as exc:
            finished = await self.jobs.finish_run(
                run.id,
                status="failed",
                error=str(exc)[:4000],
                llm_provider="herdr",
                model_requested=kind,
            )
            try:
                await self._append_run_to_log(job.id, finished)
            except Exception:
                pass
            try:
                await self._maybe_slack(job, finished)
            except Exception:
                pass
            return finished
        except Exception as exc:
            finished = await self.jobs.finish_run(
                run.id,
                status="failed",
                error=f"Herdr run failed: {exc}"[:4000],
                llm_provider="herdr",
                model_requested=kind,
            )
            try:
                await self._append_run_to_log(job.id, finished)
            except Exception:
                pass
            try:
                await self._maybe_slack(job, finished)
            except Exception:
                pass
            return finished

    async def _append_run_to_log(self, job_id: str, run: Run) -> None:
        kind, body = make_log_entry_from_run(run)
        await self.jobs.append_memory_log(job_id, kind=kind, body=body)
        try:
            await self.jobs.compact_memory_log(
                job_id,
                keep_recent=max(5, self.settings.memory_log_keep // 2),
                compact_after=self.settings.memory_log_compact_after,
            )
        except Exception as exc:
            log.warning("post-run log compact failed: %s", exc)

    async def _maybe_email(self, job_name: str, notify_email: str, run: Run) -> None:
        email = (notify_email or "").strip()
        if not email or run.status != "succeeded":
            return
        if not self.settings.email_configured:
            return
        subject = f"[Agent Orchestrator] {job_name}"
        model_line = ""
        if run.model_effective or run.model_requested:
            model_line = f"Model: {run.model_effective or run.model_requested}\n"
        body = (
            f"Job: {job_name}\n"
            f"Status: {run.status}\n"
            f"Run id: {run.id}\n"
            f"{model_line}\n"
            f"{run.result or ''}\n"
        )
        try:
            send_email(
                self.settings,
                to_addr=email,
                subject=subject,
                body=body,
            )
        except Exception as exc:
            log.warning("email notify failed: %s", exc)

    async def _maybe_slack(self, job: Job, run: Run) -> None:
        try:
            res = await notify_run_slack(
                self.settings,
                job_name=job.name,
                slack_on_success=bool(job.slack_on_success),
                slack_on_failure=bool(job.slack_on_failure),
                run_status=run.status,
                run_id=run.id,
                started_at=run.started_at,
                result=run.result,
                error=run.error,
            )
            if res is None:
                return
            if self.notify_diag is not None:
                await self.notify_diag.record_slack(
                    configured=self.settings.slack_configured,
                    ok=res.ok,
                    diagnostic=res.diagnostic,
                )
        except Exception as exc:
            log.warning("slack notify failed (non-fatal): %s", exc)
            if self.notify_diag is not None:
                try:
                    await self.notify_diag.record_slack(
                        configured=self.settings.slack_configured,
                        ok=False,
                        diagnostic=f"internal error: {type(exc).__name__}",
                    )
                except Exception:
                    pass

    async def _compact_memory(self, model: str, memory: str) -> str:
        try:
            chat = await self.llm.chat(
                model=model,
                messages=[
                    {"role": "system", "content": COMPACTION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Compact this memory to under {self.settings.memory_max_chars} "
                            f"characters. Preserve decisions and open threads. Never keep secrets.\n\n{memory}"
                        ),
                    },
                ],
            )
            parsed = parse_job_output(chat.content)
            if parsed.update_memory and (parsed.memory or "").strip():
                return parsed.memory
            return memory
        except Exception:
            return memory
