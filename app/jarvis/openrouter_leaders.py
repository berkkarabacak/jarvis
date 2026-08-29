"""Live OpenRouter catalog for Jarvis routing (ORCH-362).

The weekly board is a CATALOG of current models Jarvis may use — not a
ranking of "always pick #1 by tokens" and not "always pick free."
Prefers GET /api/v1/datasets/rankings-daily?period=week at route time.
A slug is accepted only when it appears in GET /api/v1/models — never
invented. If the live fetch fails, fall back to the 2026-08-14
"This Week" snapshot (those slugs were resolved from the same catalog).
"""

from __future__ import annotations

from app.llm.openrouter_attribution import openrouter_attribution_headers

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_RANKINGS_URL = "https://openrouter.ai/api/v1/datasets/rankings-daily"

SNAPSHOT_AS_OF = "2026-08-21"
SNAPSHOT_WINDOW = "this_week"
DEFAULT_TTL_SEC = 15 * 60
DEFAULT_TIMEOUT_SEC = 3.0
DEFAULT_TOP_N = 20

# OpenRouter "This Week" most-used, resolved against GET /api/v1/models on
# 2026-08-21. Token order from the public weekly board. Do not invent slugs
# (e.g. Flash 0423 is deepseek/deepseek-v4-flash).
# deepseek/deepseek-v4-pro and deepseek/deepseek-v4-pro-0813 are different
# live ids — not aliases. GLM 5.3 is not on OpenRouter — do not add z-ai/glm-5.3.
# If a later live fetch returns fewer than 20 catalog ids, pad from these
# known rows only.
SNAPSHOT_LEADERS: tuple[tuple[str, int, float, float, str], ...] = (
    ("deepseek/deepseek-v4-flash-0731", 1, 0.00000008, 0.00000018, "DeepSeek V4 Flash 0731"),
    ("tencent/hy3", 2, 0.000000132, 0.000000528, "Hy3"),
    ("xiaomi/mimo-v2.5", 3, 0.00000014, 0.00000028, "MiMo-V2.5"),
    ("openai/gpt-5.6-luna", 4, 0.0000002, 0.0000012, "GPT-5.6 Luna"),
    ("deepseek/deepseek-v4-flash", 5, 0.00000006006, 0.00000012012, "DeepSeek V4 Flash 0423"),
    ("nvidia/nemotron-3-ultra-550b-a55b:free", 6, 0.0, 0.0, "Nemotron 3 Ultra free"),
    ("z-ai/glm-5.2", 7, 0.000000966, 0.000003036, "GLM 5.2"),
    ("anthropic/claude-opus-5", 8, 0.000005, 0.000025, "Claude Opus 5"),
    ("stealth/ox-alpha", 9, 0.0, 0.0, "Ox Alpha"),
    ("deepseek/deepseek-v4-pro", 10, 0.000000413772, 0.000000827544, "DeepSeek V4 Pro 0423"),
    ("minimax/minimax-m3", 11, 0.0000003, 0.0000012, "MiniMax M3"),
    ("poolside/laguna-s-2.1:free", 12, 0.0, 0.0, "Laguna S 2.1 free"),
    ("google/gemini-3.6-flash", 13, 0.00000075, 0.00000375, "Gemini 3.6 Flash"),
    ("google/gemini-3.7-flash", 14, 0.000000375, 0.000001875, "Gemini 3.7 Flash"),
    ("moonshotai/kimi-k3", 15, 0.000003, 0.000015, "Kimi K3"),
    ("openai/gpt-5.6-sol", 16, 0.000002, 0.00001, "GPT-5.6 Sol"),
    ("deepseek/deepseek-v4-pro-0813", 17, 0.000001188, 0.000003564, "DeepSeek V4 Pro 0813"),
    ("anthropic/claude-sonnet-5", 18, 0.000002, 0.00001, "Claude Sonnet 5"),
    ("nvidia/nemotron-3.5-lightning:free", 19, 0.0, 0.0, "Nemotron 3.5 Lightning free"),
    ("google/gemini-3-flash-preview", 20, 0.0000005, 0.000003, "Gemini 3 Flash Preview"),
)

