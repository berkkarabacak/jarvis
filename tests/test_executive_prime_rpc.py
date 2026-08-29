from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import app.executive.adapters.prime_rpc as prime_rpc_module
from app.executive.adapters.prime import (
    NullPrimeAgent,
    PrimeMessageResult,
    PrimeRuntimeError,
    PrimeUnavailableError,
)
from app.executive.adapters.prime_rpc import (
    OPENROUTER_AUTOROUTER_MODEL,
    PrimeJsonlRpcAgent,
    PrimeRpcClient,
    build_prime_agent_from_environment,
    build_prime_environment,
)
from app.executive.adapters.routing import HeuristicModelRouter
from app.executive.delegation import MAX_PLAN_CHARS, parse_executive_reply
from app.executive.registry import ExecutiveSessionRegistry
from app.executive.runtime import ExecutiveRuntime
from app.executive.safety import sanitize_public_text
from app.executive.store import InMemoryHandoffStore
from app.executive.telemetry import (
    BOUNDED_TEST_PROFILE,
    PUBLIC_GUEST_PROFILE,
    GenerationTelemetry,
)


def stream_receipt(
    generation_id: str,
    *,
    selected_model: str = "openai/gpt-5-nano",
    input_tokens: object = 20,
    output_tokens: object = 10,
    total_tokens: object = 30,
    actual_cost_usd: object = 0.0003,
    **extra: object,
) -> dict:
    return {
        "contract": "orch.openrouter.stream-receipt",
        "contract_version": "1.0",
        "source": "openrouter_stream",
        "generation_id": generation_id,
        "selected_model": selected_model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "actual_cost_usd": actual_cost_usd,
        **extra,
    }


def telemetry_stage(stage: object, *, frame_id: str = "stage-safe") -> dict:
    return {
        "type": "extension_ui_request",
        "id": frame_id,
        "method": "setStatus",
        "statusKey": "orch71.openrouter-telemetry-stage.v1",
        "statusText": stage,
    }


class FakePrimeSubprocessTransport:
    """Scripted byte transport that behaves like the pinned JSONL subprocess."""

    def __init__(
        self,
        assistant_texts: list[str] | None = None,
        *,
        name: str = "prime",
        lifecycle: list[str] | None = None,
        fail_prompt_at: set[int] | None = None,
        generation_ids: list[str] | None = None,
        header_generation_ids: list[tuple[str, ...]] | None = None,
        stream_receipts: list[tuple[dict | str, ...]] | None = None,
        telemetry_stages: list[tuple[str, ...]] | None = None,
        extra_status_frames: list[dict] | None = None,
        emit_compaction: bool = False,
        auto_retry_success: bool | None = True,
        state_model: object | None = None,
    ) -> None:
        self.name = name
        self.lifecycle = lifecycle
        self.argv: tuple[str, ...] = ()
        self.env: dict[str, str] = {}
        self.cwd: str | None = None
        self.commands: list[dict] = []
        self.closed = False
        self.concurrent_prompt = False
        self._prompt_active = False
        self._assistant_texts = list(assistant_texts or ["Executive update complete"])
        self._fail_prompt_at = set(fail_prompt_at or set())
        self._prompt_count = 0
        self._generation_ids = list(generation_ids or [])
        self._header_generation_ids = list(header_generation_ids or [])
        self._stream_receipts = (
            None if stream_receipts is None else list(stream_receipts)
        )
        self._telemetry_stages = list(telemetry_stages or [])
        self._extra_status_frames = list(extra_status_frames or [])
        self._emit_compaction = emit_compaction
        self._auto_retry_success = auto_retry_success
        self._state_model = (
            {
                "provider": "openrouter",
                "id": OPENROUTER_AUTOROUTER_MODEL,
                "input": ["text"],
                "contextWindow": 3_000,
                "maxTokens": 600,
            }
            if state_model is None
            else state_model
        )
        self.models_config: dict | None = None
        self.runtime_config_dir: Path | None = None
        self.extension_source: str | None = None
        self._completed_texts: asyncio.Queue[str] = asyncio.Queue()
        self._frames: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._completion_tasks: list[asyncio.Task[None]] = []

    async def start(self, *, argv, env, cwd) -> None:
        self.argv = tuple(argv)
        self.env = dict(env)
        self.cwd = cwd
        coding_dir = self.env.get("PRIME_AGENT_CODING_AGENT_DIR")
        if coding_dir:
            self.runtime_config_dir = Path(coding_dir)
            self.models_config = json.loads(
                (self.runtime_config_dir / "models.json").read_text(encoding="utf-8")
            )
            extension_path = self.runtime_config_dir / "generation-receipt.js"
            if extension_path.is_file():
                self.extension_source = extension_path.read_text(encoding="utf-8")
        if self.lifecycle is not None:
            self.lifecycle.append(f"start:{self.name}")

    async def write_line(self, line: bytes) -> None:
        assert line.endswith(b"\n")
        assert b"\n" not in line[:-1]
        command = json.loads(line)
        self.commands.append(command)
        request_id = command["id"]
        kind = command["type"]

        if kind == "get_state":
            await self._emit(
                {
                    "id": request_id,
                    "type": "response",
                    "command": kind,
                    "success": True,
                    "data": {
                        "sessionId": "PRIVATE_VENDOR_SESSION_ID",
                        "sessionFile": "C:/private/browser-session.jsonl",
                        "isStreaming": False,
                        "model": self._state_model,
                    },
                }
            )
            return
        if kind == "prompt":
            self._prompt_count += 1
            if self.lifecycle is not None:
                self.lifecycle.append(f"prompt:{self.name}:{self._prompt_count}")
            if self._prompt_count in self._fail_prompt_at:
                await self._emit(
                    {
                        "id": request_id,
                        "type": "response",
                        "command": kind,
                        "success": False,
                    }
                )
                return
            if self._prompt_active:
                self.concurrent_prompt = True
            self._prompt_active = True
            await self._emit(
                {
                    "id": request_id,
                    "type": "response",
                    "command": kind,
                    "success": True,
                }
            )
            text = self._assistant_texts.pop(0)
            self._completion_tasks.append(
                asyncio.create_task(self._complete_turn(text))
            )
            return
        if kind == "set_auto_retry":
            if self._auto_retry_success is None:
                return
            await self._emit(
                {
                    "id": request_id,
                    "type": "response",
                    "command": kind,
                    "success": self._auto_retry_success,
                }
            )
            return
        if kind == "set_auto_compaction":
            await self._emit(
                {
                    "id": request_id,
                    "type": "response",
                    "command": kind,
                    "success": True,
                }
            )
            return
        if kind == "get_last_assistant_text":
            text = await self._completed_texts.get()
            await self._emit(
                {
                    "id": request_id,
                    "type": "response",
                    "command": kind,
                    "success": True,
                    "data": {"text": text},
                }
            )
            return
        if kind == "abort":
            await self._emit(
                {
                    "id": request_id,
                    "type": "response",
                    "command": kind,
                    "success": True,
                }
            )
            return
        raise AssertionError(f"unexpected command: {kind}")

    async def _complete_turn(self, text: str) -> None:
        await asyncio.sleep(0.01)
        for frame in self._extra_status_frames:
            await self._emit(frame)
        stages = self._telemetry_stages.pop(0) if self._telemetry_stages else ()
        message_stage_index = next(
            (
                index
                for index, stage in enumerate(stages)
                if stage.startswith("message_receipt_")
            ),
            len(stages),
        )
        early_stages = stages[:message_stage_index]
        message_stages = stages[message_stage_index:]
        for index, stage in enumerate(early_stages):
            await self._emit(
                telemetry_stage(
                    stage,
                    frame_id=f"stage-{self._prompt_count}-{index}",
                )
            )
        generation_ids: tuple[str, ...] = ()
        if self._header_generation_ids:
            generation_ids = self._header_generation_ids.pop(0)
            for index, generation_id in enumerate(generation_ids):
                await self._emit(
                    {
                        "type": "extension_ui_request",
                        "id": f"receipt-{self._prompt_count}-{index}",
                        "method": "setStatus",
                        "statusKey": "orch71.openrouter-generation.v1",
                        "statusText": generation_id,
                    }
                )
        if self._stream_receipts is None:
            receipts: tuple[dict | str, ...] = (
                (stream_receipt(generation_ids[0]),) if len(generation_ids) == 1 else ()
            )
        else:
            receipts = self._stream_receipts.pop(0) if self._stream_receipts else ()
        for index, receipt in enumerate(receipts):
            await self._emit(
                {
                    "type": "extension_ui_request",
                    "id": f"stream-receipt-{self._prompt_count}-{index}",
                    "method": "setStatus",
                    "statusKey": "orch71.openrouter-stream-receipt.v1",
                    "statusText": (
                        receipt
                        if isinstance(receipt, str)
                        else json.dumps(receipt, separators=(",", ":"))
                    ),
                }
            )
        for index, stage in enumerate(message_stages):
            await self._emit(
                telemetry_stage(
                    stage,
                    frame_id=f"message-stage-{self._prompt_count}-{index}",
                )
            )
        if self._emit_compaction:
            await self._emit(
                {
                    "type": "auto_compaction_end",
                    "summary": "SYNTHETIC_PRIVATE_COMPACTION_SUMMARY",
                }
            )
        # These payloads must be ignored in full. They deliberately contain
        # synthetic sentinels that may never reach a result/event/diagnostic.
        await self._emit(
            {
                "type": "message_update",
                "assistantMessageEvent": {
                    "type": "thinking_delta",
                    "delta": "SYNTHETIC_PRIVATE_REASONING_SENTINEL",
                },
            }
        )
        await self._emit(
            {
                "type": "tool_execution_end",
                "result": {"text": "API_SECRET=SYNTHETIC_TOOL_SECRET"},
            }
        )
        await self._completed_texts.put(text)
        messages = [{"private_reasoning": "SYNTHETIC_AGENT_END_REASONING"}]
        if self._generation_ids:
            messages.append(
                {
                    "role": "assistant",
                    "responseId": self._generation_ids.pop(0),
                    "responseModel": "SYNTHETIC_UNTRUSTED_MODEL",
                    "usage": {"cost": {"total": 999}},
                    "content": "Bearer SYNTHETIC_AGENT_END_SECRET",
                }
            )
        await self._emit(
            {
                "type": "agent_end",
                "messages": messages,
            }
        )
        self._prompt_active = False

    async def _emit(self, frame: dict) -> None:
        await self._frames.put(
            (json.dumps(frame, separators=(",", ":")) + "\n").encode("utf-8")
        )

    async def read_line(self) -> bytes | None:
        return await self._frames.get()

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.lifecycle is not None:
            self.lifecycle.append(f"close:{self.name}")
        for task in self._completion_tasks:
            if not task.done():
                task.cancel()


