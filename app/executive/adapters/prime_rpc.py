from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from app.executive.adapters.openrouter_generation import GenerationTelemetryResolver
from app.executive.adapters.prime import (
    PRIME_TELEMETRY_DIAGNOSTICS,
    NullPrimeAgent,
    PrimeMessageResult,
    PrimeRuntimeError,
    PrimeSessionInfo,
    PrimeTelemetryDiagnostic,
    PrimeUnavailableError,
)
from app.executive.delegation import ALLOWED_DELEGATION_ROLES
from app.executive.safety import (
    ExecutiveSafetyError,
    require_public_identifier,
    sanitize_private_input,
    sanitize_public_metadata,
    sanitize_public_text,
)
from app.executive.telemetry import (
    BOUNDED_TEST_PROFILE,
    DEFAULT_BOUNDED_TEST_POLICY,
    PUBLIC_GUEST_PROFILE,
    GenerationTelemetry,
    GenerationTelemetryError,
)

PRIME_AGENT_VERSION = "0.7.1"
PRIME_AGENT_COMMIT = "95afd319a78ae017a41241d50b013d656a0685ce"
OPENROUTER_AUTOROUTER_MODEL = "openrouter/auto"
# Prime 0.7.1 strips one explicit provider prefix, then prefers the canonical
# provider/id match. Two built-ins are named `auto` and `openrouter/auto`, so
# bounded startup needs this resolver spelling to select the latter exactly.
_BOUNDED_PRIME_CLI_MODEL = "openrouter/openrouter/openrouter/auto"

_MAX_FRAME_BYTES = 2 * 1024 * 1024
_GENERATION_STATUS_KEY = "orch71.openrouter-generation.v1"
_STREAM_RECEIPT_STATUS_KEY = "orch71.openrouter-stream-receipt.v1"
_TELEMETRY_STAGE_STATUS_KEY = "orch71.openrouter-telemetry-stage.v1"
_GENERATION_STATUS_FRAME_KEYS = frozenset(
    {"type", "id", "method", "statusKey", "statusText"}
)
_TELEMETRY_STAGE_VALUES = frozenset(
    {
        "payload_callback_observed",
        "payload_callback_unobserved",
        "payload_callback_passed",
        "payload_policy_rejected",
        "provider_response_2xx",
        "provider_response_unobserved",
        "provider_http_400",
        "provider_http_402",
        "provider_http_404",
        "provider_http_429",
        "provider_http_4xx_other",
        "provider_http_5xx",
        "provider_http_other",
        "generation_header_unobserved",
        "generation_header_missing",
        "generation_header_invalid",
        "generation_header_valid",
        "message_receipt_invalid",
        "message_receipt_valid",
    }
)
_PROVIDER_STAGE_VALUES = frozenset(
    value for value in _TELEMETRY_STAGE_VALUES if value.startswith("provider_")
)
_HEADER_STAGE_VALUES = frozenset(
    value for value in _TELEMETRY_STAGE_VALUES if value.startswith("generation_header_")
)
_MESSAGE_STAGE_VALUES = frozenset(
    value for value in _TELEMETRY_STAGE_VALUES if value.startswith("message_receipt_")
)
_STREAM_RECEIPT_KEYS = frozenset(
    {
        "contract",
        "contract_version",
        "source",
        "generation_id",
        "selected_model",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "actual_cost_usd",
    }
)
_GENERATION_ID_PATTERN = re.compile(r"^gen-[A-Za-z0-9][A-Za-z0-9._:-]{0,123}$")
_PINNED_PRIME_CLI_SHA256 = (
    "16e2324a4e3aa13305c437168d44d7395bab317e292218a52d1c61a7ebdf0993"
)
_PINNED_PRIME_PACKAGE_LOCK_SHA256 = (
    "72991596be21be3f508e83a8c0ff3c823fb7570fd645a64984ec1bb113fa2cf2"
)
_PINNED_PRIME_PACKAGE_JSON_SHA256 = (
    "1cfe001ea01cf5e1e942f7160a487534b3d5899474dff5b0687c4f0700a5ef0b"
)
_PINNED_RUNTIME_ASSETS = (
    (
        "package.json",
        2_135,
        0o644,
        "0bf756952f21542fa814acf301e0e868745b095eaf190b3457c729b41239a900",
    ),
    (
        "dist/modes/interactive/theme/prime.json",
        2_292,
        0o644,
        "cd504f1e2f769e5117f5d7756fea1505caae5f3481f356cde1ffadbb74c31489",
    ),
    (
        "dist/modes/interactive/theme/dark.json",
        2_249,
        0o644,
        "7e0e15ec4ff1f234ba9532a50df8b48b5ac6c09e1b159c812b4d2b2015a5fa61",
    ),
    (
        "dist/modes/interactive/theme/light.json",
        2_258,
        0o644,
        "0d51080a109651459f260012549331d6e32bdfdee8cc958928609a37cbd51d07",
    ),
)
_PINNED_BUNDLE_FILE_COUNT = 39
_PINNED_BUNDLE_BYTES = 13_900_111
_PINNED_BUNDLE_MODES = ((0o644, 38), (0o755, 1))
_PINNED_BUNDLE_TREE_SHA256 = (
    "f952caf385e86508787e21a006a0073ac729691d4479855f3bb7700f1baa85a4"
)
_PATCHED_BUNDLE_BYTES = 13_908_135
_PATCHED_BUNDLE_TREE_SHA256 = (
    "d279170525cc336c0b38db1509f7b9f64e739fd3bb323306716e080d2550082b"
)
_USAGE_MODULE_NAME = "openai-completions-T2XCYCXY.js"
_USAGE_MODULE_SHA256 = (
    "a9c07ee7754d624f251bf51b38576bb3f130fe6da4d177eeb03a6189bebdf5e5"
)
_PATCHED_USAGE_MODULE_SHA256 = (
    "5a1b3358927af531d311657c1c57db39062407453acacab14cef92e8cc8f6083"
)
_USAGE_PATCH_ANCHOR = b"""\
  calculateCost(model, usage, cacheWriteCost === void 0 ? void 0 : { cacheWrite: cacheWriteCost });
  return usage;"""
_USAGE_PATCH_REPLACEMENT = b"""\
  calculateCost(model, usage, cacheWriteCost === void 0 ? void 0 : { cacheWrite: cacheWriteCost });
  if (model.provider === "openrouter" && Object.prototype.hasOwnProperty.call(rawUsage, "cost") && typeof rawUsage.cost === "number" && Number.isFinite(rawUsage.cost) && rawUsage.cost >= 0) {
    usage.cost.total = rawUsage.cost;
  } else if (model.provider === "openrouter") {
    usage.cost.total = Number.NaN;
  }
  return usage;"""