SNAPSHOT_MODEL_IDS: tuple[str, ...] = tuple(row[0] for row in SNAPSHOT_LEADERS)
_REALTIME_VOICE_MARKERS = ("gpt-realtime", "gpt-4o-realtime")

# Name/id fragments only — never invented slugs. Speed SKUs are cheap;
# paid non-speed (and explicit IQ markers) are the high-IQ catalog pool.
_SPEED_MARKERS = ("flash", "mini", "nano", "lite", "small", "haiku", "instant")
_STRONG_IQ_MARKERS = ("pro", "opus", "max", "reasoning", "thinking")
_IQ_MARKERS = ("luna", "sonnet", "ultra")

JsonGetter = Callable[[str, dict[str, str], float], dict[str, Any]]


@dataclass(frozen=True)
class LeaderModel:
    model: str
    rank: int
    prompt_price: float | None
    completion_price: float | None
    name: str = ""

    @property
    def is_free(self) -> bool:
        if self.model.endswith(":free"):
            return True
        if self.prompt_price is None or self.completion_price is None:
            return False
        return self.prompt_price == 0.0 and self.completion_price == 0.0

    @property
    def unit_price(self) -> float:
        if self.prompt_price is None or self.completion_price is None:
            return float("inf")
        return float(self.prompt_price) + float(self.completion_price)

    @property
    def _label(self) -> str:
        return f"{self.model} {self.name}".lower()

    @property
    def is_speed_sku(self) -> bool:
        return any(marker in self._label for marker in _SPEED_MARKERS)

    @property
    def is_high_iq(self) -> bool:
        """Paid catalog model that is not a cheap speed SKU.

        Free / :free tips are never high-IQ. Flash/mini/etc. stay in the
        cheap pool. Usage rank is ignored.
        """
        if self.is_free:
            return False
        if self.is_speed_sku:
            return False
        return True

    @property
    def iq_tier(self) -> int:
        """Lower is smarter. Markers + price; never weekly usage rank."""
        if not self.is_high_iq:
            return 9
        blob = self._label
        if any(marker in blob for marker in _STRONG_IQ_MARKERS):
            return 0
        if any(marker in blob for marker in _IQ_MARKERS):
            return 1
        return 2


@dataclass(frozen=True)
class LeadersResult:
    models: tuple[LeaderModel, ...]
    source: str  # "live" | "snapshot"
    as_of: str
    window: str = SNAPSHOT_WINDOW
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(m.model for m in self.models)


_lock = threading.Lock()
_cache: tuple[float, LeadersResult] | None = None


def _truthy(val: str | None) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


def live_fetch_enabled() -> bool:
    raw = os.environ.get("JARVIS_LEADERBOARD_LIVE")
    if raw is None or raw == "":
        return True
    return _truthy(raw)


def reset_leaders_cache_for_tests() -> None:
    global _cache
    with _lock:
        _cache = None


def snapshot_leaders() -> tuple[LeaderModel, ...]:
    return tuple(
        LeaderModel(
            model=mid,
            rank=rank,
            prompt_price=prompt,
            completion_price=completion,
            name=name,
        )
        for mid, rank, prompt, completion, name in SNAPSHOT_LEADERS
    )


def snapshot_result(*, error: str | None = None) -> LeadersResult:
    return LeadersResult(
        models=snapshot_leaders(),
        source="snapshot",
        as_of=SNAPSHOT_AS_OF,
        window=SNAPSHOT_WINDOW,
        error=error,
        metadata={"captured": SNAPSHOT_AS_OF, "window": SNAPSHOT_WINDOW},
    )


def is_realtime_voice_model(model_id: str) -> bool:
    """OpenAI Realtime voice SKUs — never offered as OpenRouter helpers."""
    blob = (model_id or "").strip().lower()
    return any(marker in blob for marker in _REALTIME_VOICE_MARKERS)


def plain_helper_name(name: str, model_id: str) -> str:
    """Human label: 'DeepSeek V4 Flash 0731', not 'deepseek/deepseek-v4-flash-0731'."""
    n = (name or "").strip()
    if ": " in n:
        rest = n.split(": ", 1)[1].strip()
        if rest:
            n = rest
    if n.lower().endswith(" (free)"):
        n = n[: -len(" (free)")].strip() + " free"
    if n:
        return n
    mid = (model_id or "").strip()
    return mid.split("/")[-1] if mid else ""