def configure_fake_pinned_bundle(monkeypatch, tmp_path):
    install_root = tmp_path / "0.7.1"
    node_modules = install_root / "node_modules"
    package_root = node_modules / "prime-agent"
    bundle = package_root / "dist" / "bundle"
    bundle.mkdir(parents=True)
    (node_modules / "zeromq").mkdir()
    (node_modules / "zeromq" / "package.json").write_text(
        '{"type":"module"}\n', encoding="ascii"
    )
    package_lock = install_root / "package-lock.json"
    package_json = install_root / "package.json"
    package_lock.write_text('{"lockfileVersion":3}\n', encoding="ascii")
    package_json.write_text(
        '{"name":"prime-agent-runtime","version":"0.7.1"}\n',
        encoding="ascii",
    )
    runtime_assets = {
        "package.json": (
            '{"name":"@earendil-works/pi-coding-agent","type":"module",'
            '"piConfig":{"name":"prime-agent","configDir":".prime/agent"}}\n'
        ).encode("ascii"),
        "dist/modes/interactive/theme/prime.json": b'{"name":"prime"}\n',
        "dist/modes/interactive/theme/dark.json": b'{"name":"dark"}\n',
        "dist/modes/interactive/theme/light.json": b'{"name":"light"}\n',
    }
    pinned_assets = []
    for relative_name, content in runtime_assets.items():
        asset = package_root / relative_name
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_bytes(content)
        asset.chmod(0o644)
        pinned_assets.append(
            (
                relative_name,
                len(content),
                asset.stat().st_mode & 0o777,
                hashlib.sha256(content).hexdigest(),
            )
        )
    cli = bundle / "cli.js"
    cli.write_text('#!/usr/bin/env node\nimport "./chunk-test.js";\n', encoding="ascii")
    cli.chmod(0o755)
    (bundle / "chunk-test.js").write_text('import "zeromq";\n', encoding="ascii")
    usage_module = bundle / prime_rpc_module._USAGE_MODULE_NAME
    usage_module.write_bytes(
        b"function parseChunkUsage(rawUsage, model, usage, cacheWriteCost) {\n"
        + prime_rpc_module._USAGE_PATCH_ANCHOR
        + b"\n}\n"
    )
    daemon_early_module = bundle / prime_rpc_module._RPC_DAEMON_EARLY_MODULE_NAME
    daemon_early_module.write_bytes(
        b"function earlyDecision(args) {\n"
        + prime_rpc_module._RPC_DAEMON_EARLY_PATCH_ANCHOR
        + b"\n}\n"
    )
    daemon_runtime_module = bundle / prime_rpc_module._RPC_DAEMON_RUNTIME_MODULE_NAME
    daemon_runtime_module.write_bytes(
        prime_rpc_module._RPC_DAEMON_RUNTIME_PATCH_ANCHOR
        + b"\n"
        + prime_rpc_module._OUTPUT_CAP_PATCH_ANCHOR
        + b"\n"
    )

    source_fingerprint = prime_rpc_module._bundle_fingerprint(bundle)
    expected_bundle = tmp_path / "expected-patched-bundle"
    shutil.copytree(bundle, expected_bundle, copy_function=shutil.copy2)
    expected_usage = expected_bundle / prime_rpc_module._USAGE_MODULE_NAME
    expected_mode = expected_usage.stat().st_mode
    expected_usage.write_bytes(
        expected_usage.read_bytes().replace(
            prime_rpc_module._USAGE_PATCH_ANCHOR,
            prime_rpc_module._USAGE_PATCH_REPLACEMENT,
            1,
        )
    )
    expected_usage.chmod(expected_mode)
    expected_daemon_early = (
        expected_bundle / prime_rpc_module._RPC_DAEMON_EARLY_MODULE_NAME
    )
    expected_daemon_early.write_bytes(
        expected_daemon_early.read_bytes().replace(
            prime_rpc_module._RPC_DAEMON_EARLY_PATCH_ANCHOR,
            prime_rpc_module._RPC_DAEMON_EARLY_PATCH_REPLACEMENT,
            1,
        )
    )
    expected_daemon_runtime = (
        expected_bundle / prime_rpc_module._RPC_DAEMON_RUNTIME_MODULE_NAME
    )
    expected_daemon_runtime.write_bytes(
        expected_daemon_runtime.read_bytes().replace(
            prime_rpc_module._RPC_DAEMON_RUNTIME_PATCH_ANCHOR,
            prime_rpc_module._RPC_DAEMON_RUNTIME_PATCH_REPLACEMENT,
            1,
        )
    )
    intermediate_daemon_runtime = expected_daemon_runtime.read_bytes()
    expected_daemon_runtime.write_bytes(
        intermediate_daemon_runtime.replace(
            prime_rpc_module._OUTPUT_CAP_PATCH_ANCHOR,
            prime_rpc_module._OUTPUT_CAP_PATCH_REPLACEMENT,
            1,
        )
    )
    patched_fingerprint = prime_rpc_module._bundle_fingerprint(expected_bundle)

    monkeypatch.setattr(
        prime_rpc_module,
        "_PINNED_PRIME_CLI_SHA256",
        hashlib.sha256(cli.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(
        prime_rpc_module,
        "_PINNED_PRIME_PACKAGE_LOCK_SHA256",
        hashlib.sha256(package_lock.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(
        prime_rpc_module,
        "_PINNED_PRIME_PACKAGE_JSON_SHA256",
        hashlib.sha256(package_json.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(
        prime_rpc_module,
        "_PINNED_RUNTIME_ASSETS",
        tuple(pinned_assets),
    )
    monkeypatch.setattr(
        prime_rpc_module,
        "_PINNED_BUNDLE_FILE_COUNT",
        source_fingerprint[0],
    )
    monkeypatch.setattr(
        prime_rpc_module,
        "_PINNED_BUNDLE_BYTES",
        source_fingerprint[1],
    )
    monkeypatch.setattr(
        prime_rpc_module,
        "_PINNED_BUNDLE_MODES",
        source_fingerprint[2],
    )
    monkeypatch.setattr(
        prime_rpc_module,
        "_PINNED_BUNDLE_TREE_SHA256",
        source_fingerprint[3],
    )
    monkeypatch.setattr(
        prime_rpc_module,
        "_PATCHED_BUNDLE_BYTES",
        patched_fingerprint[1],
    )
    monkeypatch.setattr(
        prime_rpc_module,
        "_PATCHED_BUNDLE_TREE_SHA256",
        patched_fingerprint[3],
    )
    monkeypatch.setattr(
        prime_rpc_module,
        "_USAGE_MODULE_SHA256",
        hashlib.sha256(usage_module.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(
        prime_rpc_module,
        "_PATCHED_USAGE_MODULE_SHA256",
        hashlib.sha256(expected_usage.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(
        prime_rpc_module,
        "_RPC_DAEMON_EARLY_MODULE_SHA256",
        hashlib.sha256(daemon_early_module.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(
        prime_rpc_module,
        "_PATCHED_RPC_DAEMON_EARLY_MODULE_SHA256",
        hashlib.sha256(expected_daemon_early.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(
        prime_rpc_module,
        "_RPC_DAEMON_RUNTIME_MODULE_SHA256",
        hashlib.sha256(daemon_runtime_module.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(
        prime_rpc_module,
        "_PATCHED_RPC_DAEMON_RUNTIME_MODULE_SHA256",
        hashlib.sha256(intermediate_daemon_runtime).hexdigest(),
    )
    monkeypatch.setattr(
        prime_rpc_module,
        "_OUTPUT_CAP_MODULE_SHA256",
        hashlib.sha256(intermediate_daemon_runtime).hexdigest(),
    )
    monkeypatch.setattr(
        prime_rpc_module,
        "_PATCHED_OUTPUT_CAP_MODULE_SHA256",
        hashlib.sha256(expected_daemon_runtime.read_bytes()).hexdigest(),
    )
    return cli, bundle, node_modules


def test_bounded_bundle_manifest_and_patch_are_deterministic(
    monkeypatch,
    tmp_path,
):
    _, bundle, _ = configure_fake_pinned_bundle(monkeypatch, tmp_path)
    patch_specs = (
        (
            prime_rpc_module._USAGE_MODULE_NAME,
            prime_rpc_module._USAGE_PATCH_ANCHOR,
            prime_rpc_module._USAGE_PATCH_REPLACEMENT,
            prime_rpc_module._PATCHED_USAGE_MODULE_SHA256,
        ),
        (
            prime_rpc_module._RPC_DAEMON_EARLY_MODULE_NAME,
            prime_rpc_module._RPC_DAEMON_EARLY_PATCH_ANCHOR,
            prime_rpc_module._RPC_DAEMON_EARLY_PATCH_REPLACEMENT,
            prime_rpc_module._PATCHED_RPC_DAEMON_EARLY_MODULE_SHA256,
        ),
        (
            prime_rpc_module._RPC_DAEMON_RUNTIME_MODULE_NAME,
            prime_rpc_module._RPC_DAEMON_RUNTIME_PATCH_ANCHOR,
            prime_rpc_module._RPC_DAEMON_RUNTIME_PATCH_REPLACEMENT,
            prime_rpc_module._PATCHED_RPC_DAEMON_RUNTIME_MODULE_SHA256,
        ),
    )
    source_fingerprint = prime_rpc_module._bundle_fingerprint(bundle)

    assert source_fingerprint == (
        prime_rpc_module._PINNED_BUNDLE_FILE_COUNT,
        prime_rpc_module._PINNED_BUNDLE_BYTES,
        prime_rpc_module._PINNED_BUNDLE_MODES,
        prime_rpc_module._PINNED_BUNDLE_TREE_SHA256,
    )
    for module_name, anchor, replacement, patched_sha256 in patch_specs:
        module = bundle / module_name
        original = module.read_bytes()
        assert original.count(anchor) == 1
        patched = original.replace(anchor, replacement, 1)
        assert hashlib.sha256(patched).hexdigest() == patched_sha256
        assert module.read_bytes() == original

    runtime_module = bundle / prime_rpc_module._RPC_DAEMON_RUNTIME_MODULE_NAME
    runtime_after_daemon_patch = runtime_module.read_bytes().replace(
        prime_rpc_module._RPC_DAEMON_RUNTIME_PATCH_ANCHOR,
        prime_rpc_module._RPC_DAEMON_RUNTIME_PATCH_REPLACEMENT,
        1,
    )
    assert hashlib.sha256(runtime_after_daemon_patch).hexdigest() == (
        prime_rpc_module._OUTPUT_CAP_MODULE_SHA256
    )
    assert (
        runtime_after_daemon_patch.count(prime_rpc_module._OUTPUT_CAP_PATCH_ANCHOR) == 1
    )
    runtime_after_output_cap = runtime_after_daemon_patch.replace(
        prime_rpc_module._OUTPUT_CAP_PATCH_ANCHOR,
        prime_rpc_module._OUTPUT_CAP_PATCH_REPLACEMENT,
        1,
    )
    assert hashlib.sha256(runtime_after_output_cap).hexdigest() == (
        prime_rpc_module._PATCHED_OUTPUT_CAP_MODULE_SHA256
    )
    assert b"...options2,\n        maxTokens: 600," in runtime_after_output_cap
    assert b"maxRetries: 0," in runtime_after_output_cap
    assert (
        b"maxRetries: options2?.maxRetries ?? providerRetrySettings.maxRetries"
        not in runtime_after_output_cap
    )
    assert runtime_after_output_cap.index(b"maxTokens: 600") > (
        runtime_after_output_cap.index(b"...options2")
    )
    assert (
        runtime_after_output_cap.count(
            b"streamSimple(structuredClone(model2), context2, {"
        )
        == 1
    )
    assert (
        runtime_after_output_cap.count(
            b'plugins: [{ id: "auto-router", cost_quality_tradeoff: 10 }]'
        )
        == 1
    )
    assert runtime_after_output_cap.index(b"maxTokens: 600") < (
        runtime_after_output_cap.index(b"onPayload:")
    )
    assert runtime_after_output_cap.index(b"onPayload:") < (
        runtime_after_output_cap.index(b"apiKey:")
    )

    tampered = tmp_path / "tampered-bundle"
    shutil.copytree(bundle, tampered, copy_function=shutil.copy2)
    (tampered / "chunk-test.js").write_text("// drift\n", encoding="ascii")
    with pytest.raises(PrimeRuntimeError, match="verification failed"):
        prime_rpc_module._require_bundle_fingerprint(
            tampered,
            total_bytes=prime_rpc_module._PINNED_BUNDLE_BYTES,
            tree_sha256=prime_rpc_module._PINNED_BUNDLE_TREE_SHA256,
        )


def test_bounded_daemon_patches_change_only_rpc_decisions():
    assert prime_rpc_module._RPC_DAEMON_EARLY_PATCH_REPLACEMENT == (
        prime_rpc_module._RPC_DAEMON_EARLY_PATCH_ANCHOR.replace(
            b'args[modeIndex + 1] === "daemon"',
            b'(args[modeIndex + 1] === "daemon" || args[modeIndex + 1] === "rpc")',
            1,
        )
    )
    assert prime_rpc_module._RPC_DAEMON_RUNTIME_PATCH_REPLACEMENT == (
        prime_rpc_module._RPC_DAEMON_RUNTIME_PATCH_ANCHOR.replace(
            b"  return ",
            b'  return options.appMode !== "rpc" && ',
            1,
        )
    )
    for app_mode in ("interactive", "text", "json", "acp", "daemon"):
        for original_decision in (False, True):
            assert (app_mode != "rpc" and original_decision) == original_decision
    rpc_mode = "rpc"
    for original_decision in (False, True):
        assert (rpc_mode != "rpc" and original_decision) is False


def test_private_bundle_forces_output_cap_and_autorouter_policy_after_options():
    anchor = prime_rpc_module._OUTPUT_CAP_PATCH_ANCHOR
    replacement = prime_rpc_module._OUTPUT_CAP_PATCH_REPLACEMENT

    assert anchor.count(b"...options2") == 1
    assert (
        anchor.count(
            b"maxRetries: options2?.maxRetries ?? providerRetrySettings.maxRetries"
        )
        == 1
    )
    assert b"maxTokens" not in anchor
    assert b"onPayload" not in anchor
    assert b"structuredClone(model2)" not in anchor
    assert replacement.count(b"structuredClone(model2)") == 1
    assert replacement.count(b"maxTokens: 600") == 1
    assert replacement.count(b"maxRetries: 0") == 1
    assert (
        b"maxRetries: options2?.maxRetries ?? providerRetrySettings.maxRetries"
        not in replacement
    )
    assert replacement.count(b"onPayload:") == 1
    assert (
        replacement.count(
            b'plugins: [{ id: "auto-router", cost_quality_tradeoff: 10 }]'
        )
        == 1
    )
    assert b'plugins: [{ id: "auto-beta-router"' not in replacement
    assert b"enabled: false" not in replacement
    assert replacement.index(b"...options2") < replacement.index(b"maxTokens: 600")
    assert replacement.index(b"maxTokens: 600") < replacement.index(b"onPayload:")
    assert replacement.index(b"onPayload:") < replacement.index(b"apiKey:")
    assert replacement.index(b"apiKey:") < replacement.index(b"maxRetries: 0")


def test_bounded_cli_spelling_selects_full_id_under_pinned_resolver():
    models = [
        {"provider": "openrouter", "id": "auto"},
        {"provider": "openrouter", "id": "openrouter/auto"},
    ]

    def resolve_with_explicit_provider(cli_model: str) -> str | None:
        prefix = "openrouter/"
        pattern = (
            cli_model[len(prefix) :]
            if cli_model.lower().startswith(prefix)
            else cli_model
        )
        canonical = [
            model
            for model in models
            if f"{model['provider']}/{model['id']}".lower() == pattern.lower()
        ]
        if len(canonical) == 1:
            return canonical[0]["id"]
        by_id = [model for model in models if model["id"].lower() == pattern.lower()]
        return by_id[0]["id"] if len(by_id) == 1 else None

    assert resolve_with_explicit_provider(OPENROUTER_AUTOROUTER_MODEL) == "auto"
    assert (
        resolve_with_explicit_provider(f"openrouter/{OPENROUTER_AUTOROUTER_MODEL}")
        == "auto"
    )
    assert (
        resolve_with_explicit_provider(prime_rpc_module._BOUNDED_PRIME_CLI_MODEL)
        == OPENROUTER_AUTOROUTER_MODEL
    )
    assert set(
        prime_rpc_module._BOUNDED_MODEL_OVERRIDES["providers"]["openrouter"][
            "modelOverrides"
        ]
    ) == {OPENROUTER_AUTOROUTER_MODEL}


def test_private_bundle_forces_zero_retries_into_modeled_provider():
    node = shutil.which("node")
    assert node is not None, "Node.js is required to verify the pinned Prime patch"
    seam = prime_rpc_module._OUTPUT_CAP_PATCH_REPLACEMENT.decode("ascii")
    script = (
        """
import assert from "node:assert/strict";
const model2 = { provider: "openrouter", id: "openrouter/auto", input: ["text"] };
const context2 = { messages: [] };
const options2 = {
  maxRetries: 999,
  maxRetryDelayMs: 999999,
  maxTokens: 999999,
  headers: { "x-hostile": "true" }
};
const providerRetrySettings = {
  timeoutMs: 90000,
  maxRetries: 888,
  maxRetryDelayMs: 777
};
const auth = { apiKey: "SYNTHETIC_KEY", headers: { "x-safe": "true" } };
let providerCalls = 0;
function streamSimple(model, context, receivedOptions) {
  providerCalls += 1;
  return { model, context, receivedOptions };
}
function boundedStream() {
"""
        + seam
        + """
        maxRetryDelayMs: options2?.maxRetryDelayMs ?? providerRetrySettings.maxRetryDelayMs,
        headers: auth.headers || options2?.headers ? { ...auth.headers, ...options2?.headers } : void 0
      });
}
const modeled = boundedStream();
assert.equal(providerCalls, 1);
assert.equal(modeled.receivedOptions.maxRetries, 0);
assert.equal(modeled.receivedOptions.maxTokens, 600);
assert.equal(typeof modeled.receivedOptions.onPayload, "function");
assert.equal(options2.maxRetries, 999);
assert.equal(providerRetrySettings.maxRetries, 888);
console.log("ok");
"""
    )
    completed = subprocess.run(
        [node, "--input-type=module", "--eval", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ok"


def test_private_autorouter_payload_gate_is_fail_closed_before_network():
    node = shutil.which("node")
    assert node is not None, "Node.js is required to verify the pinned Prime patch"
    callback = prime_rpc_module._BOUNDED_AUTOROUTER_ON_PAYLOAD.decode("ascii")
    script = (
        """
import assert from "node:assert/strict";
let options2 = {};
const enforceBoundedPayload = """
        + callback
        + """;
const requestModel = {
  provider: "openrouter",
  id: "openrouter/auto",
  input: ["text"],
  cost: { input: 1, output: 5 }
};
const makePayload = () => ({
  model: "openrouter/auto",
  messages: [{ role: "user", content: "safe bounded prompt" }],
  stream: true,
  stream_options: { include_usage: true },
  store: false,
  max_completion_tokens: 600,
  temperature: 0.25,
  reasoning: { effort: "none" },
  provider: {
    sort: "price",
    require_parameters: true,
    data_collection: "deny",
    max_price: { prompt: 1, completion: 5, request: 0, image: 0, audio: 0 }
  },
  plugins: [{ id: "web", max_results: 100 }]
});
let networkCalls = 0;
async function dispatch(payload, model = requestModel, hook) {
  options2 = { onPayload: hook };
  const bounded = await enforceBoundedPayload(payload, model);
  networkCalls += 1;
  return bounded;
}

let hookCalls = 0;
const accepted = await dispatch(makePayload(), requestModel, async (payload) => {
  hookCalls += 1;
  await Promise.resolve();
  return payload;
});
assert.equal(hookCalls, 1);
assert.equal(networkCalls, 1);
assert.equal(accepted.temperature, 0.25);
assert.deepEqual(accepted.plugins, [
  { id: "auto-router", cost_quality_tradeoff: 10 }
]);
assert.deepEqual(accepted.provider.max_price, {
  prompt: 1,
  completion: 5,
  request: 0,
  image: 0,
  audio: 0
});

const acceptedUndefined = await dispatch(
  makePayload(),
  requestModel,
  async () => undefined
);
assert.deepEqual(acceptedUndefined.plugins, [
  { id: "auto-router", cost_quality_tradeoff: 10 }
]);
assert.equal(networkCalls, 2);

const delayedModel = structuredClone(requestModel);
const delayed = await dispatch(
  makePayload(),
  delayedModel,
  async (payload, model) => {
    setTimeout(() => {
      model.provider = "other";
      model.cost.input = 999;
    }, 0);
    return payload;
  }
);
await new Promise((resolve) => setTimeout(resolve, 10));
assert.equal(delayedModel.provider, "openrouter");
assert.equal(delayedModel.cost.input, 1);
assert.deepEqual(delayed.plugins, [
  { id: "auto-router", cost_quality_tradeoff: 10 }
]);
assert.equal(networkCalls, 3);

class PayloadInstance {
  constructor() {
    Object.assign(this, makePayload());
  }
}
const nullPrototype = Object.assign(Object.create(null), makePayload());
const accessorPayload = makePayload();
Object.defineProperty(accessorPayload, "max_completion_tokens", {
  enumerable: true,
  get: () => 600
});
const proxyPayload = makePayload();
proxyPayload.provider = new Proxy(proxyPayload.provider, {});
const rejected = [
  ["payload model", { ...makePayload(), model: "openrouter/auto-beta" }, requestModel],
  ["request provider", makePayload(), { ...requestModel, provider: "other" }],
  ["request model", makePayload(), { ...requestModel, id: "openrouter/auto-beta" }],
  ["single-prefix resolved model", makePayload(), {
    ...requestModel,
    id: "auto",
    input: ["text", "image"]
  }],
  ["request input", makePayload(), { ...requestModel, input: ["text", "image"] }],
  ["null hook", makePayload(), requestModel, async () => null],
  ["array hook", makePayload(), requestModel, async () => []],
  ["replacement hook", makePayload(), requestModel, async (p) => ({ ...p })],
  ["null prototype", nullPrototype, requestModel],
  ["class instance", new PayloadInstance(), requestModel],
  ["accessor", accessorPayload, requestModel],
  ["nested proxy", proxyPayload, requestModel],
  ["tools", { ...makePayload(), tools: [] }, requestModel],
  ["tool choice", { ...makePayload(), tool_choice: "none" }, requestModel],
  ["tool stream", { ...makePayload(), tool_stream: true }, requestModel],
  ["parallel tools", { ...makePayload(), parallel_tool_calls: false }, requestModel],
  ["legacy functions", { ...makePayload(), functions: [] }, requestModel],
  ["legacy function call", { ...makePayload(), function_call: "none" }, requestModel],
  ["fallback models", { ...makePayload(), models: ["paid/model"] }, requestModel],
  ["legacy route", { ...makePayload(), route: "fallback" }, requestModel],
  ["fallbacks", { ...makePayload(), fallbacks: true }, requestModel],
  ["include reasoning", { ...makePayload(), include_reasoning: true }, requestModel],
  ["reasoning effort", { ...makePayload(), reasoning_effort: "high" }, requestModel],
  ["reasoning enabled", { ...makePayload(), reasoning: { effort: "high" } }, requestModel],
  ["output cap", { ...makePayload(), max_completion_tokens: 999999 }, requestModel],
  ["legacy output cap", { ...makePayload(), max_tokens: 600 }, requestModel],
  ["provider price", {
    ...makePayload(),
    provider: {
      ...makePayload().provider,
      max_price: { ...makePayload().provider.max_price, request: 1 }
    }
  }, requestModel],
  ["provider policy", {
    ...makePayload(),
    provider: { ...makePayload().provider, data_collection: "allow" }
  }, requestModel],
  ["provider fallback", {
    ...makePayload(),
    provider: { ...makePayload().provider, allow_fallbacks: true }
  }, requestModel],
  ["hook mutation", makePayload(), requestModel, async (p) => {
    p.max_completion_tokens = 999999;
    return p;
  }],
  ["model hook mutation", makePayload(), { ...requestModel }, async (p, model) => {
    model.provider = "other";
    return p;
  }]
];
for (const [name, payload, model, hook] of rejected) {
  const before = networkCalls;
  await assert.rejects(
    dispatch(payload, model, hook),
    /Bounded OpenRouter request rejected/,
    name
  );
  assert.equal(networkCalls, before, `${name} reached the network`);
}
const beforeThrow = networkCalls;
await assert.rejects(
  dispatch(makePayload(), requestModel, async () => {
    throw new Error("synthetic prior hook failure");
  }),
  /Bounded OpenRouter request rejected/
);
assert.equal(networkCalls, beforeThrow);
console.log("ok");
"""
    )
    completed = subprocess.run(
        [node, "--input-type=module", "--eval", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ok"


def test_bounded_extension_emits_only_fixed_stages_for_provider_failures():
    node = shutil.which("node")
    assert node is not None, "Node.js is required to verify the bounded extension"
    source = json.dumps(prime_rpc_module._BOUNDED_GENERATION_EXTENSION)
    script = f"""
import assert from "node:assert/strict";
const source = {source};
const module = await import(
  "data:text/javascript;base64," + Buffer.from(source).toString("base64")
);

async function scenario({{ before = true, response, errorMessage }}) {{
  const handlers = new Map();
  const frames = [];
  module.default({{
    on(name, handler) {{ handlers.set(name, handler); }}
  }});
  const ctx = {{
    ui: {{
      setStatus(key, text) {{ frames.push({{ key, text }}); }}
    }}
  }};
  if (before) {{
    await handlers.get("before_provider_request")({{
      payload: {{ private: "API_SECRET=SYNTHETIC_PAYLOAD_SECRET" }}
    }}, ctx);
  }}
  if (response !== undefined) {{
    await handlers.get("after_provider_response")(response, ctx);
  }}
  await handlers.get("message_end")({{
    message: {{
      role: "assistant",
      provider: "openrouter",
      stopReason: "error",
      errorMessage
    }}
  }}, ctx);
  return frames
    .filter((frame) => frame.key === "orch71.openrouter-telemetry-stage.v1")
    .map((frame) => frame.text);
}}

assert.deepEqual(await scenario({{
  errorMessage: "Bounded OpenRouter request rejected"
}}), [
  "payload_callback_observed",
  "payload_policy_rejected",
  "message_receipt_invalid"
]);
assert.deepEqual(await scenario({{
  before: false,
  errorMessage: "Bounded OpenRouter request rejected"
}}), [
  "payload_callback_unobserved",
  "message_receipt_invalid"
]);

const failures = [
  ["400 API_SECRET=SYNTHETIC_400_SECRET", "provider_http_400"],
  ["402 API_SECRET=SYNTHETIC_402_SECRET", "provider_http_402"],
  ["404 API_SECRET=SYNTHETIC_404_SECRET", "provider_http_404"],
  ["429 API_SECRET=SYNTHETIC_429_SECRET", "provider_http_429"],
  ["451 API_SECRET=SYNTHETIC_451_SECRET", "provider_http_4xx_other"],
  ["503 API_SECRET=SYNTHETIC_503_SECRET", "provider_http_5xx"],
  ["301 API_SECRET=SYNTHETIC_301_SECRET", "provider_http_other"],
  ["400x API_SECRET=SYNTHETIC_UNANCHORED_SECRET", "provider_response_unobserved"],
  ["prefix 400 API_SECRET=SYNTHETIC_PREFIX_SECRET", "provider_response_unobserved"]
];
for (const [errorMessage, expected] of failures) {{
  const stages = await scenario({{ errorMessage }});
  assert.deepEqual(stages, [
    "payload_callback_observed",
    "payload_callback_passed",
    expected,
    "generation_header_unobserved",
    "message_receipt_invalid"
  ]);
  assert.equal(JSON.stringify(stages).includes("SYNTHETIC"), false);
  assert.equal(JSON.stringify(stages).includes("API_SECRET"), false);
}}

assert.deepEqual(await scenario({{
  response: {{ status: 200 }},
  errorMessage: "500 API_SECRET=SYNTHETIC_MISSING_HEADER_SECRET"
}}), [
  "payload_callback_observed",
  "payload_callback_passed",
  "provider_response_2xx",
  "generation_header_missing",
  "message_receipt_invalid"
]);
assert.deepEqual(await scenario({{
  response: {{ status: 200, headers: {{ "x-generation-id": "gen-safe" }} }},
  errorMessage: "500 API_SECRET=SYNTHETIC_MIDSTREAM_SECRET"
}}), [
  "payload_callback_observed",
  "payload_callback_passed",
  "provider_response_2xx",
  "generation_header_valid",
  "message_receipt_invalid"
]);
console.log("ok");
"""
    completed = subprocess.run(
        [node, "--input-type=module", "--eval", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert completed.returncode == 0, "bounded extension diagnostic test failed"
    assert completed.stdout.strip() == "ok"


@pytest.mark.asyncio
async def test_standard_prime_keeps_pinned_bundle_byte_for_byte(
    monkeypatch,
    tmp_path,
):
    cli, bundle, _ = configure_fake_pinned_bundle(monkeypatch, tmp_path)
    original_bundle = {
        item.name: item.read_bytes() for item in bundle.iterdir() if item.is_file()
    }
    prepare_calls: list[Path] = []

    async def reject_private_prepare(executable, runtime_dir, *, search_path=None):
        del executable, search_path
        prepare_calls.append(runtime_dir)
        raise AssertionError("standard Prime attempted to prepare a private bundle")

    monkeypatch.setattr(
        prime_rpc_module,
        "_prepare_bounded_prime_executable_async",
        reject_private_prepare,
    )
    transport = FakePrimeSubprocessTransport(["Standard path remains unchanged."])
    agent = PrimeJsonlRpcAgent(
        executable=str(cli),
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
        turn_timeout_seconds=1,
    )

    session = await agent.start_session(role_name="executive")
    result = await agent.send_message(session.session_id, message="Standard task")

    assert result.text == "Standard path remains unchanged."
    assert prepare_calls == []
    assert transport.argv[0] == str(cli)
    model_index = transport.argv.index("--model")
    assert transport.argv[model_index + 1] == OPENROUTER_AUTOROUTER_MODEL
    assert prime_rpc_module._BOUNDED_PRIME_CLI_MODEL not in transport.argv
    assert "PRIME_AGENT_CODING_AGENT_DIR" not in transport.env
    assert original_bundle == {
        item.name: item.read_bytes() for item in bundle.iterdir() if item.is_file()
    }
    await agent.stop_session(session.session_id)


@pytest.mark.parametrize(
    "mutation",
    ["tampered", "missing", "missing_anchor", "duplicate_anchor"],
)
@pytest.mark.parametrize("module_kind", ["early", "runtime"])
def test_bounded_daemon_patch_fails_closed_on_source_drift(
    monkeypatch,
    tmp_path,
    mutation,
    module_kind,
):
    _, bundle, _ = configure_fake_pinned_bundle(monkeypatch, tmp_path)
    if module_kind == "early":
        module_name = prime_rpc_module._RPC_DAEMON_EARLY_MODULE_NAME
        expected_source_sha256 = prime_rpc_module._RPC_DAEMON_EARLY_MODULE_SHA256
        patched_sha256 = prime_rpc_module._PATCHED_RPC_DAEMON_EARLY_MODULE_SHA256
        anchor = prime_rpc_module._RPC_DAEMON_EARLY_PATCH_ANCHOR
        replacement = prime_rpc_module._RPC_DAEMON_EARLY_PATCH_REPLACEMENT
    else:
        module_name = prime_rpc_module._RPC_DAEMON_RUNTIME_MODULE_NAME
        expected_source_sha256 = prime_rpc_module._RPC_DAEMON_RUNTIME_MODULE_SHA256
        patched_sha256 = prime_rpc_module._PATCHED_RPC_DAEMON_RUNTIME_MODULE_SHA256
        anchor = prime_rpc_module._RPC_DAEMON_RUNTIME_PATCH_ANCHOR
        replacement = prime_rpc_module._RPC_DAEMON_RUNTIME_PATCH_REPLACEMENT
    module = bundle / module_name
    if mutation == "tampered":
        module.write_bytes(module.read_bytes() + b"// drift\n")
    elif mutation == "missing":
        module.unlink()
    elif mutation == "missing_anchor":
        changed = module.read_bytes().replace(
            anchor,
            b"",
            1,
        )
        module.write_bytes(changed)
        expected_source_sha256 = hashlib.sha256(changed).hexdigest()
    else:
        changed = module.read_bytes() + b"\n" + anchor
        module.write_bytes(changed)
        expected_source_sha256 = hashlib.sha256(changed).hexdigest()

    with pytest.raises(PrimeRuntimeError, match="bounded module verification"):
        prime_rpc_module._patch_exact_bundle_module(
            bundle,
            module_name=module_name,
            source_sha256=expected_source_sha256,
            patched_sha256=patched_sha256,
            anchor=anchor,
            replacement=replacement,
        )


def test_bounded_runtime_assets_are_exact_and_source_is_unchanged(
    monkeypatch,
    tmp_path,
):
    _, bundle, _ = configure_fake_pinned_bundle(monkeypatch, tmp_path)
    package_root = bundle.parent.parent
    shadow_package = tmp_path / "shadow-package"
    originals = {
        relative_name: (package_root / relative_name).read_bytes()
        for relative_name, *_ in prime_rpc_module._PINNED_RUNTIME_ASSETS
    }

    prime_rpc_module._copy_pinned_runtime_assets(package_root, shadow_package)

    assert {
        path.relative_to(shadow_package).as_posix()
        for path in shadow_package.rglob("*")
        if path.is_file()
    } == set(originals)
    for (
        relative_name,
        expected_bytes,
        expected_mode,
        expected_sha256,
    ) in prime_rpc_module._PINNED_RUNTIME_ASSETS:
        source = package_root / relative_name
        copied = shadow_package / relative_name
        assert source.read_bytes() == originals[relative_name]
        assert copied.read_bytes() == originals[relative_name]
        assert len(copied.read_bytes()) == expected_bytes
        assert copied.stat().st_mode & 0o777 == expected_mode
        assert hashlib.sha256(copied.read_bytes()).hexdigest() == expected_sha256


@pytest.mark.parametrize("mutation", ["missing", "tampered"])
def test_bounded_runtime_assets_fail_closed_before_copy(
    monkeypatch,
    tmp_path,
    mutation,
):
    _, bundle, _ = configure_fake_pinned_bundle(monkeypatch, tmp_path)
    package_root = bundle.parent.parent
    target = package_root / "dist/modes/interactive/theme/dark.json"
    if mutation == "missing":
        target.unlink()
    else:
        target.write_bytes(b'{"name":"drift"}\n')
    shadow_package = tmp_path / "shadow-package"

    with pytest.raises(PrimeRuntimeError, match="runtime asset"):
        prime_rpc_module._copy_pinned_runtime_assets(package_root, shadow_package)

    assert shadow_package.exists() is False


@pytest.mark.skipif(os.name == "nt", reason="POSIX artifact modes are a Linux gate")
def test_bounded_runtime_assets_reject_mode_drift(monkeypatch, tmp_path):
    _, bundle, _ = configure_fake_pinned_bundle(monkeypatch, tmp_path)
    package_root = bundle.parent.parent
    target = package_root / "dist/modes/interactive/theme/light.json"
    target.chmod(0o600)

    with pytest.raises(PrimeRuntimeError, match="runtime asset"):
        prime_rpc_module._copy_pinned_runtime_assets(
            package_root,
            tmp_path / "shadow-package",
        )


@pytest.mark.skipif(
    os.name == "nt",
    reason="The production dependency bridge is a Linux directory symlink",
)
def test_bounded_private_bundle_is_exact_patched_and_dependency_complete(
    monkeypatch,
    tmp_path,
):
    cli, bundle, node_modules = configure_fake_pinned_bundle(monkeypatch, tmp_path)
    original_modules = {
        module_name: hashlib.sha256((bundle / module_name).read_bytes()).hexdigest()
        for module_name in (
            prime_rpc_module._USAGE_MODULE_NAME,
            prime_rpc_module._RPC_DAEMON_EARLY_MODULE_NAME,
            prime_rpc_module._RPC_DAEMON_RUNTIME_MODULE_NAME,
        )
    }
    executable_dir = tmp_path / "bin"
    executable_dir.mkdir()
    (executable_dir / "prime-agent").symlink_to(cli)
    runtime_dir = tmp_path / "private-runtime"
    runtime_dir.mkdir()

    shadow_cli = prime_rpc_module._prepare_bounded_prime_executable(
        "prime-agent",
        runtime_dir,
        search_path=str(executable_dir),
    )

    shadow_path = Path(shadow_cli)
    patched_usage = shadow_path.parent / prime_rpc_module._USAGE_MODULE_NAME
    assert shadow_path != cli
    assert shadow_path.is_file()
    assert "Object.prototype.hasOwnProperty.call(rawUsage" in patched_usage.read_text(
        encoding="utf-8"
    )
    assert "usage.cost.total = Number.NaN" in patched_usage.read_text(encoding="utf-8")
    patched_early = shadow_path.parent / prime_rpc_module._RPC_DAEMON_EARLY_MODULE_NAME
    patched_runtime = (
        shadow_path.parent / prime_rpc_module._RPC_DAEMON_RUNTIME_MODULE_NAME
    )
    assert (
        prime_rpc_module._RPC_DAEMON_EARLY_PATCH_REPLACEMENT
        in patched_early.read_bytes()
    )
    assert (
        prime_rpc_module._RPC_DAEMON_EARLY_PATCH_ANCHOR
        not in patched_early.read_bytes()
    )
    assert (
        prime_rpc_module._RPC_DAEMON_RUNTIME_PATCH_REPLACEMENT
        in patched_runtime.read_bytes()
    )
    assert (
        prime_rpc_module._RPC_DAEMON_RUNTIME_PATCH_ANCHOR
        not in patched_runtime.read_bytes()
    )
    assert prime_rpc_module._bundle_fingerprint(shadow_path.parent) == (
        prime_rpc_module._PINNED_BUNDLE_FILE_COUNT,
        prime_rpc_module._PATCHED_BUNDLE_BYTES,
        prime_rpc_module._PINNED_BUNDLE_MODES,
        prime_rpc_module._PATCHED_BUNDLE_TREE_SHA256,
    )
    for module_name, original_hash in original_modules.items():
        assert hashlib.sha256((bundle / module_name).read_bytes()).hexdigest() == (
            original_hash
        )
    bridge = runtime_dir / "node_modules"
    assert bridge.is_symlink()
    assert bridge.resolve(strict=True) == node_modules
    assert (bridge / "zeromq" / "package.json").is_file()
    assert (runtime_dir / "package.json").exists() is False
    shadow_package = shadow_path.parent.parent.parent
    shadow_package_json = json.loads(
        (shadow_package / "package.json").read_text(encoding="ascii")
    )
    assert shadow_package_json["type"] == "module"
    assert shadow_package_json["piConfig"] == {
        "name": "prime-agent",
        "configDir": ".prime/agent",
    }
    for (
        relative_name,
        expected_bytes,
        expected_mode,
        expected_sha256,
    ) in prime_rpc_module._PINNED_RUNTIME_ASSETS:
        source = bundle.parent.parent / relative_name
        copied = shadow_package / relative_name
        assert source.read_bytes() == copied.read_bytes()
        assert len(copied.read_bytes()) == expected_bytes
        assert copied.stat().st_mode & 0o777 == expected_mode
        assert hashlib.sha256(copied.read_bytes()).hexdigest() == expected_sha256

    original_usage = bundle / prime_rpc_module._USAGE_MODULE_NAME
    original_usage.write_bytes(original_usage.read_bytes() + b"// drift\n")
    second_runtime = tmp_path / "private-runtime-drift"
    second_runtime.mkdir()
    with pytest.raises(PrimeRuntimeError, match="verification failed"):
        prime_rpc_module._prepare_bounded_prime_executable(
            str(cli),
            second_runtime,
        )


@pytest.mark.asyncio
async def test_bounded_runtime_asset_failure_cleans_private_runtime(
    monkeypatch,
    tmp_path,
):
    cli, bundle, _ = configure_fake_pinned_bundle(monkeypatch, tmp_path)
    (bundle.parent.parent / "dist/modes/interactive/theme/prime.json").unlink()
    captured_runtime_dirs = []
    prepare = prime_rpc_module._prepare_bounded_prime_executable_async

    async def capture_prepare(executable, runtime_dir, *, search_path=None):
        captured_runtime_dirs.append(runtime_dir)
        return await prepare(executable, runtime_dir, search_path=search_path)

    monkeypatch.setattr(
        prime_rpc_module,
        "_prepare_bounded_prime_executable_async",
        capture_prepare,
    )
    transport = FakePrimeSubprocessTransport()
    agent = PrimeJsonlRpcAgent(
        executable=str(cli),
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
    )

    with pytest.raises(PrimeRuntimeError, match="runtime asset"):
        await agent.start_session(
            role_name="executive",
            metadata={"execution_profile": BOUNDED_TEST_PROFILE},
        )

    assert len(captured_runtime_dirs) == 1
    assert captured_runtime_dirs[0].exists() is False
    assert transport.closed is True
    assert await agent.list_sessions() == []


@pytest.mark.asyncio
async def test_prime_jsonl_rpc_filters_output_and_allowlists_process_boundary():
    transport = FakePrimeSubprocessTransport(
        ["Done. Authorization: Bearer SYNTHETIC_FAKE_TOKEN_123456"]
    )
    source_env = {
        "PATH": "C:/runtime/bin",
        "HOME": "C:/runtime/home",
        "LANG": "en_US.UTF-8",
        "OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET",
        "API_SECRET": "SYNTHETIC_SERVICE_SECRET",
        "XAI_API_KEY": "SYNTHETIC_GROK_SECRET",
        "TOKEN_ENCRYPTION_KEY": "SYNTHETIC_DATABASE_SECRET",
    }
    agent = PrimeJsonlRpcAgent(
        environment=source_env,
        transport_factory=lambda: transport,
        turn_timeout_seconds=1,
    )

    health = await agent.health()
    assert health["available"] is True
    assert health["version_verified"] is False
    assert "SYNTHETIC" not in json.dumps(health)

    session = await agent.start_session(
        role_name="executive",
        model=OPENROUTER_AUTOROUTER_MODEL,
        metadata={
            "mission_id": "m-safe",
            "OPENROUTER_API_KEY": "SYNTHETIC_METADATA_SECRET",
            "private_reasoning": "SYNTHETIC_METADATA_REASONING",
        },
    )
    assert transport.argv == (
        "prime-agent",
        "--mode",
        "rpc",
        "--provider",
        "openrouter",
        "--model",
        "openrouter/auto",
        "--no-session",
        "--no-tools",
    )
    assert "SYNTHETIC" not in " ".join(transport.argv)
    assert transport.env["OPENROUTER_API_KEY"] == "SYNTHETIC_OPENROUTER_SECRET"
    assert "API_SECRET" not in transport.env
    assert "XAI_API_KEY" not in transport.env
    assert "TOKEN_ENCRYPTION_KEY" not in transport.env
    assert "PRIVATE_VENDOR_SESSION_ID" not in json.dumps(session.to_dict())
    assert "browser-session" not in json.dumps(session.to_dict())
    assert "SYNTHETIC_METADATA" not in json.dumps(session.to_dict())
    assert [command["type"] for command in transport.commands] == ["get_state"]
    with pytest.raises(PrimeRuntimeError):
        await agent.start_session(
            role_name="reviewer", model=OPENROUTER_AUTOROUTER_MODEL
        )

    result = await agent.send_message(
        session.session_id,
        message="Status please OPENROUTER_API_KEY=SYNTHETIC_INPUT_SECRET",
    )
    serialized = json.dumps(result.to_dict())
    assert "SYNTHETIC_FAKE_TOKEN" not in serialized
    assert "SYNTHETIC_PRIVATE_REASONING" not in serialized
    assert "SYNTHETIC_TOOL_SECRET" not in serialized
    assert "[redacted]" in result.text
    prompt = next(
        command for command in transport.commands if command["type"] == "prompt"
    )
    assert "SYNTHETIC_INPUT_SECRET" not in prompt["message"]
    assert "[redacted]" in prompt["message"]

    await agent.stop_session(session.session_id)
    assert transport.closed is True
    assert any(command["type"] == "abort" for command in transport.commands)


@pytest.mark.asyncio
async def test_bounded_prime_uses_private_limits_and_provider_verified_receipt():
    class HistoryResolverMustNotRun:
        def __init__(self):
            self.called = False

        async def resolve(self, generation_id: str) -> GenerationTelemetry:
            del generation_id
            self.called = True
            raise AssertionError("bounded stream telemetry must bypass history")

    resolver = HistoryResolverMustNotRun()
    transport = FakePrimeSubprocessTransport(
        ["Safe bounded result"],
        generation_ids=["gen-untrusted-body-1"],
        header_generation_ids=[("gen-bounded-header-1",)],
    )
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
        generation_resolver=resolver,
        turn_timeout_seconds=1,
    )
    session = await agent.start_session(
        role_name="executive",
        metadata={"execution_profile": BOUNDED_TEST_PROFILE},
    )

    assert "--thinking" in transport.argv
    model_index = transport.argv.index("--model")
    assert transport.argv[model_index + 1] == prime_rpc_module._BOUNDED_PRIME_CLI_MODEL
    assert "--system-prompt" in transport.argv
    assert "--extension" in transport.argv
    assert "--no-extensions" in transport.argv
    assert "--no-skills" in transport.argv
    assert "--no-prompt-templates" in transport.argv
    assert "--no-context-files" in transport.argv
    assert transport.runtime_config_dir is not None
    assert transport.runtime_config_dir.is_dir()
    extension_index = transport.argv.index("--extension")
    assert Path(transport.argv[extension_index + 1]) == (
        transport.runtime_config_dir / "generation-receipt.js"
    )
    assert transport.extension_source is not None
    assert 'event.headers?.["x-generation-id"]' in transport.extension_source
    assert "orch71.openrouter-generation.v1" in transport.extension_source
    assert "orch71.openrouter-stream-receipt.v1" in transport.extension_source
    assert "orch71.openrouter-telemetry-stage.v1" in transport.extension_source
    assert 'pi.on("before_provider_request"' in transport.extension_source
    assert 'message.errorMessage === "Bounded OpenRouter request rejected"' in (
        transport.extension_source
    )
    assert 'pi.on("message_end"' in transport.extension_source
    assert "JSON.stringify" in transport.extension_source
    assert ".content" not in transport.extension_source
    assert "reasoning" not in transport.extension_source.lower()
    assert "tool" not in transport.extension_source.lower()
    assert "authorization" not in transport.extension_source.lower()
    assert "console" not in transport.extension_source
    assert "process" not in transport.extension_source
    assert "fetch" not in transport.extension_source
    assert "event.body" not in transport.extension_source
    assert "event.payload" not in transport.extension_source
    override = transport.models_config["providers"]["openrouter"]["modelOverrides"][
        "openrouter/auto"
    ]
    assert override["contextWindow"] == 3000
    assert override["maxTokens"] == 600
    routing = override["compat"]["openRouterRouting"]
    assert routing == {
        "data_collection": "deny",
        "max_price": {
            "audio": 0.0,
            "completion": 5.0,
            "image": 0.0,
            "prompt": 1.0,
            "request": 0.0,
        },
        "require_parameters": True,
        "sort": "price",
    }
    compaction = [
        command
        for command in transport.commands
        if command["type"] == "set_auto_compaction"
    ]
    assert compaction == [
        {
            "id": "req-3",
            "type": "set_auto_compaction",
            "enabled": False,
        }
    ]
    assert transport.commands[:3] == [
        {"id": "req-1", "type": "get_state"},
        {
            "id": "req-2",
            "type": "set_auto_retry",
            "enabled": False,
        },
        {
            "id": "req-3",
            "type": "set_auto_compaction",
            "enabled": False,
        },
    ]

    result = await agent.send_message(session.session_id, message="Bounded task")
    assert [command["type"] for command in transport.commands[:4]] == [
        "get_state",
        "set_auto_retry",
        "set_auto_compaction",
        "prompt",
    ]
    assert resolver.called is False
    assert result.generation is not None
    assert result.generation.actual_cost_usd.__str__() == "0.0003"
    assert result.generation.source == "openrouter_stream"
    assert "SYNTHETIC_AGENT_END" not in json.dumps(result.to_dict())
    runtime_dir = transport.runtime_config_dir
    await agent.stop_session(session.session_id)
    assert transport.closed is True
    assert runtime_dir.exists() is False
    assert await agent.list_sessions() == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state_model",
    [
        {},
        {
            "provider": "other",
            "id": "openrouter/auto",
            "input": ["text"],
            "contextWindow": 3_000,
            "maxTokens": 600,
        },
        {
            "provider": "openrouter",
            "id": "auto",
            "input": ["text"],
            "contextWindow": 3_000,
            "maxTokens": 600,
        },
        {
            "provider": "openrouter",
            "id": "openrouter/auto",
            "input": ["text", "image"],
            "contextWindow": 3_000,
            "maxTokens": 600,
        },
        {
            "provider": "openrouter",
            "id": "openrouter/auto",
            "input": ["text"],
            "contextWindow": 3_001,
            "maxTokens": 600,
        },
        {
            "provider": "openrouter",
            "id": "openrouter/auto",
            "input": ["text"],
            "contextWindow": 3_000,
            "maxTokens": 601,
        },
    ],
    ids=[
        "missing-fields",
        "wrong-provider",
        "wrong-id",
        "image-input",
        "wrong-context",
        "wrong-output",
    ],
)
async def test_bounded_prime_rejects_unattested_state_before_controls_or_prompt(
    state_model,
):
    transport = FakePrimeSubprocessTransport(state_model=state_model)
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
        command_timeout_seconds=0.02,
        cleanup_timeout_seconds=0.2,
    )

    with pytest.raises(PrimeRuntimeError, match="invalid bounded model state"):
        await agent.start_session(
            role_name="executive",
            metadata={"execution_profile": BOUNDED_TEST_PROFILE},
        )

    assert [command["type"] for command in transport.commands] == ["get_state"]
    assert not any(command["type"] == "prompt" for command in transport.commands)
    assert transport.closed is True
    assert transport.runtime_config_dir is not None
    assert transport.runtime_config_dir.exists() is False
    assert await agent.list_sessions() == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("auto_retry_success", "failure_text"),
    [
        (False, "set_auto_retry failed"),
        (None, "set_auto_retry timed out"),
    ],
)
async def test_bounded_prime_auto_retry_control_fails_before_prompt_and_cleans(
    auto_retry_success,
    failure_text,
):
    transport = FakePrimeSubprocessTransport(
        auto_retry_success=auto_retry_success,
    )
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
        command_timeout_seconds=0.02,
        cleanup_timeout_seconds=0.2,
    )

    with pytest.raises(PrimeRuntimeError, match=failure_text):
        await agent.start_session(
            role_name="executive",
            metadata={"execution_profile": BOUNDED_TEST_PROFILE},
        )

    assert [command["type"] for command in transport.commands] == [
        "get_state",
        "set_auto_retry",
    ]
    assert not any(command["type"] == "prompt" for command in transport.commands)
    assert transport.closed is True
    assert transport.runtime_config_dir is not None
    assert transport.runtime_config_dir.exists() is False
    assert await agent.list_sessions() == []


@pytest.mark.asyncio
async def test_public_guest_prime_reuses_private_limits_and_stream_receipt_path():
    transport = FakePrimeSubprocessTransport(
        ["Safe public guest result"],
        header_generation_ids=[("gen-public-guest-header",)],
    )
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
        turn_timeout_seconds=1,
    )
    session = await agent.start_session(
        role_name="executive",
        metadata={"execution_profile": PUBLIC_GUEST_PROFILE},
    )

    assert "--thinking" in transport.argv
    model_index = transport.argv.index("--model")
    assert transport.argv[model_index + 1] == prime_rpc_module._BOUNDED_PRIME_CLI_MODEL
    assert "--extension" in transport.argv
    assert "--no-context-files" in transport.argv
    override = transport.models_config["providers"]["openrouter"]["modelOverrides"][
        "openrouter/auto"
    ]
    assert override["contextWindow"] == 3_000
    assert override["maxTokens"] == 600
    assert override["compat"]["openRouterRouting"]["max_price"] == {
        "audio": 0.0,
        "completion": 5.0,
        "image": 0.0,
        "prompt": 1.0,
        "request": 0.0,
    }
    assert transport.commands[:3] == [
        {"id": "req-1", "type": "get_state"},
        {
            "id": "req-2",
            "type": "set_auto_retry",
            "enabled": False,
        },
        {
            "id": "req-3",
            "type": "set_auto_compaction",
            "enabled": False,
        },
    ]
    assert any(
        command["type"] == "set_auto_compaction" and command["enabled"] is False
        for command in transport.commands
    )
    result = await agent.send_message(session.session_id, message="Safe public task")
    assert result.generation is not None
    assert result.generation.source == "openrouter_stream"

    await agent.stop_session(session.session_id)
    assert await agent.list_sessions() == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stages", "expected"),
    [
        (
            ("payload_callback_unobserved", "message_receipt_invalid"),
            "telemetry_payload_callback_unobserved",
        ),
        (
            (
                "payload_callback_observed",
                "payload_policy_rejected",
                "message_receipt_invalid",
            ),
            "telemetry_payload_policy_rejected",
        ),
        (
            (
                "payload_callback_observed",
                "payload_callback_passed",
                "provider_response_unobserved",
                "generation_header_unobserved",
                "message_receipt_invalid",
            ),
            "telemetry_provider_response_unobserved",
        ),
        *[
            (
                (
                    "payload_callback_observed",
                    "payload_callback_passed",
                    provider,
                    "generation_header_unobserved",
                    "message_receipt_invalid",
                ),
                f"telemetry_{provider}",
            )
            for provider in (
                "provider_http_400",
                "provider_http_402",
                "provider_http_404",
                "provider_http_429",
                "provider_http_4xx_other",
                "provider_http_5xx",
                "provider_http_other",
            )
        ],
        (
            (
                "payload_callback_observed",
                "payload_callback_passed",
                "provider_response_2xx",
            ),
            "telemetry_provider_response_2xx",
        ),
        (
            (
                "payload_callback_observed",
                "payload_callback_passed",
                "provider_response_2xx",
                "generation_header_missing",
                "message_receipt_invalid",
            ),
            "telemetry_generation_header_missing",
        ),
        (
            (
                "payload_callback_observed",
                "payload_callback_passed",
                "provider_response_2xx",
                "generation_header_invalid",
                "message_receipt_invalid",
            ),
            "telemetry_generation_header_invalid",
        ),
        (
            (
                "payload_callback_observed",
                "payload_callback_passed",
                "provider_response_2xx",
                "generation_header_valid",
            ),
            "telemetry_message_receipt_unobserved",
        ),
        (
            (
                "payload_callback_observed",
                "payload_callback_passed",
                "provider_response_2xx",
                "generation_header_valid",
                "message_receipt_invalid",
            ),
            "telemetry_message_receipt_invalid",
        ),
        (
            (
                "payload_callback_observed",
                "payload_callback_passed",
                "provider_response_2xx",
                "generation_header_valid",
                "message_receipt_valid",
            ),
            "telemetry_adapter_correlation_failed",
        ),
    ],
)
async def test_bounded_prime_reports_only_fixed_terminal_telemetry_diagnostic(
    stages,
    expected,
):
    transport = FakePrimeSubprocessTransport(
        ["Safe diagnostic result"],
        header_generation_ids=[()],
        stream_receipts=[()],
        telemetry_stages=[stages],
    )
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
        turn_timeout_seconds=1,
    )
    session = await agent.start_session(
        role_name="executive",
        metadata={"execution_profile": BOUNDED_TEST_PROFILE},
    )

    result = await agent.send_message(session.session_id, message="Bounded task")
    health = await agent.health()

    assert result.generation is None
    assert result.telemetry_diagnostic == expected
    assert health["last_error"] == expected
    assert "SYNTHETIC_OPENROUTER_SECRET" not in repr(result)
    assert "telemetry_diagnostic" not in result.to_dict()
    await agent.stop_session(session.session_id)


@pytest.mark.asyncio
async def test_bounded_prime_reports_adapter_correlation_after_exact_stage_order():
    generation_id = "gen-stage-correlated"
    stages = (
        "payload_callback_observed",
        "payload_callback_passed",
        "provider_response_2xx",
        "generation_header_valid",
        "message_receipt_valid",
    )
    transport = FakePrimeSubprocessTransport(
        ["Safe correlated result"],
        header_generation_ids=[(generation_id,)],
        stream_receipts=[(stream_receipt(generation_id),)],
        telemetry_stages=[stages],
    )
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
        turn_timeout_seconds=1,
    )
    session = await agent.start_session(
        role_name="executive",
        metadata={"execution_profile": BOUNDED_TEST_PROFILE},
    )

    result = await agent.send_message(session.session_id, message="Bounded task")

    assert result.generation is not None
    assert result.telemetry_diagnostic == "telemetry_adapter_correlated"
    assert (await agent.health())["last_error"] is None
    await agent.stop_session(session.session_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stages",
    [
        (
            "payload_callback_observed",
            "payload_callback_observed",
            "message_receipt_invalid",
        ),
        ("payload_callback_passed", "provider_response_2xx"),
        (
            "payload_callback_observed",
            "payload_callback_passed",
            "generation_header_valid",
            "message_receipt_valid",
        ),
        (
            "payload_callback_observed",
            "payload_callback_passed",
            "provider_response_2xx",
            "generation_header_valid",
            "message_receipt_valid",
            "message_receipt_invalid",
        ),
        (
            "payload_callback_observed",
            "payload_policy_rejected",
            "message_receipt_valid",
        ),
        (
            "payload_callback_observed",
            "payload_callback_passed",
            "provider_response_unobserved",
            "generation_header_missing",
            "message_receipt_invalid",
        ),
        (
            "payload_callback_observed",
            "payload_callback_passed",
            "provider_http_400",
            "generation_header_missing",
            "message_receipt_valid",
        ),
        (
            "payload_callback_observed",
            "payload_callback_passed",
            "provider_response_2xx",
            "generation_header_missing",
            "message_receipt_valid",
        ),
    ],
    ids=[
        "duplicate",
        "missing-observed",
        "out-of-order",
        "extra",
        "policy-valid-receipt",
        "unobserved-missing-header",
        "http-error-valid-receipt",
        "missing-header-valid-receipt",
    ],
)
async def test_bounded_prime_marks_duplicate_or_out_of_order_stages_invalid(stages):
    transport = FakePrimeSubprocessTransport(
        telemetry_stages=[stages],
        header_generation_ids=[()],
        stream_receipts=[()],
    )
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
        turn_timeout_seconds=1,
    )
    session = await agent.start_session(
        role_name="executive",
        metadata={"execution_profile": BOUNDED_TEST_PROFILE},
    )

    result = await agent.send_message(session.session_id, message="Bounded task")

    assert result.telemetry_diagnostic == "telemetry_diagnostic_invalid"
    assert (await agent.health())["last_error"] == "telemetry_diagnostic_invalid"
    await agent.stop_session(session.session_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stages",
    [
        (
            "payload_callback_observed",
            "payload_callback_passed",
            "provider_response_2xx",
            "generation_header_missing",
            "message_receipt_invalid",
        ),
        (
            "payload_callback_observed",
            "payload_callback_passed",
            "provider_response_2xx",
            "generation_header_valid",
            "message_receipt_invalid",
        ),
    ],
    ids=["header-frame-contradiction", "stream-frame-contradiction"],
)
async def test_bounded_prime_marks_impossible_cross_channel_pair_invalid(stages):
    generation_id = "gen-stage-contradiction"
    transport = FakePrimeSubprocessTransport(
        ["Safe result"],
        header_generation_ids=[(generation_id,)],
        stream_receipts=[(stream_receipt(generation_id),)],
        telemetry_stages=[stages],
    )
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
        turn_timeout_seconds=1,
    )
    session = await agent.start_session(
        role_name="executive",
        metadata={"execution_profile": BOUNDED_TEST_PROFILE},
    )

    result = await agent.send_message(session.session_id, message="Bounded task")

    assert result.generation is not None
    assert result.telemetry_diagnostic == "telemetry_diagnostic_invalid"
    assert (await agent.health())["last_error"] == "telemetry_diagnostic_invalid"
    await agent.stop_session(session.session_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "poisoned_frame",
    [
        telemetry_stage(["API_SECRET=SYNTHETIC_STAGE_LIST_SECRET"]),
        telemetry_stage({"token": "SYNTHETIC_STAGE_OBJECT_SECRET"}),
        {
            **telemetry_stage("provider_http_400"),
            "private_reasoning": "SYNTHETIC_STAGE_EXTRA_SECRET",
        },
        telemetry_stage("provider_http_400:SYNTHETIC_STAGE_TEXT_SECRET"),
    ],
    ids=["list", "object", "extra-key", "unknown-text"],
)
async def test_bounded_prime_never_reflects_poisoned_stage_frame(poisoned_frame):
    generation_id = "gen-stage-poisoned"
    transport = FakePrimeSubprocessTransport(
        ["Safe result"],
        header_generation_ids=[(generation_id,)],
        stream_receipts=[(stream_receipt(generation_id),)],
        telemetry_stages=[
            (
                "payload_callback_observed",
                "payload_callback_passed",
                "provider_response_2xx",
                "generation_header_valid",
                "message_receipt_valid",
            )
        ],
        extra_status_frames=[poisoned_frame],
    )
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
        turn_timeout_seconds=1,
    )
    session = await agent.start_session(
        role_name="executive",
        metadata={"execution_profile": BOUNDED_TEST_PROFILE},
    )

    result = await agent.send_message(session.session_id, message="Bounded task")
    health = await agent.health()
    public = json.dumps(result.to_dict()) + repr(result) + json.dumps(health)

    assert result.generation is not None
    assert result.telemetry_diagnostic == "telemetry_diagnostic_invalid"
    assert health["last_error"] == "telemetry_diagnostic_invalid"
    assert "SYNTHETIC_STAGE" not in public
    assert "API_SECRET" not in public
    await agent.stop_session(session.session_id)


@pytest.mark.asyncio
async def test_bounded_prime_resets_telemetry_stage_state_between_turns():
    generation_id = "gen-stage-second-turn"
    transport = FakePrimeSubprocessTransport(
        ["First safe result", "Second safe result"],
        header_generation_ids=[(), (generation_id,)],
        stream_receipts=[(), (stream_receipt(generation_id),)],
        telemetry_stages=[
            (
                "payload_callback_observed",
                "payload_callback_passed",
                "provider_http_400",
                "generation_header_unobserved",
                "message_receipt_invalid",
            ),
            (
                "payload_callback_observed",
                "payload_callback_passed",
                "provider_response_2xx",
                "generation_header_valid",
                "message_receipt_valid",
            ),
        ],
    )
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
        turn_timeout_seconds=1,
    )
    session = await agent.start_session(
        role_name="executive",
        metadata={"execution_profile": BOUNDED_TEST_PROFILE},
    )

    first = await agent.send_message(session.session_id, message="First task")
    second = await agent.send_message(session.session_id, message="Second task")

    assert first.telemetry_diagnostic == "telemetry_provider_http_400"
    assert second.telemetry_diagnostic == "telemetry_adapter_correlated"
    assert second.generation is not None
    assert (await agent.health())["last_error"] is None
    await agent.stop_session(session.session_id)


@pytest.mark.parametrize(
    "diagnostic",
    [
        "API_SECRET=SYNTHETIC_DIAGNOSTIC_SECRET",
        ["telemetry_adapter_correlated"],
        {"diagnostic": "telemetry_adapter_correlated"},
    ],
)
def test_prime_message_result_rejects_non_enum_diagnostic(diagnostic):
    with pytest.raises(ValueError, match="diagnostic is unavailable"):
        PrimeMessageResult(
            message_id="message-safe",
            session_id="session-safe",
            text="Safe result",
            telemetry_diagnostic=diagnostic,
        )


@pytest.mark.asyncio
async def test_bounded_prime_requires_one_authoritative_header_generation_id():
    transport = FakePrimeSubprocessTransport(
        ["Safe body-only result"],
        generation_ids=["gen-body-is-not-authoritative"],
        stream_receipts=[
            (stream_receipt("gen-body-is-not-authoritative"),),
        ],
    )
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
        turn_timeout_seconds=1,
    )
    session = await agent.start_session(
        role_name="executive",
        metadata={"execution_profile": BOUNDED_TEST_PROFILE},
    )

    result = await agent.send_message(session.session_id, message="Bounded task")

    assert result.generation is None
    assert agent._last_error == "telemetry_payload_callback_unobserved"
    assert "gen-body-is-not-authoritative" not in json.dumps(result.to_dict())
    await agent.stop_session(session.session_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "header_ids",
    [
        ("gen-header-one", "gen-header-two"),
        ("gen-header-duplicate", "gen-header-duplicate"),
    ],
)
async def test_bounded_prime_rejects_multiple_header_receipt_events(header_ids):
    transport = FakePrimeSubprocessTransport(
        ["Safe result with ambiguous receipt"],
        generation_ids=["gen-untrusted-body"],
        header_generation_ids=[header_ids],
    )
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
        turn_timeout_seconds=1,
    )
    session = await agent.start_session(
        role_name="executive",
        metadata={"execution_profile": BOUNDED_TEST_PROFILE},
    )

    result = await agent.send_message(session.session_id, message="Bounded task")

    assert result.generation is None
    assert not any(
        generation_id in json.dumps(result.to_dict()) for generation_id in header_ids
    )
    await agent.stop_session(session.session_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_header_id",
    [
        "gen-.bad",
        "gen-:bad",
        "gen-bad/value",
        f"gen-{'a' * 125}",
    ],
)
async def test_bounded_prime_rejects_invalid_header_generation_id(
    invalid_header_id,
):
    transport = FakePrimeSubprocessTransport(
        ["Safe result with invalid receipt"],
        generation_ids=["gen-untrusted-body"],
        header_generation_ids=[(invalid_header_id,)],
    )
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
        turn_timeout_seconds=1,
    )
    session = await agent.start_session(
        role_name="executive",
        metadata={"execution_profile": BOUNDED_TEST_PROFILE},
    )

    result = await agent.send_message(session.session_id, message="Bounded task")

    assert result.generation is None
    assert invalid_header_id not in json.dumps(result.to_dict())
    await agent.stop_session(session.session_id)


@pytest.mark.asyncio
async def test_bounded_prime_ignores_unrelated_status_events():
    transport = FakePrimeSubprocessTransport(
        ["Safe result"],
        generation_ids=["gen-untrusted-body"],
        header_generation_ids=[("gen-authoritative-header",)],
        extra_status_frames=[
            {
                "type": "extension_ui_request",
                "id": "spoof-wrong-key",
                "method": "setStatus",
                "statusKey": "unrelated.status",
                "statusText": "gen-spoof-one",
            },
            {
                "type": "extension_ui_request",
                "id": "normal-status-event",
                "method": "setStatus",
                "statusKey": "prime.normal-status",
                "statusText": "working",
            },
        ],
    )
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
        turn_timeout_seconds=1,
    )
    session = await agent.start_session(
        role_name="executive",
        metadata={"execution_profile": BOUNDED_TEST_PROFILE},
    )

    result = await agent.send_message(session.session_id, message="Bounded task")
    serialized = json.dumps(result.to_dict())

    assert result.generation is not None
    assert "gen-spoof" not in serialized
    assert "SYNTHETIC_STATUS" not in serialized
    assert "gen-untrusted-body" not in serialized
    await agent.stop_session(session.session_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "poison_frame",
    [
        {
            "type": "extension_ui_request",
            "id": "bad-header-method",
            "method": "notify",
            "statusKey": "orch71.openrouter-generation.v1",
            "statusText": "gen-spoof-one",
        },
        {
            "type": "extension_ui_request",
            "id": "bad-header-extra",
            "method": "setStatus",
            "statusKey": "orch71.openrouter-generation.v1",
            "statusText": "gen-spoof-two",
            "authorization": "Bearer SYNTHETIC_STATUS_SECRET",
        },
        {
            "type": "extension_ui_request",
            "id": "bad-stream-method",
            "method": "notify",
            "statusKey": "orch71.openrouter-stream-receipt.v1",
            "statusText": "{}",
        },
        {
            "type": "extension_ui_request",
            "id": "bad-stream-extra",
            "method": "setStatus",
            "statusKey": "orch71.openrouter-stream-receipt.v1",
            "statusText": "{}",
            "private_reasoning": "SYNTHETIC_PRIVATE_STATUS_REASONING",
        },
        {
            "type": "extension_ui_request",
            "id": "bad-stream-missing-text",
            "method": "setStatus",
            "statusKey": "orch71.openrouter-stream-receipt.v1",
        },
    ],
)
async def test_bounded_prime_poisoned_same_key_status_fails_closed(poison_frame):
    transport = FakePrimeSubprocessTransport(
        ["Safe result"],
        header_generation_ids=[("gen-authoritative-header",)],
        extra_status_frames=[poison_frame],
    )
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
        turn_timeout_seconds=1,
    )
    session = await agent.start_session(
        role_name="executive",
        metadata={"execution_profile": BOUNDED_TEST_PROFILE},
    )

    result = await agent.send_message(session.session_id, message="Bounded task")

    assert result.generation is None
    assert agent._last_error == "telemetry_payload_callback_unobserved"
    assert "SYNTHETIC" not in json.dumps(result.to_dict())
    await agent.stop_session(session.session_id)


def invalid_stream_receipt(case: str) -> dict | str:
    receipt = stream_receipt("gen-authoritative-header")
    if case == "missing_cost":
        receipt.pop("actual_cost_usd")
    elif case == "negative_cost":
        receipt["actual_cost_usd"] = -0.1
    elif case == "string_cost":
        receipt["actual_cost_usd"] = "0.1"
    elif case == "oversized_cost":
        receipt["actual_cost_usd"] = 1000.01
    elif case == "nonfinite_cost":
        receipt["actual_cost_usd"] = float("nan")
    elif case == "null_cost":
        receipt["actual_cost_usd"] = None
    elif case == "boolean_tokens":
        receipt["input_tokens"] = True
    elif case == "negative_tokens":
        receipt["output_tokens"] = -1
    elif case == "inconsistent_tokens":
        receipt["total_tokens"] = 31
    elif case == "invalid_model":
        receipt["selected_model"] = "model with spaces"
    elif case == "invalid_id":
        receipt["generation_id"] = "gen-bad/value"
    elif case == "wrong_source":
        receipt["source"] = "openrouter_generation"
    elif case == "extra_secret_key":
        receipt["API_SECRET"] = "SYNTHETIC_INNER_SECRET"
    elif case == "duplicate_key":
        encoded = json.dumps(receipt, separators=(",", ":"))
        return encoded[:-1] + ',"actual_cost_usd":0.2}'
    elif case == "malformed_json":
        return '{"contract":"orch.openrouter.stream-receipt"'
    else:
        raise AssertionError(f"unknown invalid receipt case: {case}")
    return receipt


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "missing_cost",
        "negative_cost",
        "string_cost",
        "oversized_cost",
        "nonfinite_cost",
        "null_cost",
        "boolean_tokens",
        "negative_tokens",
        "inconsistent_tokens",
        "invalid_model",
        "invalid_id",
        "wrong_source",
        "extra_secret_key",
        "duplicate_key",
        "malformed_json",
    ],
)
async def test_bounded_prime_rejects_invalid_stream_receipt(case):
    transport = FakePrimeSubprocessTransport(
        ["Safe result"],
        header_generation_ids=[("gen-authoritative-header",)],
        stream_receipts=[(invalid_stream_receipt(case),)],
    )
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
        turn_timeout_seconds=1,
    )
    session = await agent.start_session(
        role_name="executive",
        metadata={"execution_profile": BOUNDED_TEST_PROFILE},
    )

    result = await agent.send_message(session.session_id, message="Bounded task")

    assert result.generation is None
    assert agent._last_error == "telemetry_payload_callback_unobserved"
    assert "SYNTHETIC" not in json.dumps(result.to_dict())
    await agent.stop_session(session.session_id)


@pytest.mark.asyncio
async def test_bounded_prime_accepts_zero_owner_cost_but_not_missing_receipt():
    transport = FakePrimeSubprocessTransport(
        ["Free result", "Missing receipt result"],
        header_generation_ids=[("gen-zero-cost",), ("gen-missing-receipt",)],
        stream_receipts=[
            (stream_receipt("gen-zero-cost", actual_cost_usd=0),),
            (),
        ],
    )
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
        turn_timeout_seconds=1,
    )
    session = await agent.start_session(
        role_name="executive",
        metadata={"execution_profile": BOUNDED_TEST_PROFILE},
    )

    free = await agent.send_message(session.session_id, message="Free task")
    missing = await agent.send_message(session.session_id, message="Missing task")

    assert free.generation is not None
    assert free.generation.actual_cost_usd == 0
    assert missing.generation is None
    assert agent._last_error == "telemetry_payload_callback_unobserved"
    await agent.stop_session(session.session_id)