# Prime 0.7.1 selects its detached, UID-global daemon both before argument
# parsing and again during runtime selection. Session-private bundles cannot
# safely own that shared process, so only their RPC path is made process-local.
_RPC_DAEMON_EARLY_MODULE_NAME = "chunk-VNU2AJHD.js"
_RPC_DAEMON_EARLY_MODULE_SHA256 = (
    "a9586f2afa99534b2a901c7427e1290894892df24798cdc491ffd9eec738600e"
)
_PATCHED_RPC_DAEMON_EARLY_MODULE_SHA256 = (
    "cb15725c59bed43bb4cbe4cebbb5eed019be4846168980e91a2222a2612cc49b"
)
_RPC_DAEMON_EARLY_PATCH_ANCHOR = (
    b'  if (modeIndex !== -1 && args[modeIndex + 1] === "daemon") {'
)
_RPC_DAEMON_EARLY_PATCH_REPLACEMENT = (
    b'  if (modeIndex !== -1 && (args[modeIndex + 1] === "daemon" || '
    b'args[modeIndex + 1] === "rpc")) {'
)
_RPC_DAEMON_RUNTIME_MODULE_NAME = "chunk-PNKBOUZJ.js"
_RPC_DAEMON_RUNTIME_MODULE_SHA256 = (
    "f601b11e9bd58ae6379b99b3bcc92a62d8548cfe5030d0a2ca66c082dfe9c5ef"
)
_PATCHED_RPC_DAEMON_RUNTIME_MODULE_SHA256 = (
    "2ae05552d28bfbe1e916094e04e0a16eb8748ec45131256ac0160379cbba4c5e"
)
_RPC_DAEMON_RUNTIME_PATCH_ANCHOR = b"""\
function shouldUseDaemonClientRuntime(options) {
  return shouldUseDaemonClient(options) && !options.ownedSessionWorker && !options.hasProcessLocalExtensionFactories;
}"""
_RPC_DAEMON_RUNTIME_PATCH_REPLACEMENT = b"""\
function shouldUseDaemonClientRuntime(options) {
  return options.appMode !== "rpc" && shouldUseDaemonClient(options) && !options.ownedSessionWorker && !options.hasProcessLocalExtensionFactories;
}"""
_OUTPUT_CAP_MODULE_SHA256 = _PATCHED_RPC_DAEMON_RUNTIME_MODULE_SHA256
_PATCHED_OUTPUT_CAP_MODULE_SHA256 = (
    "50459aefdff83f9f15dbc022c7816878c9db49458118d168b4a97f162104c2a9"
)
_BOUNDED_AUTOROUTER_ON_PAYLOAD = b"""\
async (payload2, requestModel2) => {
          const snapshotPayload = (value) => {
            try {
              if (
                value === null ||
                typeof value !== "object" ||
                Array.isArray(value) ||
                Object.getPrototypeOf(value) !== Object.prototype
              ) throw new Error();
              JSON.stringify(value, function (key, member) {
                if (key !== "") {
                  const descriptor = Object.getOwnPropertyDescriptor(this, key);
                  if (!descriptor || !("value" in descriptor)) throw new Error();
                }
                return member;
              });
              const clone = structuredClone(value);
              const encoded = JSON.stringify(clone);
              if (typeof encoded !== "string" || encoded.length > 65536) {
                throw new Error();
              }
              const snapshot = JSON.parse(encoded);
              if (
                snapshot === null ||
                typeof snapshot !== "object" ||
                Array.isArray(snapshot) ||
                Object.getPrototypeOf(snapshot) !== Object.prototype
              ) throw new Error();
              return { encoded, snapshot };
            } catch {
              throw new Error("Bounded OpenRouter request rejected");
            }
          };
          const originalRequestModel = snapshotPayload(requestModel2);
          const originalPayload = snapshotPayload(payload2);
          const hookRequestModel = structuredClone(originalRequestModel.snapshot);
          const hookPayload = structuredClone(originalPayload.snapshot);
          let priorPayload;
          try {
            priorPayload = await options2?.onPayload?.(
              hookPayload,
              hookRequestModel
            );
          } catch {
            throw new Error("Bounded OpenRouter request rejected");
          }
          if (priorPayload !== void 0 && priorPayload !== hookPayload) {
            throw new Error("Bounded OpenRouter request rejected");
          }
          const postHookPayload = snapshotPayload(payload2);
          const postHookRequestModel = snapshotPayload(requestModel2);
          const postCallbackPayload = snapshotPayload(hookPayload);
          const postCallbackRequestModel = snapshotPayload(hookRequestModel);
          if (
            originalPayload.encoded !== postHookPayload.encoded ||
            originalRequestModel.encoded !== postHookRequestModel.encoded ||
            originalPayload.encoded !== postCallbackPayload.encoded ||
            originalRequestModel.encoded !== postCallbackRequestModel.encoded
          ) {
            throw new Error("Bounded OpenRouter request rejected");
          }
          const boundedRequestModel = originalRequestModel.snapshot;
          const boundedPayload = originalPayload.snapshot;
          const providerPolicy = boundedPayload?.provider;
          const maxPrice = providerPolicy?.max_price;
          const reasoningPolicy = boundedPayload?.reasoning;
          const streamOptions = boundedPayload?.stream_options;
          const allowedPayloadKeys = new Set([
            "model",
            "messages",
            "stream",
            "stream_options",
            "store",
            "max_completion_tokens",
            "temperature",
            "reasoning",
            "provider",
            "plugins"
          ]);
          if (
            boundedPayload === null ||
            typeof boundedPayload !== "object" ||
            Array.isArray(boundedPayload) ||
            Object.getPrototypeOf(boundedPayload) !== Object.prototype ||
            Object.keys(boundedPayload).some(
              (key) => !allowedPayloadKeys.has(key)
            ) ||
            boundedRequestModel.provider !== "openrouter" ||
            boundedRequestModel.id !== "openrouter/auto" ||
            JSON.stringify(boundedRequestModel.input) !== '["text"]' ||
            boundedPayload.model !== "openrouter/auto" ||
            !Array.isArray(boundedPayload.messages) ||
            !boundedPayload.messages.every(
              (message) =>
                message !== null &&
                typeof message === "object" &&
                !Array.isArray(message) &&
                Object.keys(message).length === 2 &&
                ["developer", "system", "user"].includes(message.role) &&
                (typeof message.content === "string" ||
                  (Array.isArray(message.content) &&
                    message.content.every(
                      (part) =>
                        part !== null &&
                        typeof part === "object" &&
                        !Array.isArray(part) &&
                        Object.keys(part).length === 2 &&
                        part.type === "text" &&
                        typeof part.text === "string"
                    )))
            ) ||
            boundedPayload.stream !== true ||
            boundedPayload.store !== false ||
            boundedPayload.max_completion_tokens !== 600 ||
            (boundedPayload.temperature !== void 0 &&
              (typeof boundedPayload.temperature !== "number" ||
                !Number.isFinite(boundedPayload.temperature) ||
                boundedPayload.temperature < 0 ||
                boundedPayload.temperature > 2)) ||
            streamOptions === null ||
            typeof streamOptions !== "object" ||
            Array.isArray(streamOptions) ||
            Object.keys(streamOptions).length !== 1 ||
            streamOptions.include_usage !== true ||
            reasoningPolicy === null ||
            typeof reasoningPolicy !== "object" ||
            Array.isArray(reasoningPolicy) ||
            Object.keys(reasoningPolicy).length !== 1 ||
            reasoningPolicy.effort !== "none" ||
            providerPolicy === null ||
            typeof providerPolicy !== "object" ||
            Array.isArray(providerPolicy) ||
            Object.getPrototypeOf(providerPolicy) !== Object.prototype ||
            Object.keys(providerPolicy).length !== 4 ||
            providerPolicy.sort !== "price" ||
            providerPolicy.require_parameters !== true ||
            providerPolicy.data_collection !== "deny" ||
            maxPrice === null ||
            typeof maxPrice !== "object" ||
            Array.isArray(maxPrice) ||
            Object.getPrototypeOf(maxPrice) !== Object.prototype ||
            Object.keys(maxPrice).length !== 5 ||
            maxPrice.prompt !== 1 ||
            maxPrice.completion !== 5 ||
            maxPrice.request !== 0 ||
            maxPrice.image !== 0 ||
            maxPrice.audio !== 0
          ) {
            throw new Error("Bounded OpenRouter request rejected");
          }
          return {
            model: "openrouter/auto",
            messages: boundedPayload.messages,
            stream: true,
            stream_options: { include_usage: true },
            store: false,
            max_completion_tokens: 600,
            ...(boundedPayload.temperature === void 0
              ? {}
              : { temperature: boundedPayload.temperature }),
            reasoning: { effort: "none" },
            provider: {
              sort: "price",
              require_parameters: true,
              data_collection: "deny",
              max_price: {
                prompt: 1,
                completion: 5,
                request: 0,
                image: 0,
                audio: 0
              }
            },
            plugins: [{ id: "auto-router", cost_quality_tradeoff: 10 }]
          };
        }"""
_OUTPUT_CAP_PATCH_ANCHOR = b"""\
      return streamSimple(model2, context2, {
        ...options2,
        apiKey: auth.apiKey,
        timeoutMs: options2?.timeoutMs ?? providerRetrySettings.timeoutMs,
        maxRetries: options2?.maxRetries ?? providerRetrySettings.maxRetries,"""