def pad_with_snapshot(
    models: tuple[LeaderModel, ...] | list[LeaderModel],
    *,
    top_n: int = DEFAULT_TOP_N,
) -> tuple[LeaderModel, ...]:
    """Keep live rows, then known SNAPSHOT_LEADERS only. Never invent slugs."""
    out: list[LeaderModel] = []
    seen: set[str] = set()
    for m in models:
        if not m.model or m.model in seen or is_realtime_voice_model(m.model):
            continue
        seen.add(m.model)
        out.append(m)
        if len(out) >= top_n:
            return tuple(out)
    for m in snapshot_leaders():
        if m.model in seen or is_realtime_voice_model(m.model):
            continue
        seen.add(m.model)
        out.append(
            LeaderModel(
                model=m.model,
                rank=len(out) + 1,
                prompt_price=m.prompt_price,
                completion_price=m.completion_price,
                name=m.name,
            )
        )
        if len(out) >= top_n:
            break
    return tuple(out)


def helper_models_public(result: LeadersResult | None = None) -> list[dict[str, Any]]:
    """id + plain name + rank for Talk / health. No keys, no prices."""
    board = result if result is not None else load_leaders()
    models = pad_with_snapshot(board.models)
    out: list[dict[str, Any]] = []
    for m in models[:DEFAULT_TOP_N]:
        if is_realtime_voice_model(m.model):
            continue
        out.append(
            {
                "id": m.model,
                "name": plain_helper_name(m.name, m.model),
                "rank": int(m.rank),
            }
        )
    return out


def known_helper_ids() -> set[str]:
    ids = set(SNAPSHOT_MODEL_IDS)
    try:
        ids.update(load_leaders().ids)
    except Exception:
        pass
    return {mid for mid in ids if mid and not is_realtime_voice_model(mid)}


def is_allowed_helper_model(model_id: str) -> bool:
    mid = (model_id or "").strip()
    if not mid or is_realtime_voice_model(mid) or "auto" in mid.lower():
        return False
    return mid in known_helper_ids()


def _dedupe_ids(models: list[LeaderModel]) -> list[str]:
    out: list[str] = []
    for m in models:
        if m.model and m.model not in out and "auto" not in m.model.lower():
            out.append(m.model)
    return out


def cost_sorted_model_ids(models: tuple[LeaderModel, ...] | list[LeaderModel]) -> list[str]:
    """Cheap catalog order for light / child jobs.

    One free tip (allowed only for actually-light work), then paid by
    price, then leftover free. This is not "pick #1 by tokens."
    """
    return cheap_catalog_ids(models, allow_free=True)


def cheap_catalog_ids(
    models: tuple[LeaderModel, ...] | list[LeaderModel],
    *,
    allow_free: bool = True,
) -> list[str]:
    """Cheap capable models from the current board. Price, not usage rank.

    Free is included only when ``allow_free`` is true (light jobs / children).
    Routine builds should pass ``allow_free=False`` so the first pick is a
    cheap paid model when one exists.
    """
    free = [m for m in models if m.is_free]
    paid = [m for m in models if not m.is_free]
    free.sort(key=lambda m: (m.model,))
    paid.sort(key=lambda m: (m.unit_price, m.rank, m.model))
    if allow_free:
        ordered = ([free[0]] if free else []) + paid + free[1:]
    else:
        ordered = paid + free
    return _dedupe_ids(ordered)


def smart_catalog_ids(models: tuple[LeaderModel, ...] | list[LeaderModel]) -> list[str]:
    """High-IQ paid catalog models, strongest first.

    Usage rank is ignored. Free / flash tips are not first-class here.
    If the board has no paid non-speed model, fall back to any paid
    model rather than inventing a slug.
    """
    high = [m for m in models if m.is_high_iq]
    if not high:
        high = [m for m in models if not m.is_free]
    if not high:
        high = list(models)
    high.sort(
        key=lambda m: (
            m.iq_tier,
            -(m.unit_price if m.unit_price != float("inf") else 0.0),
            m.model,
        )
    )
    return _dedupe_ids(high)


def _http_get_json(url: str, headers: dict[str, str], timeout: float) -> dict[str, Any]:
    import httpx

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url, headers=headers)
    if resp.status_code >= 400:
        raise RuntimeError(f"OpenRouter HTTP {resp.status_code} for {url.split('?', 1)[0]}")
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError("OpenRouter response was not an object")
    return data