@pytest.mark.asyncio
async def test_bounded_prime_rejects_duplicate_stream_receipts():
    receipt = stream_receipt("gen-duplicate-receipt")
    transport = FakePrimeSubprocessTransport(
        ["Ambiguous result"],
        header_generation_ids=[("gen-duplicate-receipt",)],
        stream_receipts=[(receipt, receipt)],
    )
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
        turn_timeout_seconds=1,
    )
    session = await agent.start_session(
        role_name="executive",
        metadata={"execution_profile": BOUNDED_TEST_PROFILE},
    )

    result = await agent.send_message(session.session_id, message="Bounded task")

    assert result.generation is None
    await agent.stop_session(session.session_id)


@pytest.mark.asyncio
async def test_bounded_prime_rejects_mismatched_stream_receipt():
    transport = FakePrimeSubprocessTransport(
        ["Safe result"],
        generation_ids=["gen-untrusted-body"],
        header_generation_ids=[("gen-authoritative-request",)],
        stream_receipts=[(stream_receipt("gen-different-response"),)],
    )
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
        turn_timeout_seconds=1,
    )
    session = await agent.start_session(
        role_name="executive",
        metadata={"execution_profile": BOUNDED_TEST_PROFILE},
    )

    result = await agent.send_message(session.session_id, message="Bounded task")

    assert result.generation is None
    assert agent._last_error == "telemetry_payload_callback_unobserved"
    assert "gen-different-response" not in json.dumps(result.to_dict())
    await agent.stop_session(session.session_id)