_OUTPUT_CAP_PATCH_REPLACEMENT = (
    b"""\
      return streamSimple(structuredClone(model2), context2, {
        ...options2,
        maxTokens: 600,
        onPayload: """
    + _BOUNDED_AUTOROUTER_ON_PAYLOAD
    + b""",
        apiKey: auth.apiKey,
        timeoutMs: options2?.timeoutMs ?? providerRetrySettings.timeoutMs,
        maxRetries: 0,"""
)
_BOUNDED_SYSTEM_PROMPT = (
    "Return concise task output only. Never reveal private reasoning, credentials, "
    "tokens, browser data, or session data. Tools are disabled."
)
_BOUNDED_GENERATION_EXTENSION = f"""\
export default function (pi) {{
  let generationCount = 0;
  let pendingGenerationId;
  let payloadCallbackObserved = false;
  let providerResponseSeen = false;

  const emitStage = (ctx, stage) => {{
    ctx.ui.setStatus("{_TELEMETRY_STAGE_STATUS_KEY}", stage);
  }};

  const providerStage = (status) => {{
    if (status >= 200 && status < 300) return "provider_response_2xx";
    if (status === 400) return "provider_http_400";
    if (status === 402) return "provider_http_402";
    if (status === 404) return "provider_http_404";
    if (status === 429) return "provider_http_429";
    if (status >= 400 && status < 500) return "provider_http_4xx_other";
    if (status >= 500 && status < 600) return "provider_http_5xx";
    return "provider_http_other";
  }};

  const errorStatus = (message) => {{
    if (
      message?.stopReason !== "error" ||
      typeof message.errorMessage !== "string" ||
      message.errorMessage.length < 3
    ) return 0;
    const first = message.errorMessage.charCodeAt(0);
    const second = message.errorMessage.charCodeAt(1);
    const third = message.errorMessage.charCodeAt(2);
    if (
      first < 49 || first > 53 ||
      second < 48 || second > 57 ||
      third < 48 || third > 57 ||
      (message.errorMessage.length !== 3 &&
        message.errorMessage.charCodeAt(3) !== 32)
    ) return 0;
    return (first - 48) * 100 + (second - 48) * 10 + (third - 48);
  }};

  const resetGeneration = () => {{
    generationCount = 0;
    pendingGenerationId = undefined;
    payloadCallbackObserved = false;
    providerResponseSeen = false;
  }};

  pi.on("before_provider_request", (_event, ctx) => {{
    payloadCallbackObserved = true;
    emitStage(ctx, "payload_callback_observed");
  }});

  pi.on("after_provider_response", (event, ctx) => {{
    providerResponseSeen = true;
    generationCount = Math.min(generationCount + 1, 2);
    const generationId = event.headers?.["x-generation-id"];
    emitStage(ctx, "payload_callback_passed");
    emitStage(ctx, providerStage(event.status));
    emitStage(
      ctx,
      generationId === undefined
        ? "generation_header_missing"
        : typeof generationId === "string" &&
            /^gen-[A-Za-z0-9][A-Za-z0-9._:-]{{0,123}}$/.test(generationId)
          ? "generation_header_valid"
          : "generation_header_invalid"
    );
    if (
      event.status !== 200 ||
      generationCount !== 1 ||
      typeof generationId !== "string" ||
      !/^gen-[A-Za-z0-9][A-Za-z0-9._:-]{{0,123}}$/.test(generationId)
    ) {{
      pendingGenerationId = undefined;
      return;
    }}
    pendingGenerationId = generationId;
    ctx.ui.setStatus("{_GENERATION_STATUS_KEY}", generationId);
  }});

  pi.on("message_end", (event, ctx) => {{
    const headerCount = generationCount;
    const generationId = pendingGenerationId;
    const callbackObserved = payloadCallbackObserved;
    const responseSeen = providerResponseSeen;
    resetGeneration();

    const message = event.message;
    if (message?.role !== "assistant") return;
    if (!responseSeen) {{
      if (!callbackObserved) {{
        emitStage(ctx, "payload_callback_unobserved");
      }} else if (
        message.stopReason === "error" &&
        message.errorMessage === "Bounded OpenRouter request rejected"
      ) {{
        emitStage(ctx, "payload_policy_rejected");
      }} else {{
        emitStage(ctx, "payload_callback_passed");
        const status = errorStatus(message);
        emitStage(
          ctx,
          status === 0 ? "provider_response_unobserved" : providerStage(status)
        );
        emitStage(ctx, "generation_header_unobserved");
      }}
    }}
    const usage = message?.usage;
    const selectedModel = message?.responseModel;
    const inputTokens = Number.isSafeInteger(usage?.input) &&
      Number.isSafeInteger(usage?.cacheRead) &&
      Number.isSafeInteger(usage?.cacheWrite)
      ? usage.input + usage.cacheRead + usage.cacheWrite
      : -1;
    const outputTokens = usage?.output;
    const totalTokens = usage?.totalTokens;
    const actualCost = usage?.cost?.total;
    const receiptInvalid =
      headerCount !== 1 ||
      typeof generationId !== "string" ||
      message.provider !== "openrouter" ||
      message.responseId !== generationId ||
      typeof selectedModel !== "string" ||
      !/^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,199}}$/.test(selectedModel) ||
      !Number.isSafeInteger(inputTokens) ||
      !Number.isSafeInteger(outputTokens) ||
      !Number.isSafeInteger(totalTokens) ||
      inputTokens < 0 || outputTokens < 0 || totalTokens < 0 ||
      inputTokens > 100000000 || outputTokens > 100000000 ||
      totalTokens > 100000000 ||
      totalTokens !== inputTokens + outputTokens ||
      typeof actualCost !== "number" ||
      !Number.isFinite(actualCost) ||
      actualCost < 0 || actualCost > 1000;
    if (receiptInvalid) {{
      emitStage(ctx, "message_receipt_invalid");
      return;
    }}

    ctx.ui.setStatus("{_STREAM_RECEIPT_STATUS_KEY}", JSON.stringify({{
      contract: "orch.openrouter.stream-receipt",
      contract_version: "1.0",
      source: "openrouter_stream",
      generation_id: generationId,
      selected_model: selectedModel,
      input_tokens: inputTokens,
      output_tokens: outputTokens,
      total_tokens: totalTokens,
      actual_cost_usd: actualCost
    }}));
    emitStage(ctx, "message_receipt_valid");
  }});
}}
"""
_BOUNDED_MODEL_OVERRIDES = {
    "providers": {
        "openrouter": {
            "modelOverrides": {
                OPENROUTER_AUTOROUTER_MODEL: {
                    "input": ["text"],
                    "contextWindow": (
                        DEFAULT_BOUNDED_TEST_POLICY.reserved_tokens_per_generation
                    ),
                    "maxTokens": (
                        DEFAULT_BOUNDED_TEST_POLICY.max_output_tokens_per_generation
                    ),
                    "compat": {
                        "openRouterRouting": {
                            "sort": "price",
                            "require_parameters": True,
                            "data_collection": "deny",
                            "max_price": {
                                "prompt": float(
                                    DEFAULT_BOUNDED_TEST_POLICY.max_prompt_price_usd_per_million
                                ),
                                "completion": float(
                                    DEFAULT_BOUNDED_TEST_POLICY.max_completion_price_usd_per_million
                                ),
                                "request": float(
                                    DEFAULT_BOUNDED_TEST_POLICY.max_request_price_usd
                                ),
                                "image": float(
                                    DEFAULT_BOUNDED_TEST_POLICY.max_image_price_usd
                                ),
                                "audio": float(
                                    DEFAULT_BOUNDED_TEST_POLICY.max_audio_price_usd
                                ),
                            },
                        }
                    },
                }
            }
        }
    }
}


def _require_bounded_prime_state(state: dict[str, Any]) -> None:
    """Attest the effective bounded model without retaining vendor state."""

    model = state.get("model")
    if not isinstance(model, dict):
        raise PrimeRuntimeError("Prime RPC returned invalid bounded model state")
    if (
        model.get("provider") != "openrouter"
        or model.get("id") != OPENROUTER_AUTOROUTER_MODEL
        or model.get("input") != ["text"]
        or type(model.get("contextWindow")) is not int
        or model.get("contextWindow")
        != DEFAULT_BOUNDED_TEST_POLICY.reserved_tokens_per_generation
        or type(model.get("maxTokens")) is not int
        or model.get("maxTokens")
        != DEFAULT_BOUNDED_TEST_POLICY.max_output_tokens_per_generation
    ):
        raise PrimeRuntimeError("Prime RPC returned invalid bounded model state")


_ENV_ALLOWLIST = frozenset(
    {
        "PATH",
        "HOME",
        "USERPROFILE",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "OPENROUTER_API_KEY",
    }
)


def build_prime_environment(source: Mapping[str, str]) -> dict[str, str]:
    """Copy only runtime basics and the one provider credential Prime needs."""

    return {
        key.upper(): value
        for key, value in source.items()
        if key.upper() in _ENV_ALLOWLIST and isinstance(value, str)
    }


def _read_regular_file(path: Path) -> tuple[bytes, int]:
    """Read one non-symlink regular file without accepting an artifact swap."""

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise PrimeRuntimeError("Pinned Prime artifact is unavailable")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            data = handle.read()
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if any(getattr(before, name) != getattr(after, name) for name in stable_fields):
        raise PrimeRuntimeError("Pinned Prime artifact changed during verification")
    if len(data) != before.st_size:
        raise PrimeRuntimeError("Pinned Prime artifact is incomplete")
    return data, stat.S_IMODE(before.st_mode)