def _parse_price(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    if val != val or val in {float("inf"), float("-inf")}:
        return None
    return val


def parse_models_catalog(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map callable OpenRouter id → catalog row. Skip :batch variants."""
    by_id: dict[str, dict[str, Any]] = {}
    for item in payload.get("data") or []:
        if not isinstance(item, dict):
            continue
        mid = item.get("id")
        if not isinstance(mid, str) or not mid.strip():
            continue
        mid = mid.strip()
        if ":batch" in mid or mid == "other":
            continue
        by_id[mid] = item
    return by_id


def _canonical_index(by_id: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for mid, item in by_id.items():
        canon = item.get("canonical_slug")
        if isinstance(canon, str) and canon.strip():
            index.setdefault(canon.strip(), []).append(mid)
    return index


def resolve_ranked_slug(slug: str, by_id: dict[str, dict[str, Any]]) -> str | None:
    """Map a rankings permaslug to a callable /models id. None if unknown."""
    raw = (slug or "").strip()
    if not raw or raw == "other" or ":batch" in raw:
        return None
    if raw in by_id:
        return raw
    by_canon = _canonical_index(by_id)
    if raw in by_canon:
        ids = by_canon[raw]
        for mid in ids:
            if ":" not in mid:
                return mid
        return ids[0]
    if ":" in raw:
        base, variant = raw.rsplit(":", 1)
        if variant == "batch":
            return None
        for mid in by_canon.get(base, []):
            if mid.endswith(f":{variant}"):
                return mid
        suffixed = f"{base}:{variant}"
        if suffixed in by_id:
            return suffixed
    return None


def _supports_tools(item: dict[str, Any]) -> bool:
    params = item.get("supported_parameters")
    if not isinstance(params, list) or not params:
        return True
    return "tools" in params


def _leader_from_catalog(
    mid: str,
    rank: int,
    item: dict[str, Any] | None,
    *,
    fallback: LeaderModel | None = None,
) -> LeaderModel:
    pricing = (item or {}).get("pricing") if isinstance(item, dict) else None
    if not isinstance(pricing, dict):
        pricing = {}
    prompt = _parse_price(pricing.get("prompt"))
    completion = _parse_price(pricing.get("completion"))
    name = ""
    if isinstance(item, dict):
        name = str(item.get("name") or "").strip()
    if fallback is not None:
        if prompt is None:
            prompt = fallback.prompt_price
        if completion is None:
            completion = fallback.completion_price
        name = name or fallback.name
    return LeaderModel(
        model=mid,
        rank=rank,
        prompt_price=prompt,
        completion_price=completion,
        name=name,
    )


def parse_weekly_rankings(
    payload: dict[str, Any],
    catalog: dict[str, dict[str, Any]],
    *,
    top_n: int = DEFAULT_TOP_N,
) -> tuple[tuple[LeaderModel, ...], str]:
    """Latest week bucket → callable catalog ids only.

    Token sort is only how we decide *membership* of the current board.
    The router must not treat that order as "always pick #1."
    """
    rows = [r for r in (payload.get("data") or []) if isinstance(r, dict)]
    dated = [
        r
        for r in rows
        if r.get("date") and r.get("model_permaslug") not in {None, "", "other"}
    ]
    if not dated:
        return (), ""
    latest = max(str(r["date"]) for r in dated)
    week = [r for r in dated if str(r["date"]) == latest]
    def _tokens(row: dict[str, Any]) -> int:
        try:
            return int(str(row.get("total_tokens") or "0"))
        except (TypeError, ValueError):
            return 0

    week.sort(key=lambda r: (-_tokens(r), str(r.get("model_permaslug") or "")))
    out: list[LeaderModel] = []
    seen: set[str] = set()
    for row in week:
        mid = resolve_ranked_slug(str(row.get("model_permaslug") or ""), catalog)
        if not mid or mid in seen:
            continue
        item = catalog.get(mid) or {}
        if not _supports_tools(item):
            continue
        seen.add(mid)
        out.append(_leader_from_catalog(mid, len(out) + 1, item))
        if len(out) >= top_n:
            break
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    as_of = str(meta.get("as_of") or latest or "")
    return tuple(out), as_of


def fetch_live_leaders(
    *,
    getter: JsonGetter | None = None,
    api_key: str | None = None,
    timeout: float | None = None,
    top_n: int = DEFAULT_TOP_N,
) -> LeadersResult:
    """Hit OpenRouter models + weekly rankings. Raises on hard failure."""
    get = getter or _http_get_json
    timeout_s = float(
        timeout
        if timeout is not None
        else (os.environ.get("JARVIS_LEADERBOARD_TIMEOUT_SEC") or DEFAULT_TIMEOUT_SEC)
    )
    key = (api_key if api_key is not None else os.environ.get("OPENROUTER_API_KEY") or "").strip()
    headers = {
        "Accept": "application/json",
        **openrouter_attribution_headers(),
    }
    if key:
        headers["Authorization"] = f"Bearer {key}"

    catalog_payload = get(OPENROUTER_MODELS_URL, headers, timeout_s)
    catalog = parse_models_catalog(catalog_payload)
    if not catalog:
        raise RuntimeError("OpenRouter /models returned no usable ids")

    rank_headers = dict(headers)
    rank_url = f"{OPENROUTER_RANKINGS_URL}?period=week&modality=text"
    rank_payload = get(rank_url, rank_headers, timeout_s)
    models, as_of = parse_weekly_rankings(rank_payload, catalog, top_n=top_n)
    if not models:
        raise RuntimeError("OpenRouter weekly rankings mapped to no catalog ids")
    return LeadersResult(
        models=models,
        source="live",
        as_of=as_of or time.strftime("%Y-%m-%d"),
        window="week",
        metadata={"top_n": top_n, "catalog_size": len(catalog)},
    )


def _validate_snapshot_against_catalog(
    catalog: dict[str, dict[str, Any]],
) -> tuple[LeaderModel, ...]:
    snap = {m.model: m for m in snapshot_leaders()}
    out: list[LeaderModel] = []
    for mid, fallback in snap.items():
        if mid not in catalog:
            continue
        out.append(
            _leader_from_catalog(mid, fallback.rank, catalog[mid], fallback=fallback)
        )
    return tuple(out) if out else snapshot_leaders()


def load_leaders(
    *,
    getter: JsonGetter | None = None,
    api_key: str | None = None,
    force_refresh: bool = False,
) -> LeadersResult:
    """Live weekly board, else snapshot. Cached; never raises to the router."""
    global _cache
    ttl = float(os.environ.get("JARVIS_LEADERBOARD_TTL_SEC") or DEFAULT_TTL_SEC)
    now = time.time()
    if not force_refresh:
        with _lock:
            if _cache is not None:
                ts, cached = _cache
                if now - ts < ttl:
                    return cached

    result: LeadersResult
    if not live_fetch_enabled() and getter is None:
        result = snapshot_result(error="live_disabled")
    else:
        try:
            result = fetch_live_leaders(getter=getter, api_key=api_key)
        except Exception as exc:
            err = str(exc)[:240]
            catalog: dict[str, dict[str, Any]] = {}
            if getter is not None or live_fetch_enabled():
                try:
                    get = getter or _http_get_json
                    timeout_s = float(
                        os.environ.get("JARVIS_LEADERBOARD_TIMEOUT_SEC") or DEFAULT_TIMEOUT_SEC
                    )
                    key = (
                        api_key
                        if api_key is not None
                        else os.environ.get("OPENROUTER_API_KEY")
                        or ""
                    ).strip()
                    headers = {"Accept": "application/json"}
                    if key:
                        headers["Authorization"] = f"Bearer {key}"
                    catalog = parse_models_catalog(
                        get(OPENROUTER_MODELS_URL, headers, timeout_s)
                    )
                except Exception:
                    catalog = {}
            models = (
                _validate_snapshot_against_catalog(catalog) if catalog else snapshot_leaders()
            )
            result = LeadersResult(
                models=models,
                source="snapshot",
                as_of=SNAPSHOT_AS_OF,
                window=SNAPSHOT_WINDOW,
                error=err,
                metadata={"fallback": True, "catalog_validated": bool(catalog)},
            )

    with _lock:
        _cache = (time.time(), result)
    return result