@pytest.mark.asyncio
async def test_bounded_prime_correlates_one_header_to_each_agent_end():
    transport = FakePrimeSubprocessTransport(
        ["First safe result", "Second safe result"],
        generation_ids=["gen-body-one", "gen-body-two"],
        header_generation_ids=[("gen-header-one",), ("gen-header-two",)],
    )
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
        turn_timeout_seconds=1,
    )
    session = await agent.start_session(
        role_name="executive",
        metadata={"execution_profile": BOUNDED_TEST_PROFILE},
    )

    first = await agent.send_message(session.session_id, message="First task")
    second = await agent.send_message(session.session_id, message="Second task")

    assert first.generation is not None
    assert first.generation.generation_id == "gen-header-one"
    assert second.generation is not None
    assert second.generation.generation_id == "gen-header-two"
    await agent.stop_session(session.session_id)


@pytest.mark.asyncio
async def test_bounded_prime_does_not_reuse_prior_header_on_next_turn():
    transport = FakePrimeSubprocessTransport(
        ["First safe result", "Second safe result"],
        generation_ids=["gen-body-one", "gen-body-two"],
        header_generation_ids=[("gen-header-one",), ()],
    )
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
        turn_timeout_seconds=1,
    )
    session = await agent.start_session(
        role_name="executive",
        metadata={"execution_profile": BOUNDED_TEST_PROFILE},
    )

    first = await agent.send_message(session.session_id, message="First task")
    second = await agent.send_message(session.session_id, message="Second task")

    assert first.generation is not None
    assert first.generation.generation_id == "gen-header-one"
    assert second.generation is None
    assert agent._last_error == "telemetry_payload_callback_unobserved"
    await agent.stop_session(session.session_id)