def _bundle_fingerprint(
    bundle_dir: Path,
) -> tuple[int, int, tuple[tuple[int, int], ...], str]:
    """Return a deterministic direct-file manifest without following links."""

    entries = sorted(bundle_dir.iterdir(), key=lambda item: item.name)
    if not entries or any(item.is_symlink() for item in entries):
        raise PrimeRuntimeError("Pinned Prime bundle layout is unavailable")
    digest = hashlib.sha256()
    total_bytes = 0
    mode_counts: dict[int, int] = {}
    for entry in entries:
        data, mode = _read_regular_file(entry)
        total_bytes += len(data)
        mode_counts[mode] = mode_counts.get(mode, 0) + 1
        digest.update(entry.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(f"{mode:04o}".encode("ascii"))
        digest.update(b"\0")
        digest.update(str(len(data)).encode("ascii"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).hexdigest().encode("ascii"))
        digest.update(b"\n")
    return (
        len(entries),
        total_bytes,
        tuple(sorted(mode_counts.items())),
        digest.hexdigest(),
    )


def _require_bundle_fingerprint(
    bundle_dir: Path,
    *,
    total_bytes: int,
    tree_sha256: str,
) -> None:
    expected = (
        _PINNED_BUNDLE_FILE_COUNT,
        total_bytes,
        _PINNED_BUNDLE_MODES,
        tree_sha256,
    )
    if _bundle_fingerprint(bundle_dir) != expected:
        raise PrimeRuntimeError("Pinned Prime bundle verification failed")


def _require_runtime_asset(
    path: Path,
    *,
    expected_bytes: int,
    expected_mode: int,
    expected_sha256: str,
) -> bytes:
    try:
        data, mode = _read_regular_file(path)
    except PrimeRuntimeError:
        raise
    except (OSError, ValueError) as exc:
        raise PrimeRuntimeError(
            "Pinned Prime runtime asset verification failed"
        ) from exc
    if (
        len(data) != expected_bytes
        or mode != expected_mode
        or hashlib.sha256(data).hexdigest() != expected_sha256
    ):
        raise PrimeRuntimeError("Pinned Prime runtime asset verification failed")
    return data


def _copy_pinned_runtime_assets(
    package_root: Path,
    shadow_package_root: Path,
) -> None:
    """Copy only the fixed package metadata and themes needed by RPC startup."""

    verified_assets: list[tuple[Path, bytes, int, int, str]] = []
    for (
        relative_name,
        expected_bytes,
        expected_mode,
        expected_sha256,
    ) in _PINNED_RUNTIME_ASSETS:
        relative_path = Path(relative_name)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise PrimeRuntimeError("Pinned Prime runtime asset path is invalid")
        source = package_root / relative_path
        data = _require_runtime_asset(
            source,
            expected_bytes=expected_bytes,
            expected_mode=expected_mode,
            expected_sha256=expected_sha256,
        )
        verified_assets.append(
            (
                relative_path,
                data,
                expected_bytes,
                expected_mode,
                expected_sha256,
            )
        )

    for (
        relative_path,
        data,
        expected_bytes,
        expected_mode,
        expected_sha256,
    ) in verified_assets:
        destination = shadow_package_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        destination.chmod(expected_mode)
        _require_runtime_asset(
            destination,
            expected_bytes=expected_bytes,
            expected_mode=expected_mode,
            expected_sha256=expected_sha256,
        )


def _patch_exact_bundle_module(
    bundle_dir: Path,
    *,
    module_name: str,
    source_sha256: str,
    patched_sha256: str,
    anchor: bytes,
    replacement: bytes,
) -> None:
    """Apply one pinned, bounded-only patch without accepting source drift."""

    module = bundle_dir / module_name
    try:
        source, source_mode = _read_regular_file(module)
    except PrimeRuntimeError:
        raise
    except (OSError, ValueError) as exc:
        raise PrimeRuntimeError(
            "Pinned Prime bounded module verification failed"
        ) from exc
    if hashlib.sha256(source).hexdigest() != source_sha256 or source.count(anchor) != 1:
        raise PrimeRuntimeError("Pinned Prime bounded module verification failed")
    module.write_bytes(source.replace(anchor, replacement, 1))
    module.chmod(source_mode)
    patched, patched_mode = _read_regular_file(module)
    if (
        patched_mode != source_mode
        or hashlib.sha256(patched).hexdigest() != patched_sha256
    ):
        raise PrimeRuntimeError("Pinned Prime bounded module patch failed")


def _prepare_bounded_prime_executable(
    executable: str,
    runtime_dir: Path,
    *,
    search_path: str | None = None,
) -> str:
    """Build one fail-closed, session-private Prime accounting adapter."""

    try:
        executable_path = Path(executable)
        if executable_path.parent == Path("."):
            discovered = shutil.which(executable, path=search_path)
            if discovered is None:
                raise PrimeRuntimeError("Pinned Prime executable is unavailable")
            executable_path = Path(discovered)
        resolved_cli = executable_path.resolve(strict=True)
        bundle_dir = resolved_cli.parent
        package_root = bundle_dir.parent.parent
        node_modules_root = package_root.parent
        install_root = node_modules_root.parent
        if (
            resolved_cli.name != "cli.js"
            or bundle_dir.name != "bundle"
            or bundle_dir.parent.name != "dist"
            or package_root.name != "prime-agent"
            or node_modules_root.name != "node_modules"
            or install_root.name != PRIME_AGENT_VERSION
        ):
            raise PrimeRuntimeError("Pinned Prime install layout is unavailable")

        cli_source, source_cli_mode = _read_regular_file(resolved_cli)
        package_lock, _ = _read_regular_file(install_root / "package-lock.json")
        package_json, _ = _read_regular_file(install_root / "package.json")
        if (
            hashlib.sha256(cli_source).hexdigest() != _PINNED_PRIME_CLI_SHA256
            or hashlib.sha256(package_lock).hexdigest()
            != _PINNED_PRIME_PACKAGE_LOCK_SHA256
            or hashlib.sha256(package_json).hexdigest()
            != _PINNED_PRIME_PACKAGE_JSON_SHA256
        ):
            raise PrimeRuntimeError("Pinned Prime install verification failed")
        _require_bundle_fingerprint(
            bundle_dir,
            total_bytes=_PINNED_BUNDLE_BYTES,
            tree_sha256=_PINNED_BUNDLE_TREE_SHA256,
        )

        shadow_package_root = runtime_dir / "prime-agent"
        _copy_pinned_runtime_assets(package_root, shadow_package_root)
        shadow_bundle = shadow_package_root / "dist" / "bundle"
        shutil.copytree(bundle_dir, shadow_bundle, copy_function=shutil.copy2)
        _require_bundle_fingerprint(
            shadow_bundle,
            total_bytes=_PINNED_BUNDLE_BYTES,
            tree_sha256=_PINNED_BUNDLE_TREE_SHA256,
        )

        _patch_exact_bundle_module(
            shadow_bundle,
            module_name=_USAGE_MODULE_NAME,
            source_sha256=_USAGE_MODULE_SHA256,
            patched_sha256=_PATCHED_USAGE_MODULE_SHA256,
            anchor=_USAGE_PATCH_ANCHOR,
            replacement=_USAGE_PATCH_REPLACEMENT,
        )
        _patch_exact_bundle_module(
            shadow_bundle,
            module_name=_RPC_DAEMON_EARLY_MODULE_NAME,
            source_sha256=_RPC_DAEMON_EARLY_MODULE_SHA256,
            patched_sha256=_PATCHED_RPC_DAEMON_EARLY_MODULE_SHA256,
            anchor=_RPC_DAEMON_EARLY_PATCH_ANCHOR,
            replacement=_RPC_DAEMON_EARLY_PATCH_REPLACEMENT,
        )
        _patch_exact_bundle_module(
            shadow_bundle,
            module_name=_RPC_DAEMON_RUNTIME_MODULE_NAME,
            source_sha256=_RPC_DAEMON_RUNTIME_MODULE_SHA256,
            patched_sha256=_PATCHED_RPC_DAEMON_RUNTIME_MODULE_SHA256,
            anchor=_RPC_DAEMON_RUNTIME_PATCH_ANCHOR,
            replacement=_RPC_DAEMON_RUNTIME_PATCH_REPLACEMENT,
        )
        _patch_exact_bundle_module(
            shadow_bundle,
            module_name=_RPC_DAEMON_RUNTIME_MODULE_NAME,
            source_sha256=_OUTPUT_CAP_MODULE_SHA256,
            patched_sha256=_PATCHED_OUTPUT_CAP_MODULE_SHA256,
            anchor=_OUTPUT_CAP_PATCH_ANCHOR,
            replacement=_OUTPUT_CAP_PATCH_REPLACEMENT,
        )
        _require_bundle_fingerprint(
            shadow_bundle,
            total_bytes=_PATCHED_BUNDLE_BYTES,
            tree_sha256=_PATCHED_BUNDLE_TREE_SHA256,
        )

        dependency_bridge = runtime_dir / "node_modules"
        dependency_bridge.symlink_to(node_modules_root, target_is_directory=True)
        if (
            not dependency_bridge.is_symlink()
            or dependency_bridge.resolve(strict=True) != node_modules_root
        ):
            raise PrimeRuntimeError("Pinned Prime dependency bridge failed")
        shadow_cli = shadow_bundle / "cli.js"
        cli_copy, cli_mode = _read_regular_file(shadow_cli)
        if (
            hashlib.sha256(cli_copy).hexdigest() != _PINNED_PRIME_CLI_SHA256
            or cli_mode != source_cli_mode
        ):
            raise PrimeRuntimeError("Pinned Prime private executable is unavailable")
        return str(shadow_cli)
    except PrimeRuntimeError:
        raise
    except (OSError, ValueError) as exc:
        raise PrimeRuntimeError("Pinned Prime bounded adapter is unavailable") from exc


async def _prepare_bounded_prime_executable_async(
    executable: str,
    runtime_dir: Path,
    *,
    search_path: str | None = None,
) -> str:
    """Keep the event loop responsive and finish private copying before cleanup."""

    task = asyncio.create_task(
        asyncio.to_thread(
            _prepare_bounded_prime_executable,
            executable,
            runtime_dir,
            search_path=search_path,
        )
    )
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await asyncio.shield(task)
        except Exception:  # noqa: BLE001, S110 - preserve original cancellation
            pass
        raise


def _safe_body_generation_id(frame: dict[str, Any]) -> str | None:
    """Extract only the pinned assistant response id; retain no message payload."""

    messages = frame.get("messages")
    if not isinstance(messages, list):
        return None
    for message in reversed(messages[-64:]):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        try:
            return require_public_identifier(message.get("responseId"))
        except ExecutiveSafetyError:
            return None
    return None


def _safe_header_generation_id(frame: dict[str, Any]) -> str | None:
    """Accept only the private bounded extension's exact scalar RPC frame."""

    if set(frame) != _GENERATION_STATUS_FRAME_KEYS:
        return None
    if (
        frame.get("type") != "extension_ui_request"
        or frame.get("method") != "setStatus"
        or frame.get("statusKey") != _GENERATION_STATUS_KEY
    ):
        return None
    try:
        require_public_identifier(frame.get("id"))
        generation_id = require_public_identifier(frame.get("statusText"))
    except ExecutiveSafetyError:
        return None
    if _GENERATION_ID_PATTERN.fullmatch(generation_id) is None:
        return None
    return generation_id


def _safe_telemetry_stage(frame: dict[str, Any]) -> str | None:
    """Accept one exact, content-blind bounded telemetry stage."""

    if set(frame) != _GENERATION_STATUS_FRAME_KEYS:
        return None
    if (
        frame.get("type") != "extension_ui_request"
        or frame.get("method") != "setStatus"
        or frame.get("statusKey") != _TELEMETRY_STAGE_STATUS_KEY
    ):
        return None
    try:
        require_public_identifier(frame.get("id"))
    except ExecutiveSafetyError:
        return None
    stage = frame.get("statusText")
    return (
        stage if isinstance(stage, str) and stage in _TELEMETRY_STAGE_VALUES else None
    )


def _telemetry_diagnostic(
    stages: tuple[str, ...],
    *,
    invalid: bool,
    receipt: GenerationTelemetry | None,
    generation_status_seen: bool,
    stream_status_seen: bool,
) -> PrimeTelemetryDiagnostic:
    """Collapse fixed stages to one safe, root-cause-oriented result."""

    if invalid:
        return "telemetry_diagnostic_invalid"
    if (
        len(stages) >= 4
        and stages[3]
        in {
            "generation_header_unobserved",
            "generation_header_missing",
            "generation_header_invalid",
        }
        and generation_status_seen
    ) or (
        len(stages) >= 5
        and stages[4] == "message_receipt_invalid"
        and stream_status_seen
    ):
        return "telemetry_diagnostic_invalid"
    if receipt is not None:
        return "telemetry_adapter_correlated"
    if not stages:
        return "telemetry_payload_callback_unobserved"
    if stages[0] == "payload_callback_unobserved":
        return "telemetry_payload_callback_unobserved"
    if stages[0] != "payload_callback_observed" or len(stages) == 1:
        return "telemetry_diagnostic_invalid"
    if stages[1] == "payload_policy_rejected":
        return "telemetry_payload_policy_rejected"
    if stages[1] != "payload_callback_passed":
        return "telemetry_diagnostic_invalid"
    if len(stages) == 2:
        return "telemetry_provider_response_unobserved"

    provider = stages[2]
    provider_diagnostic = f"telemetry_{provider}"
    if provider != "provider_response_2xx":
        if provider_diagnostic in PRIME_TELEMETRY_DIAGNOSTICS:
            return provider_diagnostic  # type: ignore[return-value]
        return "telemetry_diagnostic_invalid"
    if len(stages) == 3:
        return "telemetry_provider_response_2xx"

    header = stages[3]
    if header != "generation_header_valid":
        header_diagnostic = f"telemetry_{header}"
        if header_diagnostic in PRIME_TELEMETRY_DIAGNOSTICS:
            return header_diagnostic  # type: ignore[return-value]
        return "telemetry_diagnostic_invalid"
    if len(stages) == 4:
        return "telemetry_message_receipt_unobserved"
    if stages[4] == "message_receipt_invalid":
        return "telemetry_message_receipt_invalid"
    if stages[4] == "message_receipt_valid":
        return "telemetry_adapter_correlation_failed"
    return "telemetry_diagnostic_invalid"


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(_: str) -> None:
    raise ValueError("non-finite JSON number")


def _safe_stream_receipt(frame: dict[str, Any]) -> GenerationTelemetry | None:
    """Accept only the bounded extension's exact scalar stream receipt."""

    if set(frame) != _GENERATION_STATUS_FRAME_KEYS:
        return None
    if (
        frame.get("type") != "extension_ui_request"
        or frame.get("method") != "setStatus"
        or frame.get("statusKey") != _STREAM_RECEIPT_STATUS_KEY
    ):
        return None
    status_text = frame.get("statusText")
    if (
        not isinstance(status_text, str)
        or len(status_text) > 2_048
        or any(character in status_text for character in ("\x00", "\r", "\n"))
    ):
        return None
    try:
        require_public_identifier(frame.get("id"))
        receipt = json.loads(
            status_text,
            object_pairs_hook=_unique_json_object,
            parse_float=Decimal,
            parse_constant=_reject_json_constant,
        )
        if not isinstance(receipt, dict) or set(receipt) != _STREAM_RECEIPT_KEYS:
            return None
        if (
            receipt.get("contract") != "orch.openrouter.stream-receipt"
            or receipt.get("contract_version") != "1.0"
            or receipt.get("source") != "openrouter_stream"
        ):
            return None
        actual_cost = receipt.get("actual_cost_usd")
        if isinstance(actual_cost, bool) or not isinstance(actual_cost, (int, Decimal)):
            return None
        generation_id = receipt.get("generation_id")
        if (
            not isinstance(generation_id, str)
            or _GENERATION_ID_PATTERN.fullmatch(generation_id) is None
        ):
            return None
        return GenerationTelemetry.build(
            generation_id=generation_id,
            selected_model=receipt.get("selected_model"),
            input_tokens=receipt.get("input_tokens"),
            output_tokens=receipt.get("output_tokens"),
            total_tokens=receipt.get("total_tokens"),
            actual_cost_usd=actual_cost,
            source="openrouter_stream",
        )
    except (
        ExecutiveSafetyError,
        GenerationTelemetryError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        return None


@runtime_checkable
class PrimeRpcTransport(Protocol):
    """Strict JSONL byte transport; tests provide an in-memory subprocess fake."""

    async def start(
        self,
        *,
        argv: tuple[str, ...],
        env: Mapping[str, str],
        cwd: str | None,
    ) -> None: ...

    async def write_line(self, line: bytes) -> None: ...

    async def read_line(self) -> bytes | None: ...

    async def close(self) -> None: ...


class SubprocessPrimeRpcTransport:
    """Documented Prime v0.7.1 JSONL transport with stderr suppressed."""

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None

    async def start(
        self,
        *,
        argv: tuple[str, ...],
        env: Mapping[str, str],
        cwd: str | None,
    ) -> None:
        if self._process is not None:
            raise PrimeRuntimeError("Prime RPC transport is already started")
        try:
            self._process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=cwd,
                env=dict(env),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=_MAX_FRAME_BYTES,
            )
        except (OSError, ValueError) as exc:
            raise PrimeUnavailableError("Prime RPC process could not start") from exc

    async def write_line(self, line: bytes) -> None:
        process = self._process
        if process is None or process.stdin is None or process.returncode is not None:
            raise PrimeUnavailableError("Prime RPC process is unavailable")
        if not line.endswith(b"\n") or line[:-1].find(b"\n") >= 0:
            raise PrimeRuntimeError("Prime RPC requires one LF-delimited JSON record")
        process.stdin.write(line)
        try:
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise PrimeUnavailableError("Prime RPC process closed its input") from exc

    async def read_line(self) -> bytes | None:
        process = self._process
        if process is None or process.stdout is None:
            raise PrimeUnavailableError("Prime RPC process is unavailable")
        try:
            line = await process.stdout.readline()
        except (ValueError, asyncio.LimitOverrunError) as exc:
            raise PrimeRuntimeError("Prime RPC frame exceeds its size limit") from exc
        return line or None

    async def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.stdin is not None:
            process.stdin.close()
        cancellation: asyncio.CancelledError | None = None
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError as exc:
                cancellation = exc
            finally:
                if process.returncode is None:
                    process.kill()
                    wait_task = asyncio.create_task(process.wait())
                    try:
                        await asyncio.shield(wait_task)
                    except asyncio.CancelledError as exc:
                        cancellation = cancellation or exc
                        await asyncio.shield(wait_task)
        if cancellation is not None:
            raise cancellation


class PrimeRpcClient:
    """Correlated Prime RPC client that never retains event payloads."""

    def __init__(
        self,
        transport: PrimeRpcTransport,
        *,
        command_timeout_seconds: float = 30.0,
        turn_timeout_seconds: float = 600.0,
        reject_compaction: bool = False,
        capture_generation_headers: bool = False,
    ) -> None:
        self.transport = transport
        self.command_timeout_seconds = float(command_timeout_seconds)
        self.turn_timeout_seconds = float(turn_timeout_seconds)
        self.reject_compaction = bool(reject_compaction)
        self.capture_generation_headers = bool(capture_generation_headers)
        self._next_id = 0
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._reader: asyncio.Task[None] | None = None
        self._write_lock = asyncio.Lock()
        self._agent_end_count = 0
        self._agent_end = asyncio.Event()
        self._agent_end_receipts: dict[int, str | GenerationTelemetry | None] = {}
        self._generation_window_open = False
        self._generation_header_count = 0
        self._generation_header_id: str | None = None
        self._stream_receipt_count = 0
        self._stream_receipt: GenerationTelemetry | None = None
        self._telemetry_stages: list[str] = []
        self._telemetry_stage_invalid = False
        self._last_telemetry_diagnostic: PrimeTelemetryDiagnostic | None = None
        self._fatal: PrimeRuntimeError | None = None

    @property
    def last_telemetry_diagnostic(self) -> PrimeTelemetryDiagnostic | None:
        return self._last_telemetry_diagnostic

    def _open_generation_window(self) -> None:
        self._generation_window_open = True
        self._generation_header_count = 0
        self._generation_header_id = None
        self._stream_receipt_count = 0
        self._stream_receipt = None
        self._telemetry_stages = []
        self._telemetry_stage_invalid = False
        self._last_telemetry_diagnostic = None

    def _record_telemetry_stage(self, frame: dict[str, Any]) -> None:
        stage = _safe_telemetry_stage(frame)
        trace = tuple(self._telemetry_stages)
        if not trace:
            expected = frozenset(
                {"payload_callback_observed", "payload_callback_unobserved"}
            )
        elif trace == ("payload_callback_observed",):
            expected = frozenset({"payload_callback_passed", "payload_policy_rejected"})
        elif trace == ("payload_callback_unobserved",) or trace == (
            "payload_callback_observed",
            "payload_policy_rejected",
        ):
            expected = frozenset({"message_receipt_invalid"})
        elif trace == (
            "payload_callback_observed",
            "payload_callback_passed",
        ):
            expected = _PROVIDER_STAGE_VALUES
        elif (
            len(trace) == 3
            and trace[:2] == ("payload_callback_observed", "payload_callback_passed")
            and trace[2] in _PROVIDER_STAGE_VALUES
        ):
            expected = (
                frozenset({"generation_header_unobserved"})
                if trace[2] == "provider_response_unobserved"
                else _HEADER_STAGE_VALUES
            )
        elif (
            len(trace) == 4
            and trace[:2] == ("payload_callback_observed", "payload_callback_passed")
            and trace[2] in _PROVIDER_STAGE_VALUES
            and trace[3] in _HEADER_STAGE_VALUES
        ):
            expected = (
                _MESSAGE_STAGE_VALUES
                if trace[2] == "provider_response_2xx"
                and trace[3] == "generation_header_valid"
                else frozenset({"message_receipt_invalid"})
            )
        else:
            expected = frozenset()
        if stage is None or stage not in expected:
            self._telemetry_stage_invalid = True
            return
        self._telemetry_stages.append(stage)

    def _record_generation_status(self, frame: dict[str, Any]) -> None:
        if not self.capture_generation_headers or not self._generation_window_open:
            return
        status_key = frame.get("statusKey")
        if status_key == _GENERATION_STATUS_KEY:
            self._generation_header_count = min(self._generation_header_count + 1, 2)
            generation_id = _safe_header_generation_id(frame)
            if self._generation_header_count == 1:
                self._generation_header_id = generation_id
            else:
                self._generation_header_id = None
        elif status_key == _STREAM_RECEIPT_STATUS_KEY:
            self._stream_receipt_count = min(self._stream_receipt_count + 1, 2)
            receipt = _safe_stream_receipt(frame)
            if self._stream_receipt_count == 1:
                self._stream_receipt = receipt
            else:
                self._stream_receipt = None
        elif status_key == _TELEMETRY_STAGE_STATUS_KEY:
            self._record_telemetry_stage(frame)

    def _close_generation_window(self) -> GenerationTelemetry | None:
        window_was_open = self._generation_window_open
        receipt = (
            self._stream_receipt
            if (
                self._generation_window_open
                and self._generation_header_count == 1
                and self._stream_receipt_count == 1
                and self._generation_header_id is not None
                and self._stream_receipt is not None
                and self._generation_header_id == self._stream_receipt.generation_id
            )
            else None
        )
        if window_was_open:
            self._last_telemetry_diagnostic = _telemetry_diagnostic(
                tuple(self._telemetry_stages),
                invalid=self._telemetry_stage_invalid,
                receipt=receipt,
                generation_status_seen=self._generation_header_count > 0,
                stream_status_seen=self._stream_receipt_count > 0,
            )
        self._generation_window_open = False
        self._generation_header_count = 0
        self._generation_header_id = None
        self._stream_receipt_count = 0
        self._stream_receipt = None
        self._telemetry_stages = []
        self._telemetry_stage_invalid = False
        return receipt

    async def start(
        self,
        *,
        argv: tuple[str, ...],
        env: Mapping[str, str],
        cwd: str | None,
    ) -> None:
        await self.transport.start(argv=argv, env=env, cwd=cwd)
        self._reader = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        try:
            while True:
                line = await self.transport.read_line()
                if line is None:
                    raise PrimeUnavailableError("Prime RPC process ended")
                if len(line) > _MAX_FRAME_BYTES or not line.endswith(b"\n"):
                    raise PrimeRuntimeError("Prime RPC emitted an invalid JSONL frame")
                record = line[:-1]
                if record.endswith(b"\r"):
                    record = record[:-1]
                try:
                    frame = json.loads(record.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise PrimeRuntimeError("Prime RPC emitted invalid JSON") from exc
                if not isinstance(frame, dict):
                    raise PrimeRuntimeError("Prime RPC emitted a non-object frame")

                frame_type = frame.get("type")
                if frame_type == "response":
                    request_id = frame.get("id")
                    future = self._pending.pop(request_id, None)
                    if future is not None and not future.done():
                        future.set_result(frame)
                elif frame_type == "extension_ui_request":
                    self._record_generation_status(frame)
                elif frame_type == "agent_end":
                    self._agent_end_count += 1
                    self._agent_end_receipts[self._agent_end_count] = (
                        self._close_generation_window()
                        if self.capture_generation_headers
                        else _safe_body_generation_id(frame)
                    )
                    self._agent_end.set()
                    # The complete messages/tool/thinking payload is discarded here.
                elif (
                    self.reject_compaction
                    and isinstance(frame_type, str)
                    and "compaction" in frame_type.lower()
                ):
                    raise PrimeRuntimeError(
                        "Prime RPC emitted an unexpected compaction event"
                    )
                # All other event payloads, including message_update thinking/tool
                # deltas and tool results, are ignored and never stored or logged.
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - convert to a safe boundary error
            self._fatal = (
                exc
                if isinstance(exc, PrimeRuntimeError)
                else PrimeRuntimeError("Prime RPC failed")
            )
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(self._fatal)
            self._pending.clear()
            self._agent_end.set()

    async def request(self, command: str, **fields: Any) -> dict[str, Any]:
        if self._fatal is not None:
            raise self._fatal
        self._next_id += 1
        request_id = f"req-{self._next_id}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = future
        record = {"id": request_id, "type": command, **fields}
        encoded = (
            json.dumps(record, separators=(",", ":"), ensure_ascii=True) + "\n"
        ).encode("utf-8")
        try:
            async with self._write_lock:
                await self.transport.write_line(encoded)
            response = await asyncio.wait_for(
                future, timeout=self.command_timeout_seconds
            )
        except asyncio.TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise PrimeRuntimeError(f"Prime RPC {command} timed out") from exc
        except BaseException:
            self._pending.pop(request_id, None)
            if not future.done():
                future.cancel()
            raise
        if response.get("command") != command or response.get("success") is not True:
            raise PrimeRuntimeError(f"Prime RPC {command} failed")
        return response

    async def prompt_and_wait(
        self, message: str
    ) -> tuple[str, str | GenerationTelemetry | None]:
        baseline = self._agent_end_count
        if self.capture_generation_headers:
            self._open_generation_window()
        try:
            await self.request("prompt", message=message)
            while self._agent_end_count <= baseline:
                self._agent_end.clear()
                if self._agent_end_count > baseline:
                    break
                await asyncio.wait_for(
                    self._agent_end.wait(), timeout=self.turn_timeout_seconds
                )
                if self._fatal is not None:
                    raise self._fatal
            if self._agent_end_count != baseline + 1:
                raise PrimeRuntimeError(
                    "Prime RPC emitted an unexpected generation count"
                )
        except asyncio.TimeoutError as exc:
            self._close_generation_window()
            raise PrimeRuntimeError("Prime RPC turn timed out") from exc
        except BaseException:
            self._close_generation_window()
            raise
        response = await self.request("get_last_assistant_text")
        if self._agent_end_count != baseline + 1:
            raise PrimeRuntimeError("Prime RPC emitted an unexpected generation count")
        data = response.get("data")
        text = data.get("text") if isinstance(data, dict) else None
        if not isinstance(text, str):
            raise PrimeRuntimeError("Prime RPC returned no assistant text")
        receipt = self._agent_end_receipts.pop(baseline + 1, None)
        return text, receipt

    async def close(self) -> None:
        shutdown = PrimeUnavailableError("Prime RPC client is closing")
        self._fatal = self._fatal or shutdown
        for future in self._pending.values():
            if not future.done():
                future.set_exception(self._fatal)
        self._pending.clear()
        self._agent_end.set()
        self._close_generation_window()
        self._agent_end_receipts.clear()
        reader = self._reader
        self._reader = None
        if reader is not None:
            reader.cancel()
        try:
            await self.transport.close()
        finally:
            if reader is not None:
                try:
                    await reader
                except asyncio.CancelledError:
                    pass


@dataclass
class _LivePrimeSession:
    info: PrimeSessionInfo
    client: PrimeRpcClient
    telemetry_required: bool = False
    runtime_config: tempfile.TemporaryDirectory[str] | None = field(
        default=None,
        repr=False,
    )
    turn_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class PrimeJsonlRpcAgent:
    """Prime v0.7.1 adapter for isolated executive and specialist processes.

    Every local session owns one independent RPC process. Tools and Prime session
    persistence are always disabled because Prime is not a security sandbox.
    """

    name = "prime-jsonl-rpc"

    def __init__(
        self,
        *,
        executable: str = "prime-agent",
        cwd: str | None = None,
        environment: Mapping[str, str] | None = None,
        transport_factory: Callable[[], PrimeRpcTransport] | None = None,
        allow_tools: bool = False,
        command_timeout_seconds: float = 30.0,
        turn_timeout_seconds: float = 600.0,
        cleanup_timeout_seconds: float = 5.0,
        generation_resolver: GenerationTelemetryResolver | None = None,
    ) -> None:
        if allow_tools:
            raise PrimeRuntimeError("Prime RPC tools are disabled")
        self.executable = executable
        if cwd is None:
            if transport_factory is None:
                raise PrimeRuntimeError("Prime RPC requires an isolated workdir")
            self.cwd = None
        else:
            self.cwd = _validated_isolated_workdir(cwd)
            if self.cwd is None:
                raise PrimeRuntimeError("Prime RPC isolated workdir is invalid")
        self.allow_tools = False
        env_source = environment if environment is not None else os.environ
        self._env = build_prime_environment(env_source)
        # Never give Prime the service account's real home/profile. Production
        # construction requires an isolated workdir; direct fake transports may
        # omit one, in which case the inherited home variables are removed.
        if self.cwd is None:
            self._env.pop("HOME", None)
            self._env.pop("USERPROFILE", None)
        else:
            self._env["HOME"] = self.cwd
            self._env["USERPROFILE"] = self.cwd
        self._factory = transport_factory or SubprocessPrimeRpcTransport
        self._custom_transport = transport_factory is not None
        self._command_timeout = float(command_timeout_seconds)
        self._turn_timeout = float(turn_timeout_seconds)
        self._cleanup_timeout = max(0.1, min(float(cleanup_timeout_seconds), 10.0))
        self._sessions: dict[str, _LivePrimeSession] = {}
        self._last_error: str | None = None
        # Retain the constructor seam for callers pinned to the prior adapter,
        # but bounded execution must never fall back to asynchronous history.
        self._generation_resolver = generation_resolver

    def _binary_available(self) -> bool:
        path = Path(self.executable)
        if path.parent != Path("."):
            return path.is_file()
        return shutil.which(self.executable, path=self._env.get("PATH")) is not None

    async def health(self) -> dict[str, Any]:
        binary = self._custom_transport or self._binary_available()
        credentials = bool(self._env.get("OPENROUTER_API_KEY"))
        available = binary and credentials
        return {
            "ok": available,
            "available": available,
            "availability": "ready" if available else "unavailable",
            "adapter": self.name,
            "prime_binary": binary,
            "rpc": available,
            "live": available,
            "credentials_configured": credentials,
            "provider": "openrouter",
            "model": OPENROUTER_AUTOROUTER_MODEL,
            "expected_protocol_version": PRIME_AGENT_VERSION,
            "expected_protocol_commit": PRIME_AGENT_COMMIT,
            "version_verified": False,
            "tools_enabled": self.allow_tools,
            "isolated_workdir_configured": self.cwd is not None,
            "last_error": self._last_error,
        }

    async def start_session(
        self,
        *,
        role_name: str,
        parent_session_id: str | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PrimeSessionInfo:
        del model
        role = str(role_name or "").strip()
        bounded_profile = bool(
            isinstance(metadata, dict)
            and metadata.get("execution_profile")
            in {BOUNDED_TEST_PROFILE, PUBLIC_GUEST_PROFILE}
        )
        if role == "executive":
            if parent_session_id is not None:
                raise PrimeRuntimeError("Prime executive sessions cannot have a parent")
            logical_parent_id = None
        else:
            if role not in ALLOWED_DELEGATION_ROLES or parent_session_id is None:
                raise PrimeRuntimeError("Prime specialist session is not allowed")
            logical_parent_id = require_public_identifier(parent_session_id)
            parent = self._sessions.get(logical_parent_id)
            if (
                parent is None
                or parent.info.role_name != "executive"
                or parent.info.parent_session_id is not None
                or parent.info.status != "active"
            ):
                raise PrimeRuntimeError("Prime specialist parent is unavailable")
        if not self._env.get("OPENROUTER_API_KEY"):
            raise PrimeUnavailableError("OpenRouter is not configured for Prime RPC")
        if not self._custom_transport and not self._binary_available():
            raise PrimeUnavailableError("Prime RPC binary is unavailable")
        if (
            bounded_profile
            and self.cwd is not None
            and len(self.cwd.encode("utf-8"))
            > DEFAULT_BOUNDED_TEST_POLICY.max_bounded_workdir_utf8_bytes
        ):
            raise PrimeRuntimeError("Bounded Prime workdir exceeds its safe size limit")

        argv = [
            self.executable,
            "--mode",
            "rpc",
            "--provider",
            "openrouter",
            "--model",
            (
                _BOUNDED_PRIME_CLI_MODEL
                if bounded_profile
                else OPENROUTER_AUTOROUTER_MODEL
            ),
            "--no-session",
            "--no-tools",
        ]
        runtime_config: tempfile.TemporaryDirectory[str] | None = None
        session_env = dict(self._env)
        client = PrimeRpcClient(
            self._factory(),
            command_timeout_seconds=self._command_timeout,
            turn_timeout_seconds=self._turn_timeout,
            reject_compaction=bounded_profile,
            capture_generation_headers=bounded_profile,
        )
        try:
            if bounded_profile:
                runtime_config = tempfile.TemporaryDirectory(
                    prefix="orch71-bounded-prime-",
                    dir=self.cwd,
                )
                runtime_path = Path(runtime_config.name)
                if not self._custom_transport or Path(self.executable).is_file():
                    argv[0] = await _prepare_bounded_prime_executable_async(
                        self.executable,
                        runtime_path,
                        search_path=session_env.get("PATH"),
                    )
                config_path = runtime_path / "models.json"
                config_path.write_text(
                    json.dumps(
                        _BOUNDED_MODEL_OVERRIDES,
                        ensure_ascii=True,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
                extension_path = runtime_path / "generation-receipt.js"
                extension_path.write_text(
                    _BOUNDED_GENERATION_EXTENSION,
                    encoding="utf-8",
                )
                session_env["PRIME_AGENT_CODING_AGENT_DIR"] = runtime_config.name
                argv.extend(
                    [
                        "--thinking",
                        "off",
                        "--system-prompt",
                        _BOUNDED_SYSTEM_PROMPT,
                        "--extension",
                        str(extension_path),
                        "--no-extensions",
                        "--no-skills",
                        "--no-prompt-templates",
                        "--no-context-files",
                    ]
                )
            await client.start(argv=tuple(argv), env=session_env, cwd=self.cwd)
            state_response = await client.request("get_state")
            # A successful get_state confirms the documented command boundary.
            # Never expose Prime's sessionId/sessionFile from its raw state.
            state = state_response.get("data")
            if not isinstance(state, dict):
                raise PrimeRuntimeError("Prime RPC returned invalid state")
            if bounded_profile:
                _require_bounded_prime_state(state)
            # Raw vendor state may include session or filesystem identifiers.
            # Discard it before any bounded control or public session creation.
            state = None
            state_response = None
            if bounded_profile:
                await client.request("set_auto_retry", enabled=False)
                await client.request("set_auto_compaction", enabled=False)
            session_id = str(uuid.uuid4())
            info = PrimeSessionInfo(
                session_id=session_id,
                role_name=role,
                parent_session_id=logical_parent_id,
                model=OPENROUTER_AUTOROUTER_MODEL,
                metadata={
                    "expected_protocol_version": PRIME_AGENT_VERSION,
                    "expected_protocol_commit": PRIME_AGENT_COMMIT,
                    "version_verified": False,
                    "provider": "openrouter",
                    "tools_enabled": False,
                    "context": (
                        sanitize_public_metadata(metadata or {})
                        if logical_parent_id is None
                        else {}
                    ),
                },
                status="active",
            )
            self._sessions[session_id] = _LivePrimeSession(
                info=info,
                client=client,
                telemetry_required=bounded_profile,
                runtime_config=runtime_config,
            )
            return info
        except BaseException as exc:
            self._last_error = type(exc).__name__
            cleanup_error: BaseException | None = None
            try:
                await self._close_client_bounded(client)
            except BaseException as close_exc:
                cleanup_error = close_exc
            finally:
                if runtime_config is not None:
                    try:
                        runtime_config.cleanup()
                    except OSError as config_exc:
                        cleanup_error = cleanup_error or config_exc
            if isinstance(exc, asyncio.CancelledError):
                raise
            if isinstance(exc, PrimeRuntimeError):
                raise
            if not isinstance(exc, Exception):
                raise
            if cleanup_error is not None:
                raise PrimeRuntimeError("Prime RPC session cleanup failed") from exc
            raise PrimeRuntimeError("Prime RPC session could not start") from exc

    async def send_message(
        self, session_id: str, *, message: str
    ) -> PrimeMessageResult:
        live = self._sessions.get(session_id)
        if live is None:
            raise PrimeUnavailableError("Prime RPC session is unavailable")
        safe_input = sanitize_private_input(message, maximum=20_000)
        diagnostic: PrimeTelemetryDiagnostic | None = None
        try:
            async with live.turn_lock:
                raw_text, receipt = await live.client.prompt_and_wait(safe_input)
                if live.telemetry_required:
                    diagnostic = live.client.last_telemetry_diagnostic
                generation = None
                if live.telemetry_required:
                    if (
                        not isinstance(receipt, GenerationTelemetry)
                        or receipt.source != "openrouter_stream"
                    ):
                        self._last_error = (
                            diagnostic or "telemetry_adapter_correlation_failed"
                        )
                    else:
                        generation = receipt
                        self._last_error = (
                            None
                            if diagnostic == "telemetry_adapter_correlated"
                            else diagnostic
                        )
        except asyncio.CancelledError:
            self._last_error = (
                live.client.last_telemetry_diagnostic
                if live.telemetry_required
                else None
            ) or "CancelledError"
            try:
                await self.stop_session(session_id, reason="turn_cancelled")
            except Exception:  # noqa: BLE001 - cancellation still propagates
                pass
            raise
        except Exception as exc:
            self._last_error = (
                live.client.last_telemetry_diagnostic
                if live.telemetry_required
                else None
            ) or type(exc).__name__
            if isinstance(exc, PrimeRuntimeError):
                raise
            raise PrimeRuntimeError("Prime RPC turn failed") from exc
        public_text, filtered = sanitize_public_text(raw_text)
        return PrimeMessageResult(
            message_id=str(uuid.uuid4()),
            session_id=session_id,
            text=public_text,
            safety_filtered=filtered,
            generation=generation,
            telemetry_diagnostic=diagnostic,
        )

    async def _close_client_bounded(
        self,
        client: PrimeRpcClient,
        *,
        timeout_seconds: float | None = None,
    ) -> None:
        task = asyncio.create_task(client.close())
        try:
            await asyncio.wait_for(
                asyncio.shield(task),
                timeout=(
                    self._cleanup_timeout
                    if timeout_seconds is None
                    else max(0.05, timeout_seconds)
                ),
            )
        except asyncio.TimeoutError as exc:
            task.cancel()
            try:
                await task
            except BaseException:
                pass
            raise PrimeRuntimeError("Prime RPC cleanup timed out") from exc

    async def stop_session(self, session_id: str, *, reason: str = "stopped") -> None:
        del reason
        live = self._sessions.get(session_id)
        if live is None:
            return
        live.info.status = "stopping"
        deadline = asyncio.get_running_loop().time() + self._cleanup_timeout
        cancellation: asyncio.CancelledError | None = None
        close_error: Exception | None = None
        transport_closed = False
        try:
            await asyncio.wait_for(
                live.client.request("abort"),
                timeout=min(1.0, max(0.05, self._cleanup_timeout / 4)),
            )
        except asyncio.CancelledError as exc:
            cancellation = exc
        except (PrimeRuntimeError, asyncio.TimeoutError):
            pass
        try:
            remaining = max(0.05, deadline - asyncio.get_running_loop().time())
            await self._close_client_bounded(
                live.client,
                timeout_seconds=remaining,
            )
            transport_closed = True
        except asyncio.CancelledError as exc:
            cancellation = cancellation or exc
        except Exception as exc:  # noqa: BLE001 - preserve safe adapter error only
            close_error = exc
        if transport_closed and close_error is None:
            self._sessions.pop(session_id, None)
            if live.runtime_config is not None:
                try:
                    live.runtime_config.cleanup()
                except OSError:
                    close_error = close_error or PrimeRuntimeError(
                        "Prime RPC runtime cleanup failed"
                    )
        if cancellation is not None:
            live.info.status = "failed"
            raise cancellation
        if close_error is not None and session_id not in self._sessions:
            # Config cleanup failed after transport shutdown; no live process remains.
            live.info.status = "failed"
            raise close_error
        if close_error is not None:
            live.info.status = "failed"
            if isinstance(close_error, PrimeRuntimeError):
                raise close_error
            raise PrimeRuntimeError("Prime RPC session could not stop") from close_error
        live.info.status = "stopped"

    async def list_sessions(self) -> list[PrimeSessionInfo]:
        return [live.info for live in self._sessions.values()]

    async def close(self) -> None:
        failed = False
        for session_id in list(self._sessions):
            try:
                await self.stop_session(session_id, reason="runtime_shutdown")
            except Exception:  # noqa: BLE001 - attempt every remaining process
                failed = True
        if failed:
            raise PrimeRuntimeError("One or more Prime RPC sessions could not close")


def _validated_executable(value: Any) -> str | None:
    text = str(value or "prime-agent").strip()
    if (
        not text
        or len(text) > 1_024
        or text.startswith("-")
        or any(char in text for char in ("\x00", "\r", "\n"))
    ):
        return None
    return text


def _validated_isolated_workdir(value: Any) -> str | None:
    text = str(value or "").strip()
    if (
        not text
        or len(text) > 1_024
        or any(char in text for char in ("\x00", "\r", "\n"))
    ):
        return None
    path = Path(text)
    if not path.is_absolute():
        return None
    try:
        resolved = path.resolve(strict=True)
        inherited = Path.cwd().resolve(strict=True)
    except OSError:
        return None
    if (
        not resolved.is_dir()
        or resolved == inherited
        or inherited in resolved.parents
        or resolved in inherited.parents
    ):
        return None
    return str(resolved)


def build_prime_agent_from_environment(
    source: Mapping[str, str] | None = None,
) -> NullPrimeAgent | PrimeJsonlRpcAgent:
    """Opt-in live adapter factory; Null remains the production default."""

    env_source = source if source is not None else os.environ
    enabled = str(env_source.get("PRIME_AGENT_ENABLED", "")).strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return NullPrimeAgent()
    executable = _validated_executable(env_source.get("PRIME_AGENT_BIN"))
    workdir = _validated_isolated_workdir(env_source.get("PRIME_AGENT_WORKDIR"))
    if executable is None or workdir is None:
        disabled = NullPrimeAgent()
        disabled.mark_error("Prime RPC isolated runtime configuration is invalid")
        return disabled
    return PrimeJsonlRpcAgent(
        executable=executable,
        cwd=workdir,
        environment=env_source,
    )