@pytest.mark.asyncio
async def test_standard_prime_ignores_header_status_channel_and_keeps_body_id():
    transport = FakePrimeSubprocessTransport(
        ["Standard result"],
        generation_ids=["gen-standard-body"],
        extra_status_frames=[
            {
                "type": "extension_ui_request",
                "id": "standard-spoof",
                "method": "setStatus",
                "statusKey": "orch71.openrouter-generation.v1",
                "statusText": "gen-standard-spoof",
            }
        ],
    )
    client = PrimeRpcClient(transport, turn_timeout_seconds=1)
    await client.start(argv=("prime-agent",), env={}, cwd=None)

    text, generation_id = await client.prompt_and_wait("Standard task")

    assert text == "Standard result"
    assert generation_id == "gen-standard-body"
    await client.close()


@pytest.mark.asyncio
async def test_bounded_prime_rejects_utf8_workdir_over_request_budget():
    transport = FakePrimeSubprocessTransport()
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
    )
    agent.cwd = "C:\\" + ("é" * 127)
    assert len(agent.cwd.encode("utf-8")) == 257

    with pytest.raises(PrimeRuntimeError, match="workdir exceeds"):
        await agent.start_session(
            role_name="executive",
            metadata={"execution_profile": BOUNDED_TEST_PROFILE},
        )

    assert transport.argv == ()
    assert await agent.list_sessions() == []


@pytest.mark.asyncio
async def test_standard_prime_ignores_compaction_event_for_compatibility():
    transport = FakePrimeSubprocessTransport(
        ["Standard turn remains available."],
        emit_compaction=True,
    )
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
    )
    session = await agent.start_session(role_name="executive")

    result = await agent.send_message(session.session_id, message="Standard task")

    assert result.text == "Standard turn remains available."
    assert result.telemetry_diagnostic is None
    assert "SYNTHETIC_PRIVATE_COMPACTION_SUMMARY" not in json.dumps(result.to_dict())
    await agent.stop_session(session.session_id)


@pytest.mark.asyncio
async def test_bounded_prime_fails_closed_on_unexpected_compaction_event():
    transport = FakePrimeSubprocessTransport(
        ["Bounded result must not be accepted."],
        generation_ids=["gen-compacted"],
        emit_compaction=True,
    )
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
    )
    session = await agent.start_session(
        role_name="executive",
        metadata={"execution_profile": BOUNDED_TEST_PROFILE},
    )

    with pytest.raises(PrimeRuntimeError, match="compaction"):
        await agent.send_message(session.session_id, message="Bounded task")

    await agent.stop_session(session.session_id)
    assert await agent.list_sessions() == []


@pytest.mark.asyncio
async def test_cancelled_bounded_start_closes_transport_and_private_config():
    class BlockingStateTransport(FakePrimeSubprocessTransport):
        def __init__(self):
            super().__init__()
            self.state_seen = asyncio.Event()

        async def write_line(self, line: bytes) -> None:
            command = json.loads(line)
            if command["type"] == "get_state":
                self.commands.append(command)
                self.state_seen.set()
                await asyncio.Event().wait()
            await super().write_line(line)

    transport = BlockingStateTransport()
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
        cleanup_timeout_seconds=0.2,
    )
    task = asyncio.create_task(
        agent.start_session(
            role_name="executive",
            metadata={"execution_profile": BOUNDED_TEST_PROFILE},
        )
    )
    await asyncio.wait_for(transport.state_seen.wait(), timeout=0.2)
    runtime_dir = transport.runtime_config_dir
    assert runtime_dir is not None and runtime_dir.exists()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert transport.closed is True
    assert runtime_dir.exists() is False
    assert await agent.list_sessions() == []


@pytest.mark.asyncio
async def test_cancelled_bounded_send_leaves_no_live_session():
    class HangingTurnTransport(FakePrimeSubprocessTransport):
        async def _complete_turn(self, text: str) -> None:
            del text
            await asyncio.Event().wait()

    transport = HangingTurnTransport(generation_ids=["gen-never-completes"])
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
        cleanup_timeout_seconds=0.2,
    )
    session = await agent.start_session(
        role_name="executive",
        metadata={"execution_profile": BOUNDED_TEST_PROFILE},
    )
    runtime_dir = transport.runtime_config_dir
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            agent.send_message(session.session_id, message="Bounded task"),
            timeout=0.03,
        )
    assert transport.closed is True
    assert runtime_dir is not None and runtime_dir.exists() is False
    assert await agent.list_sessions() == []


@pytest.mark.asyncio
async def test_cancelled_abort_still_closes_and_removes_session():
    class BlockingAbortTransport(FakePrimeSubprocessTransport):
        def __init__(self):
            super().__init__()
            self.abort_seen = asyncio.Event()

        async def write_line(self, line: bytes) -> None:
            command = json.loads(line)
            if command["type"] == "abort":
                self.commands.append(command)
                self.abort_seen.set()
                await asyncio.Event().wait()
            await super().write_line(line)

    transport = BlockingAbortTransport()
    agent = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: transport,
        cleanup_timeout_seconds=0.2,
    )
    session = await agent.start_session(
        role_name="executive",
        metadata={"execution_profile": BOUNDED_TEST_PROFILE},
    )
    runtime_dir = transport.runtime_config_dir
    stop_task = asyncio.create_task(agent.stop_session(session.session_id))
    await asyncio.wait_for(transport.abort_seen.wait(), timeout=0.2)
    stop_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stop_task
    assert transport.closed is True
    assert runtime_dir is not None and runtime_dir.exists() is False
    assert await agent.list_sessions() == []


def test_public_output_withholds_explicit_private_reasoning():
    text, filtered = sanitize_public_text(
        "Private reasoning: SYNTHETIC_INTERNAL_ANALYSIS"
    )
    assert text == "Executive response withheld by safety policy"
    assert filtered is True
    assert "SYNTHETIC_INTERNAL_ANALYSIS" not in text


@pytest.mark.asyncio
async def test_empty_explicit_environment_does_not_fall_back_to_service_environment(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "SYNTHETIC_PARENT_PROCESS_SECRET")
    monkeypatch.setenv("API_SECRET", "SYNTHETIC_PARENT_API_SECRET")
    transport = FakePrimeSubprocessTransport()
    agent = PrimeJsonlRpcAgent(environment={}, transport_factory=lambda: transport)
    assert build_prime_environment({}) == {}
    health = await agent.health()
    assert health["credentials_configured"] is False
    with pytest.raises(PrimeUnavailableError):
        await agent.start_session(
            role_name="executive", model=OPENROUTER_AUTOROUTER_MODEL
        )
    assert transport.argv == ()
    assert transport.env == {}
    assert isinstance(build_prime_agent_from_environment({}), NullPrimeAgent)
    assert isinstance(
        build_prime_agent_from_environment(
            {
                "PRIME_AGENT_ENABLED": "true",
                "OPENROUTER_API_KEY": "SYNTHETIC_GATE_SECRET",
            }
        ),
        NullPrimeAgent,
    )
    isolated = tmp_path / "prime-isolated"
    isolated.mkdir()
    live = build_prime_agent_from_environment(
        {
            "PRIME_AGENT_ENABLED": "true",
            "PRIME_AGENT_WORKDIR": str(isolated),
            "PRIME_AGENT_BIN": "prime-agent",
            "OPENROUTER_API_KEY": "SYNTHETIC_GATE_SECRET",
            "API_SECRET": "SYNTHETIC_UNRELATED_SECRET",
        }
    )
    assert isinstance(live, PrimeJsonlRpcAgent)
    assert live.cwd == str(isolated.resolve())
    assert "PRIME_AGENT_ENABLED" not in live._env
    assert "PRIME_AGENT_WORKDIR" not in live._env
    assert "PRIME_AGENT_BIN" not in live._env
    assert "API_SECRET" not in live._env
    assert live._env["HOME"] == str(isolated.resolve())
    assert live._env["USERPROFILE"] == str(isolated.resolve())

    production_cwd = Path.cwd().resolve()
    for overlapping in (production_cwd, production_cwd / "app", production_cwd.parent):
        disabled = build_prime_agent_from_environment(
            {
                "PRIME_AGENT_ENABLED": "true",
                "PRIME_AGENT_WORKDIR": str(overlapping),
                "OPENROUTER_API_KEY": "SYNTHETIC_GATE_SECRET",
            }
        )
        assert isinstance(disabled, NullPrimeAgent)


def test_delegation_parser_is_strict_bounded_and_redacts_tasks():
    plain = parse_executive_reply("Normal public update")
    assert plain.reply == "Normal public update"
    assert plain.delegations == ()

    raw = json.dumps(
        {
            "reply": "I will consult one specialist.",
            "delegations": [
                {
                    "role": "analyst",
                    "task": "Check risk API_KEY=SYNTHETIC_TASK_SECRET",
                }
            ],
        },
        separators=(",", ":"),
    )
    assert len(raw) <= MAX_PLAN_CHARS
    parsed = parse_executive_reply(raw)
    assert len(parsed.delegations) == 1
    assert parsed.delegations[0].role == "analyst"
    assert parsed.delegations[0].task == "Check risk [redacted]"
    assert "SYNTHETIC" not in repr(parsed.delegations[0])

    for rejected in (
        '[{"role":"analyst","task":"INTERNAL_ARRAY_TASK"}]',
        '```json\n{"reply":"x","delegations":[]}\n```',
        '{"reply":"one","reply":"two","delegations":[]}',
        '{"reply":null,"delegations":[{"role":"analyst","task":"x"}]}',
        '{"reply":"safe","delegations":[],"extra":"INTERNAL_EXTRA"}',
        "{" + "x" * MAX_PLAN_CHARS + "}",
    ):
        result = parse_executive_reply(rejected)
        assert result.delegations == ()
        assert result.plan_rejected is True
        assert "INTERNAL_" not in result.reply


def test_prime_adapter_rejects_any_tools_opt_in():
    with pytest.raises(PrimeRuntimeError, match="tools are disabled"):
        PrimeJsonlRpcAgent(environment={}, allow_tools=True)
    with pytest.raises(PrimeRuntimeError, match="requires an isolated workdir"):
        PrimeJsonlRpcAgent(environment={})
    with pytest.raises(PrimeRuntimeError, match="isolated workdir is invalid"):
        PrimeJsonlRpcAgent(
            cwd=str(Path.cwd()),
            environment={},
            transport_factory=FakePrimeSubprocessTransport,
        )


@pytest.mark.asyncio
async def test_prime_adapter_allows_only_children_of_a_live_local_root(tmp_path):
    root_transport = FakePrimeSubprocessTransport(name="root")
    child_transport = FakePrimeSubprocessTransport(name="reviewer")
    pending = [root_transport, child_transport]
    isolated = tmp_path / "prime-home"
    isolated.mkdir()
    agent = PrimeJsonlRpcAgent(
        cwd=str(isolated.resolve()),
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: pending.pop(0),
    )
    root = await agent.start_session(role_name="executive", model="hostile/model")
    child = await agent.start_session(
        role_name="reviewer",
        parent_session_id=root.session_id,
        model="hostile/model",
        metadata={"task": "INTERNAL_METADATA_TASK", "sessionFile": "PRIVATE_FILE"},
    )

    assert child.parent_session_id == root.session_id
    assert child.model == OPENROUTER_AUTOROUTER_MODEL
    assert child.metadata["tools_enabled"] is False
    assert child.metadata["context"] == {}
    assert "INTERNAL_METADATA_TASK" not in json.dumps(child.to_dict())
    assert child_transport.argv[-2:] == ("--no-session", "--no-tools")
    with pytest.raises(PrimeRuntimeError, match="not allowed"):
        await agent.start_session(
            role_name="untrusted-role", parent_session_id=root.session_id
        )
    with pytest.raises(PrimeRuntimeError, match="parent is unavailable"):
        await agent.start_session(
            role_name="analyst", parent_session_id="missing-parent"
        )
    with pytest.raises(PrimeRuntimeError, match="cannot have a parent"):
        await agent.start_session(
            role_name="executive", parent_session_id=root.session_id
        )

    await agent.stop_session(child.session_id)
    await agent.stop_session(root.session_id)
    assert await agent.list_sessions() == []


@pytest.mark.asyncio
async def test_runtime_serializes_turns_and_projects_orch70_v1_publish_requests():
    transport = FakePrimeSubprocessTransport(
        ["First safe update", "Second safe update"]
    )
    prime = PrimeJsonlRpcAgent(
        environment={
            "PATH": "C:/runtime/bin",
            "OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET",
            "API_SECRET": "SYNTHETIC_SERVICE_SECRET",
        },
        transport_factory=lambda: transport,
        turn_timeout_seconds=1,
    )
    registry = ExecutiveSessionRegistry(handoff_store=InMemoryHandoffStore())
    runtime = ExecutiveRuntime(
        registry=registry,
        prime=prime,
        router=HeuristicModelRouter(),
    )
    health = await runtime.adapter_health()
    assert health["live_prime_rpc"] is True
    assert health["live_llm"] is True
    assert "SYNTHETIC" not in json.dumps(health)
    session = await runtime.open_mission(mission_id="m-chat", brief="Safe chat demo")
    first, second = await asyncio.gather(
        runtime.send_message(session.session_id, message="First"),
        runtime.send_message(session.session_id, message="Second"),
    )
    assert transport.concurrent_prompt is False
    assert {first["message"]["text"], second["message"]["text"]} == {
        "First safe update",
        "Second safe update",
    }

    for turn in (first, second):
        assert turn["contract"] == "orch.executive.chat"
        batch = turn["event_batch"]
        assert batch["target_contract"] == "orch.control-plane.event"
        assert batch["target_contract_version"] == "1.0"
        assert [event["type"] for event in batch["events"]] == [
            "executive_message",
            "evidence",
            "confidence",
        ]
        assert set(batch["events"][0]["data"]) == {
            "summary",
            "severity",
            "action_required",
        }
        assert set(batch["events"][1]["data"]) == {
            "evidence_id",
            "kind",
            "reference_id",
            "label",
            "verification_status",
        }
        assert batch["events"][2]["data"]["score"] == 0
        assert "SYNTHETIC" not in json.dumps(turn)

    await runtime.close()
    assert transport.closed is True
    assert await prime.list_sessions() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("delegation_count", [1, 2])
async def test_runtime_runs_host_controlled_delegations_sequentially(
    delegation_count,
    tmp_path,
):
    lifecycle: list[str] = []
    requests = [
        {
            "role": "analyst",
            "task": (
                "Assess launch risk INTERNAL_TASK_ALPHA API_KEY=SYNTHETIC_TASK_SECRET"
            ),
        },
        {"role": "reviewer", "task": "Challenge evidence INTERNAL_TASK_BETA"},
    ][:delegation_count]
    plan = json.dumps(
        {"reply": "I am consulting bounded specialists.", "delegations": requests},
        separators=(",", ":"),
    )
    root = FakePrimeSubprocessTransport(
        [plan, "Final public synthesis"], name="root", lifecycle=lifecycle
    )
    reports = [
        "Analyst report: launch risk is bounded.",
        "Reviewer report: Authorization: Bearer SYNTHETIC_REPORT_TOKEN_123456",
    ]
    children = [
        FakePrimeSubprocessTransport(
            [reports[index]],
            name=request["role"],
            lifecycle=lifecycle,
        )
        for index, request in enumerate(requests)
    ]
    transports = [root, *children]
    pending = list(transports)

    def transport_factory():
        return pending.pop(0)

    isolated = tmp_path / "prime-home"
    isolated.mkdir()
    prime = PrimeJsonlRpcAgent(
        cwd=str(isolated.resolve()),
        environment={
            "HOME": "C:/real/service/home",
            "USERPROFILE": "C:/real/service/profile",
            "OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET",
        },
        transport_factory=transport_factory,
        turn_timeout_seconds=1,
    )
    runtime = ExecutiveRuntime(
        registry=ExecutiveSessionRegistry(handoff_store=InMemoryHandoffStore()),
        prime=prime,
        router=HeuristicModelRouter(),
    )
    session = await runtime.open_mission(mission_id="m-delegate", brief="Safe demo")
    turn = await runtime.send_message(session.session_id, message="Advise me")

    expected_lifecycle = ["start:root", "prompt:root:1"]
    for request in requests:
        role = request["role"]
        expected_lifecycle.extend(
            [f"start:{role}", f"prompt:{role}:1", f"close:{role}"]
        )
    expected_lifecycle.append("prompt:root:2")
    assert lifecycle == expected_lifecycle
    assert pending == []
    assert turn["message"]["text"] == "Final public synthesis"
    assert turn["delegations"] == [
        {"role": request["role"], "status": "completed"} for request in requests
    ]
    assert set().union(*(summary.keys() for summary in turn["delegations"])) == {
        "role",
        "status",
    }
    serialized = json.dumps(turn)
    assert "INTERNAL_TASK" not in serialized
    assert "SYNTHETIC_REPORT_TOKEN" not in serialized
    assert "SYNTHETIC_TASK_SECRET" not in serialized
    assert "PRIVATE_VENDOR_SESSION_ID" not in serialized
    assert "browser-session" not in serialized
    assert "SYNTHETIC_PRIVATE_REASONING" not in serialized
    assert "SYNTHETIC_TOOL_SECRET" not in serialized

    root_prompts = [
        command["message"] for command in root.commands if command["type"] == "prompt"
    ]
    assert len(root_prompts) == 2
    assert "CEO message:\nAdvise me" in root_prompts[0]
    assert '"delegations"' in root_prompts[0]
    assert "Analyst report" in root_prompts[1]
    assert "INTERNAL_TASK" not in root_prompts[1]
    for index, child in enumerate(children):
        child_prompt = next(
            command["message"]
            for command in child.commands
            if command["type"] == "prompt"
        )
        expected_task = requests[index]["task"].replace(
            "API_KEY=SYNTHETIC_TASK_SECRET", "[redacted]"
        )
        assert child_prompt == expected_task
        assert child.argv[-2:] == ("--no-session", "--no-tools")
        assert child.env["HOME"] == str(isolated.resolve())
        assert child.env["USERPROFILE"] == str(isolated.resolve())
        assert child.closed is True
    assert all(
        transport.argv[transport.argv.index("--model") + 1]
        == OPENROUTER_AUTOROUTER_MODEL
        for transport in transports
    )

    final_event = turn["event_batch"]["events"][0]
    assert final_event["data"]["summary"] == "Final public synthesis"
    final_message_id = turn["message"]["message_id"]
    assert turn["event_batch"]["events"][1]["data"]["evidence_id"] == final_message_id
    team = turn["snapshot"]["specialists"]
    assert len(team) == delegation_count + 1
    assert team[0]["role_name"] == "executive"
    assert [item["role_name"] for item in team[1:]] == [
        request["role"] for request in requests
    ]
    assert all(item["status"] == "completed" for item in team[1:])
    assert all(
        item["parent_instance_id"] == team[0]["instance_id"] for item in team[1:]
    )
    assert "INTERNAL_TASK" not in json.dumps(team)

    live_sessions = await prime.list_sessions()
    assert len(live_sessions) == 1
    assert live_sessions[0].role_name == "executive"
    await runtime.close()
    assert root.closed is True
    assert await prime.list_sessions() == []


@pytest.mark.asyncio
async def test_runtime_child_failure_is_closed_and_synthesized_safely(tmp_path):
    lifecycle: list[str] = []
    plan = json.dumps(
        {
            "reply": "A reviewer check is pending.",
            "delegations": [
                {"role": "reviewer", "task": "Inspect INTERNAL_FAILURE_TASK"}
            ],
        },
        separators=(",", ":"),
    )
    root = FakePrimeSubprocessTransport(
        [plan, "Safe final answer despite unavailable review"],
        name="root",
        lifecycle=lifecycle,
    )
    child = FakePrimeSubprocessTransport(
        ["unused"],
        name="reviewer",
        lifecycle=lifecycle,
        fail_prompt_at={1},
    )
    pending = [root, child]
    isolated = tmp_path / "prime-home"
    isolated.mkdir()
    prime = PrimeJsonlRpcAgent(
        cwd=str(isolated.resolve()),
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: pending.pop(0),
        turn_timeout_seconds=1,
    )
    runtime = ExecutiveRuntime(
        registry=ExecutiveSessionRegistry(handoff_store=InMemoryHandoffStore()),
        prime=prime,
        router=HeuristicModelRouter(),
    )
    session = await runtime.open_mission(mission_id="m-child-failure", brief="demo")
    turn = await runtime.send_message(session.session_id, message="Review this")

    assert lifecycle == [
        "start:root",
        "prompt:root:1",
        "start:reviewer",
        "prompt:reviewer:1",
        "close:reviewer",
        "prompt:root:2",
    ]
    assert child.closed is True
    assert turn["delegations"] == [{"role": "reviewer", "status": "failed"}]
    assert turn["message"]["text"] == "Safe final answer despite unavailable review"
    assert turn["snapshot"]["specialists"][1]["status"] == "failed"
    synthesis = [
        command["message"] for command in root.commands if command["type"] == "prompt"
    ][1]
    assert "reviewer: unavailable" in synthesis
    assert "INTERNAL_FAILURE_TASK" not in synthesis
    assert "INTERNAL_FAILURE_TASK" not in json.dumps(turn)
    assert "Prime RPC prompt failed" not in json.dumps(turn)
    await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "plan",
    [
        json.dumps(
            {
                "reply": "Safe fallback for too many requests.",
                "delegations": [
                    {"role": "analyst", "task": "INTERNAL_ONE"},
                    {"role": "reviewer", "task": "INTERNAL_TWO"},
                    {"role": "tester", "task": "INTERNAL_THREE"},
                ],
            },
            separators=(",", ":"),
        ),
        json.dumps(
            {
                "reply": "Safe fallback for an extra field.",
                "delegations": [{"role": "analyst", "task": "INTERNAL_EXTRA_TASK"}],
                "extra": "not allowed",
            },
            separators=(",", ":"),
        ),
    ],
)
async def test_runtime_rejects_nonconforming_plans_without_children(plan):
    root = FakePrimeSubprocessTransport([plan])
    calls = 0

    def transport_factory():
        nonlocal calls
        calls += 1
        assert calls == 1
        return root

    prime = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=transport_factory,
        turn_timeout_seconds=1,
    )
    runtime = ExecutiveRuntime(
        registry=ExecutiveSessionRegistry(handoff_store=InMemoryHandoffStore()),
        prime=prime,
        router=HeuristicModelRouter(),
    )
    session = await runtime.open_mission(mission_id="m-reject-plan", brief="demo")
    turn = await runtime.send_message(session.session_id, message="Advise")

    assert calls == 1
    assert turn["delegations"] == []
    assert len(turn["snapshot"]["specialists"]) == 1
    assert "Safe fallback" in turn["message"]["text"]
    assert "INTERNAL_" not in json.dumps(turn)
    assert len([c for c in root.commands if c["type"] == "prompt"]) == 1
    await runtime.close()


@pytest.mark.asyncio
async def test_runtime_strips_second_round_plan_and_never_starts_grandchildren():
    first_plan = json.dumps(
        {
            "reply": "An analyst check is in progress.",
            "delegations": [{"role": "analyst", "task": "Inspect INTERNAL_FIRST_TASK"}],
        },
        separators=(",", ":"),
    )
    second_plan = json.dumps(
        {
            "reply": "Final safe answer.",
            "delegations": [{"role": "tester", "task": "Run INTERNAL_GRANDCHILD_TASK"}],
        },
        separators=(",", ":"),
    )
    root = FakePrimeSubprocessTransport([first_plan, second_plan], name="root")
    child = FakePrimeSubprocessTransport(["Safe analyst report"], name="analyst")
    pending = [root, child]
    calls = 0

    def transport_factory():
        nonlocal calls
        calls += 1
        assert calls <= 2
        return pending.pop(0)

    prime = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=transport_factory,
        turn_timeout_seconds=1,
    )
    runtime = ExecutiveRuntime(
        registry=ExecutiveSessionRegistry(handoff_store=InMemoryHandoffStore()),
        prime=prime,
        router=HeuristicModelRouter(),
    )
    session = await runtime.open_mission(mission_id="m-no-grandchild", brief="demo")
    turn = await runtime.send_message(session.session_id, message="Advise")

    assert calls == 2
    assert turn["message"]["text"] == "Final safe answer."
    assert turn["message"]["safety_filtered"] is True
    assert turn["delegations"] == [{"role": "analyst", "status": "completed"}]
    assert [item["role_name"] for item in turn["snapshot"]["specialists"]] == [
        "executive",
        "analyst",
    ]
    assert "INTERNAL_FIRST_TASK" not in json.dumps(turn)
    assert "INTERNAL_GRANDCHILD_TASK" not in json.dumps(turn)
    assert turn["event_batch"]["events"][0]["data"]["summary"] == "Final safe answer."
    await runtime.close()


@pytest.mark.asyncio
async def test_runtime_uses_safe_draft_when_root_synthesis_fails():
    plan = json.dumps(
        {
            "reply": "Safe draft remains available.",
            "delegations": [
                {"role": "analyst", "task": "Inspect INTERNAL_SYNTHESIS_TASK"}
            ],
        },
        separators=(",", ":"),
    )
    root = FakePrimeSubprocessTransport([plan], name="root", fail_prompt_at={2})
    child = FakePrimeSubprocessTransport(["Safe report"], name="analyst")
    pending = [root, child]
    prime = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: pending.pop(0),
        turn_timeout_seconds=1,
    )
    runtime = ExecutiveRuntime(
        registry=ExecutiveSessionRegistry(handoff_store=InMemoryHandoffStore()),
        prime=prime,
        router=HeuristicModelRouter(),
    )
    session = await runtime.open_mission(mission_id="m-synthesis-failure", brief="demo")
    turn = await runtime.send_message(session.session_id, message="Advise")

    assert turn["message"]["text"] == "Safe draft remains available."
    assert turn["message"]["safety_filtered"] is True
    assert turn["delegations"] == [{"role": "analyst", "status": "completed"}]
    assert "INTERNAL_SYNTHESIS_TASK" not in json.dumps(turn)
    assert "Prime RPC prompt failed" not in json.dumps(turn)
    assert (
        turn["event_batch"]["events"][0]["data"]["summary"]
        == "Safe draft remains available."
    )
    await runtime.close()


@pytest.mark.asyncio
async def test_runtime_serializes_complete_delegated_turns_without_interleaving():
    lifecycle: list[str] = []
    first_plan = json.dumps(
        {
            "reply": "First draft.",
            "delegations": [
                {"role": "analyst", "task": "Inspect INTERNAL_CONCURRENT_ONE"}
            ],
        },
        separators=(",", ":"),
    )
    second_plan = json.dumps(
        {
            "reply": "Second draft.",
            "delegations": [
                {"role": "reviewer", "task": "Inspect INTERNAL_CONCURRENT_TWO"}
            ],
        },
        separators=(",", ":"),
    )
    root = FakePrimeSubprocessTransport(
        [first_plan, "First final.", second_plan, "Second final."],
        name="root",
        lifecycle=lifecycle,
    )
    analyst = FakePrimeSubprocessTransport(
        ["First report"], name="analyst", lifecycle=lifecycle
    )
    reviewer = FakePrimeSubprocessTransport(
        ["Second report"], name="reviewer", lifecycle=lifecycle
    )
    pending = [root, analyst, reviewer]
    prime = PrimeJsonlRpcAgent(
        environment={"OPENROUTER_API_KEY": "SYNTHETIC_OPENROUTER_SECRET"},
        transport_factory=lambda: pending.pop(0),
        turn_timeout_seconds=1,
    )
    runtime = ExecutiveRuntime(
        registry=ExecutiveSessionRegistry(handoff_store=InMemoryHandoffStore()),
        prime=prime,
        router=HeuristicModelRouter(),
    )
    session = await runtime.open_mission(mission_id="m-atomic-turns", brief="demo")
    first, second = await asyncio.gather(
        runtime.send_message(session.session_id, message="First CEO request"),
        runtime.send_message(session.session_id, message="Second CEO request"),
    )

    assert lifecycle == [
        "start:root",
        "prompt:root:1",
        "start:analyst",
        "prompt:analyst:1",
        "close:analyst",
        "prompt:root:2",
        "prompt:root:3",
        "start:reviewer",
        "prompt:reviewer:1",
        "close:reviewer",
        "prompt:root:4",
    ]
    assert {first["message"]["text"], second["message"]["text"]} == {
        "First final.",
        "Second final.",
    }
    assert "INTERNAL_CONCURRENT" not in json.dumps([first, second])
    await runtime.close()


class FailingPrime:
    name = "failing"

    async def start_session(self, **kwargs):
        del kwargs
        raise PrimeUnavailableError("SYNTHETIC_RAW_PROVIDER_ERROR")


@pytest.mark.asyncio
async def test_open_mission_drops_registry_state_when_prime_start_fails():
    registry = ExecutiveSessionRegistry(handoff_store=InMemoryHandoffStore())
    runtime = ExecutiveRuntime(
        registry=registry,
        prime=FailingPrime(),  # type: ignore[arg-type]
        router=HeuristicModelRouter(),
    )
    with pytest.raises(ValueError):
        await runtime.open_mission(
            mission_id="not publishable", brief="must fail before Prime"
        )
    assert registry.list_sessions() == []
    with pytest.raises(PrimeUnavailableError):
        await runtime.open_mission(mission_id="m-orphan", brief="must roll back")
    assert registry.list_sessions() == []
