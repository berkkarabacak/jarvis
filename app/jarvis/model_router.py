"""Jarvis execution model router (ORCH-328 / ORCH-362).

Picks an OpenRouter model per task and a short reason. The weekly board
is a CATALOG of current models — not "always pick #1 by tokens" and not
"always pick free." Hard pins (explicit override, Settings model,
JARVIS_MODEL_PIN) always win.

Easy / cheap jobs: a cheap capable model from the current board (free is
OK only when the job is actually light). Hard / high-IQ jobs: a smarter
paid catalog model (e.g. DeepSeek V4 Pro, GPT-5.6 Luna, Hy3, GLM 5.2) as
the FIRST pick — not Nemotron/Laguna free, not the usage-rank #1 flash
tip. Fail-then-escalate still exists, but a hard task must not start on
a free model that will just fail.

Live board fetch + snapshot fallback stay. Last scorecard path is
persisted on the route state. Children still use the cheap ladder.
"""

from __future__ import annotations

from app.llm.openrouter_attribution import openrouter_attribution_headers

import json
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Sequence

import httpx

from app.jarvis.workspace import default_workspace

Preference = Literal["cheap_fast", "fast", "balanced", "quality"]
TaskClass = Literal["light", "routine_build", "hard"]
BudgetAction = Literal["ok", "cheaper", "stop"]

STATE_FILENAME = "jarvis_model_route.json"
BENCH_LATEST = Path("benchmarks") / "jarvis-tetris-latest.json"

# Tool-capable ladder (cheapest -> stronger). openrouter/auto omitted (weak tools).
# Verified OpenRouter /models ids only — not gpt-4.1. Cheap first, then
# paid high-IQ catalog models used when the live board is unavailable.
_CHEAP_FALLBACK = "deepseek/deepseek-v4-flash-0731"
_DEFAULT_LADDER: tuple[str, ...] = (
    _CHEAP_FALLBACK,
    "z-ai/glm-5.2",
    "deepseek/deepseek-v4-pro-0813",
)

_HARD_PATTERNS = tuple(
    re.compile(p, re.I)
    for p in (
        r"\b(refactor|multi-?file|codebase|architecture|migrate|migration)\b",
        r"\b\d+-file\b",
        r"\bsplit\b.+\binto\b.+\b(layers?|modules?|packages?)\b",
        r"\b(careful|detailed)\s+plan\b",
        r"\bwithout breaking\b",
        r"\b(design|implement)\b.+\b(system|service|framework|protocol)\b",
        r"\b(security|threat|red.?team|exploit)\b",
        r"\b(large|complex|production|messy)\b.+\b(app|system|rewrite)\b",
        r"\b(debug|root.?cause)\b.+\b(distributed|race|deadlock)\b",
        r"\blayers?\s*\(\s*api",
        r"\bfiles to touch\b",
    )
)

_BUILD_PATTERNS = tuple(
    re.compile(p, re.I)
    for p in (
        r"\b(build|create|write|make|scaffold)\b.+\b(html|tetris|excel|script|file|game|page|report)\b",
        r"\b(write_file|Exports/)",
        r"\bbench-tetris\b",
        r"\bsingle-?file\b",
    )
)

_LIGHT_PATTERNS = tuple(
    re.compile(p, re.I)
    for p in (
        r"\b(disk|free space|storage|ram|cpu|system info)\b",
        r"\b(open|launch)\b.+\b(notepad|calc|excel|chrome|browser)\b",
        r"\b(list|show)\b.+\b(files?|folders?|directory|desktop|downloads|documents)\b",
        r"\b(remember|recall)\b",
        r"\b(screenshot|what('s| is) on (my )?screen)\b",
        r"\bhow much\b",
    )
)

# Free talk / cheap-lift workers. Person speaks only to Jarvis; these two
# do the lifting. Kimi Code first (api.kimi.com — never moonshot.ai/.cn).
# OpenRouter Ox is the 429/5xx fallback. No User-Agent spoof. Kimi never
# gets max_tokens.
KIMI_CODE_URL = "https://api.kimi.com/coding/v1/chat/completions"
KIMI_CODE_MODEL = "kimi-for-coding-highspeed"
OX_MODEL = "stealth/ox-alpha"
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
_MOONSHOT_HOSTS = ("api.moonshot.ai", "api.moonshot.cn", "moonshot.ai", "moonshot.cn")
HELPER_DISPLAY_NAMES = frozenset({"Quick", "Kimi", "Ox"})

_lock = threading.RLock()


@dataclass(frozen=True)
class FreeWorker:
    """One free lifting worker. ``name`` is a friendly word, never a raw key."""

    key: str
    name: str
    model: str
    url: str


@dataclass
class ChatResult:
    text: str
    worker: FreeWorker | None = None
    data: dict[str, Any] = field(default_factory=dict)
    ok: bool = False
    status: int | None = None


def kimi_api_key() -> str:
    return (
        (os.environ.get("KIMI_CODE_API_KEY") or "").strip()
        or (os.environ.get("KIMI_API_KEY") or "").strip()
    )


def _openrouter_key() -> str:
    try:
        from app.jarvis.talk_auth import openrouter_api_key

        return openrouter_api_key()
    except Exception:
        return (os.environ.get("OPENROUTER_API_KEY") or "").strip()


def list_free_workers() -> list[FreeWorker]:
    """Available free workers in try order: Kimi, then Ox."""
    out: list[FreeWorker] = []
    if kimi_api_key():
        out.append(
            FreeWorker(
                key="kimi",
                name="Kimi",
                model=KIMI_CODE_MODEL,
                url=KIMI_CODE_URL,
            )
        )
    if _openrouter_key():
        out.append(
            FreeWorker(
                key="ox",
                name="Ox",
                model=OX_MODEL,
                url=OPENROUTER_CHAT_URL,
            )
        )
    return out


def pick_free_worker() -> FreeWorker | None:
    """First free worker. Kimi if its env is set, else Ox, else None."""
    workers = list_free_workers()
    return workers[0] if workers else None


def helper_display_name(worker: FreeWorker | None = None) -> str | None:
    """Friendly word for Settings / health: Quick, Kimi, or Ox. Never a key."""
    chosen = worker if worker is not None else pick_free_worker()
    if chosen is None:
        return None
    workers = list_free_workers()
    if len(workers) >= 2:
        return "Quick"
    return chosen.name if chosen.name in HELPER_DISPLAY_NAMES else "Quick"


def _assert_not_moonshot(url: str) -> None:
    low = (url or "").lower()
    if any(host in low for host in _MOONSHOT_HOSTS):
        raise ValueError("Kimi Code uses api.kimi.com, not moonshot")


def _worker_headers(worker: FreeWorker) -> dict[str, str]:
    if worker.key == "kimi":
        return {
            "Authorization": f"Bearer {kimi_api_key()}",
            "Content-Type": "application/json",
        }
    return {
        "Authorization": f"Bearer {_openrouter_key()}",
        "Content-Type": "application/json",
        **openrouter_attribution_headers(),
    }


def _worker_payload(
    worker: FreeWorker,
    messages: Sequence[dict[str, Any]],
    *,
    temperature: float,
    extra: dict[str, Any] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": worker.model,
        "messages": list(messages),
        "temperature": temperature,
    }
    if extra:
        payload.update(extra)
    if worker.key == "kimi":
        payload.pop("max_tokens", None)
    elif worker.key == "ox":
        payload.setdefault("reasoning", {"effort": "low", "exclude": True})
        payload.setdefault("usage", {"include": True})
    return payload


def _message_content(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, list):
        bits: list[str] = []
        for part in raw:
            if isinstance(part, str) and part.strip():
                bits.append(part.strip())
            elif isinstance(part, dict):
                piece = part.get("text") or part.get("content") or ""
                if str(piece).strip():
                    bits.append(str(piece).strip())
        return " ".join(bits).strip()
    return str(raw).strip()


def _choice_text(data: dict[str, Any]) -> str:
    """Spoken content. Ox with reasoning.exclude should fill content; never a key."""
    try:
        msg = ((data.get("choices") or [{}])[0].get("message") or {})
    except (AttributeError, IndexError, TypeError):
        return ""
    if not isinstance(msg, dict):
        return ""
    text = _message_content(msg.get("content"))
    if text:
        return text
    # Content empty: do not dump reasoning JSON. One short string only.
    return _message_content(msg.get("reasoning") or data.get("reasoning"))


def _should_fallback(status: int | None) -> bool:
    if status is None:
        return True
    return status == 429 or status >= 500


async def chat(
    messages: Sequence[dict[str, Any]],
    *,
    timeout: float = 8.0,
    temperature: float = 0.3,
    extra: dict[str, Any] | None = None,
    client_factory: Any | None = None,
) -> ChatResult:
    """Cheap no-tool chat through pick_free_worker. 429/5xx → next worker."""
    workers = list_free_workers()
    last = ChatResult(text="", ok=False)
    factory = client_factory or (lambda timeout=timeout: httpx.AsyncClient(timeout=timeout))
    for worker in workers:
        _assert_not_moonshot(worker.url)
        payload = _worker_payload(
            worker, messages, temperature=temperature, extra=extra
        )
        headers = _worker_headers(worker)
        try:
            async with factory(timeout) as client:
                resp = await client.post(worker.url, headers=headers, json=payload)
            status = int(getattr(resp, "status_code", 0) or 0)
            if status >= 400:
                last = ChatResult(
                    text="", worker=worker, data={}, ok=False, status=status
                )
                if _should_fallback(status):
                    continue
                return last
            data = resp.json()
        except Exception:
            last = ChatResult(text="", worker=worker, data={}, ok=False, status=None)
            continue
        if not isinstance(data, dict):
            last = ChatResult(text="", worker=worker, data={}, ok=False, status=status)
            if _should_fallback(status):
                continue
            return last
        text = _choice_text(data)
        return ChatResult(
            text=text, worker=worker, data=data, ok=True, status=status
        )
    return last


@dataclass
class ModelRouteChoice:
    model: str
    reason: str
    task_class: TaskClass
    preference: Preference
    pinned: bool = False
    escalate: bool = False
    budget_action: BudgetAction = "ok"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def state_path(root: Path | None = None) -> Path:
    base = (root or default_workspace()).resolve()
    return base / "Memory" / STATE_FILENAME


def _truthy(val: str | None) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def load_state(root: Path | None = None) -> dict[str, Any]:
    with _lock:
        return _read_json(state_path(root))


def record_outcome(
    *,
    model: str,
    reason: str,
    task_class: TaskClass,
    ok: bool,
    root: Path | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist last choice + light failure counts for fail-then-escalate."""
    path = state_path(root)
    with _lock:
        cur = _read_json(path)
        failures = cur.get("failures_by_class")
        if not isinstance(failures, dict):
            failures = {}
        key = str(task_class)
        n = int(failures.get(key) or 0)
        if ok:
            n = 0
        else:
            n = min(5, n + 1)
        failures[key] = n
        cur["failures_by_class"] = failures
        cur["last"] = {
            "model": model,
            "reason": reason[:240],
            "task_class": task_class,
            "ok": bool(ok),
            "ts": time.time(),
            **(extra or {}),
        }
        _write_json(path, cur)
        return dict(cur)


def reset_state_for_tests(root: Path | None = None) -> None:
    path = state_path(root)
    with _lock:
        if path.is_file():
            try:
                path.unlink()
            except OSError:
                pass


def cheap_default_model() -> str:
    """Env hint for the cheap rung (not a hard pin by itself)."""
    return (
        os.environ.get("JARVIS_MODEL")
        or os.environ.get("DEFAULT_MODEL")
        or _CHEAP_FALLBACK
    ).strip() or _CHEAP_FALLBACK


def _resolve_data_path(rel: Path, repo_root: Path | None = None) -> Path:
    root = repo_root or Path.cwd()
    path = root / rel
    if path.is_file():
        return path
    alt = Path(__file__).resolve().parents[2] / rel
    return alt if alt.is_file() else path


def remember_scorecard_path(
    *,
    repo_root: Path | None = None,
    workspace_root: Path | None = None,
) -> str | None:
    """Persist the scorecard file the router last read (ORCH-334)."""
    from app.jarvis.cost_index import resolve_index_path

    path = resolve_index_path(repo_root)
    if not path.is_file():
        return None
    resolved = str(path.resolve())
    with _lock:
        cur = _read_json(state_path(workspace_root))
        cur["last_scorecard_path"] = resolved
        cur["last_scorecard_ts"] = time.time()
        _write_json(state_path(workspace_root), cur)
    return resolved


def load_bench_preferred_cheap(repo_root: Path | None = None) -> str | None:
    """Prefer scorecard JSON; else Tetris JSON.

    Scorecard cheap = lowest $ per success among models with pass@1 at
    least as good as the current cheap, else best pass@1 then cheapest.
    Unknown / non-positive cost is not treated as free.
    """
    from app.jarvis.cost_index import load_index_preferred_cheap

    indexed = load_index_preferred_cheap(
        repo_root, current_cheap=cheap_default_model()
    )
    if indexed:
        return indexed
    path = _resolve_data_path(BENCH_LATEST, repo_root)
    data = _read_json(path)
    results = data.get("results")
    if not isinstance(results, list):
        return None
    best: tuple[float, str] | None = None
    for row in results:
        if not isinstance(row, dict):
            continue
        if not row.get("ok"):
            continue
        if row.get("cost_unknown") is True:
            continue
        model = str(row.get("model") or "").strip()
        if not model or "auto" in model.lower():
            continue
        cost = row.get("cost_usd")
        try:
            c = float(cost) if cost is not None else None
        except (TypeError, ValueError):
            c = None
        if c is None or c <= 0:
            continue
        if best is None or c < best[0]:
            best = (c, model)
    return best[1] if best else None


_SCREEN_CONTROL_TOOLS = re.compile(r"\b(see_screen|focus_app|click|keys)\b", re.I)
_SCREEN_CONTROL_TARGET = re.compile(r"(https?://|\.com\b|\bchrome\b|\bntv\b)", re.I)


def _is_screen_control_job(goal: str) -> bool:
    """ORCH-373: chrome/URL + see_screen/focus_app/click is not a light job."""
    return bool(_SCREEN_CONTROL_TOOLS.search(goal) and _SCREEN_CONTROL_TARGET.search(goal))


def classify_task(goal: str) -> TaskClass:
    g = (goal or "").strip()
    if not g:
        return "light"
    for pat in _HARD_PATTERNS:
        if pat.search(g):
            return "hard"
    # ORCH-373: before light patterns — Open Chrome + see_screen a site is routine.
    if _is_screen_control_job(g):
        return "routine_build"
    for pat in _LIGHT_PATTERNS:
        if pat.search(g):
            return "light"
    for pat in _BUILD_PATTERNS:
        if pat.search(g):
            return "routine_build"
    # long goals without light markers → treat as harder
    if len(g) > 900:
        return "hard"
    if len(g) > 280:
        return "routine_build"
    return "light"


def _normalize_preference(raw: str | None) -> Preference:
    p = (raw or os.environ.get("JARVIS_MODEL_PREFERENCE") or "cheap_fast").strip().lower()
    if p in {"quality", "premium", "max", "high", "smart", "hard"}:
        return "quality"
    if p in {"balanced", "default", "medium", "normal"}:
        return "balanced"
    if p in {"fast", "cheap"}:
        return "fast"
    return "cheap_fast"


def _leaders_for_route() -> Any:
    from app.jarvis.openrouter_leaders import load_leaders

    return load_leaders()


def _merge_ladder(*groups: list[str] | tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for group in groups:
        for m in group:
            if m and m not in out and "auto" not in m.lower():
                out.append(m)
    return out or [_CHEAP_FALLBACK]


def _ladder(repo_root: Path | None = None) -> list[str]:
    """Cheap catalog ladder for children and actually-light jobs.

    Free board tips are allowed here. Parent hard tasks must not use this
    as the first-pick pool.
    """
    from app.jarvis.cost_index import load_index_model_order
    from app.jarvis.openrouter_leaders import cheap_catalog_ids

    current = cheap_default_model()
    scored = load_index_model_order(repo_root, current_cheap=current)
    board = _leaders_for_route()
    leaders = cheap_catalog_ids(board.models, allow_free=True)
    cheap = load_bench_preferred_cheap(repo_root) or (leaders[0] if leaders else current)
    if "auto" in cheap.lower():
        cheap = leaders[0] if leaders else _CHEAP_FALLBACK
    return _merge_ladder((cheap,), scored, leaders, _DEFAULT_LADDER)


def _cheap_capable_ladder(repo_root: Path | None = None) -> list[str]:
    """Cheap paid catalog first (routine builds). Free only as a fallback."""
    from app.jarvis.cost_index import load_index_model_order
    from app.jarvis.openrouter_leaders import cheap_catalog_ids

    current = cheap_default_model()
    scored = load_index_model_order(repo_root, current_cheap=current)
    board = _leaders_for_route()
    paid = cheap_catalog_ids(board.models, allow_free=False)
    free_ok = cheap_catalog_ids(board.models, allow_free=True)
    cheap = load_bench_preferred_cheap(repo_root) or (paid[0] if paid else (free_ok[0] if free_ok else current))
    if "auto" in cheap.lower():
        cheap = paid[0] if paid else _CHEAP_FALLBACK
    return _merge_ladder((cheap,), scored, paid, free_ok, _DEFAULT_LADDER)


def _smart_ladder(repo_root: Path | None = None) -> list[str]:
    """High-IQ paid catalog first. Usage rank is not the pick key."""
    from app.jarvis.cost_index import load_index_model_order
    from app.jarvis.openrouter_leaders import smart_catalog_ids

    current = cheap_default_model()
    scored = load_index_model_order(repo_root, current_cheap=current)
    board = _leaders_for_route()
    smart = smart_catalog_ids(board.models)
    stronger_defaults = tuple(
        m
        for m in _DEFAULT_LADDER
        if "mini" not in m.lower() and "flash" not in m.lower()
    )
    return _merge_ladder(smart, scored, stronger_defaults, _DEFAULT_LADDER)


def _pool_for_task(task_class: TaskClass, pref: Preference) -> str:
    # Settings Fast / Balanced / Smart (ORCH-384). Legacy cheap_fast keeps
    # ORCH-362/363 hard-task → high-IQ first-pick behavior when unset.
    if pref == "quality":
        return "high_iq"
    if pref == "balanced":
        return "balanced"
    if pref == "fast":
        if task_class == "light":
            return "cheap_free_ok"
        return "cheap_capable"
    if task_class == "hard":
        return "high_iq"
    if task_class == "light":
        return "cheap_free_ok"
    return "cheap_capable"


_POOL_ORDER = ("cheap_free_ok", "cheap_capable", "balanced", "high_iq")


def _settings_model_speed(root: Path | None = None) -> str:
    try:
        from app.jarvis.settings_store import get_model_speed

        return get_model_speed(root)
    except Exception:
        return "balanced"


def apply_model_speed(pool: str, speed: str | None) -> str:
    """Shift the quality pool one step toward cheaper (fast) or smarter (careful).

    Balanced speed is a no-op so Fast / Balanced / Smart stays the primary pick.
    """
    if pool not in _POOL_ORDER:
        return pool
    idx = _POOL_ORDER.index(pool)
    parsed = (speed or "").strip().lower()
    if parsed == "fast":
        idx = max(0, idx - 1)
    elif parsed == "careful":
        idx = min(len(_POOL_ORDER) - 1, idx + 1)
    return _POOL_ORDER[idx]


def _balanced_ladder(repo_root: Path | None = None) -> list[str]:
    """Middle path: not the cheapest catalog tip, not usage-rank #1.

    Balanced is a real third choice (ORCH-384). It must not collapse to
    the cheap-first pick and must not collapse to the weekly #1 flash tip.
    """
    board = _leaders_for_route()
    cheap = _cheap_capable_ladder(repo_root)
    smart = _smart_ladder(repo_root)
    usage_one = board.models[0].model if board.models else ""
    cheapest = cheap[0] if cheap else ""
    banned = {m for m in (cheapest, usage_one) if m}
    paid = [m for m in board.models if not m.is_free]
    paid.sort(key=lambda m: (m.unit_price, m.model))
    mid = [m.model for m in paid if m.model not in banned]
    if not mid:
        mid = [m for m in cheap[1:] if m not in banned]
    if not mid:
        mid = [m for m in smart if m not in banned]
    first = mid[len(mid) // 2] if mid else (cheap[0] if cheap else _CHEAP_FALLBACK)
    if first in banned and mid:
        first = next((m for m in mid if m not in banned), mid[0])
    return _merge_ladder((first,), mid, cheap, smart)


def _settings_model_pin(root: Path | None = None) -> str | None:
    try:
        from app.jarvis.settings_store import load

        stored = load(root).get("model")
        if isinstance(stored, str) and stored.strip():
            return stored.strip()
    except Exception:
        return None
    return None


def resolve_hard_pin(
    *,
    explicit_model: str | None = None,
    root: Path | None = None,
) -> str | None:
    """Return a pinned model id when settings/env/override demand it."""
    explicit = (explicit_model or "").strip()
    if explicit:
        return explicit
    pin_env = (os.environ.get("JARVIS_MODEL_PIN") or "").strip()
    if pin_env:
        if _truthy(pin_env):
            # pin to settings/env resolved model
            pinned = _settings_model_pin(root)
            if pinned:
                return pinned
            return cheap_default_model()
        return pin_env
    if _truthy(os.environ.get("JARVIS_DISABLE_MODEL_ROUTER")):
        pinned = _settings_model_pin(root)
        return pinned or cheap_default_model()
    # Locked Settings model is a hard pin. An unlocked stored model is the
    # default helper (first pick) and may still escalate for hard jobs.
    try:
        from app.jarvis.settings_store import get_model_lock

        if get_model_lock(root):
            return _settings_model_pin(root)
    except Exception:
        return _settings_model_pin(root)
    return None


def _settings_preference(root: Path | None = None) -> str | None:
    try:
        from app.jarvis.settings_store import router_preference

        return router_preference(root)
    except Exception:
        return None


def _budget_status(root: Path | None = None) -> dict[str, Any]:
    try:
        from app.jarvis.settings_store import budget_status

        return budget_status(root)
    except Exception:
        return {"action": "ok", "hit": False}


def route_model(
    *,
    goal: str = "",
    explicit_model: str | None = None,
    preference: str | None = None,
    prior_failures: int | None = None,
    repo_root: Path | None = None,
    workspace_root: Path | None = None,
) -> ModelRouteChoice:
    """Select execution model + short reason for a Jarvis task."""
    if preference is None:
        preference = _settings_preference(workspace_root)
    pref = _normalize_preference(preference)
    budget = _budget_status(workspace_root)
    budget_action: BudgetAction = "ok"
    raw_action = str(budget.get("action") or "ok")
    if raw_action in {"ok", "cheaper", "stop"}:
        budget_action = raw_action  # type: ignore[assignment]

    pin = resolve_hard_pin(explicit_model=explicit_model, root=workspace_root)
    if pin and budget_action != "stop":
        if "auto" in pin.lower():
            pin = _CHEAP_FALLBACK
        return ModelRouteChoice(
            model=pin,
            reason="hard pin (settings/env/override)",
            task_class=classify_task(goal),
            preference=pref,
            pinned=True,
            escalate=False,
            budget_action=budget_action,
            metadata={"source": "pin", "budget": budget},
        )

    task_class = classify_task(goal)
    if budget_action == "stop":
        return ModelRouteChoice(
            model="",
            reason=f"budget cap reached ({budget.get('hit_period') or 'cap'})",
            task_class=task_class,
            preference=pref,
            pinned=False,
            escalate=False,
            budget_action="stop",
            metadata={"budget": budget, "source": "budget_stop"},
        )

    scorecard_path = remember_scorecard_path(
        repo_root=repo_root, workspace_root=workspace_root
    )
    state = load_state(workspace_root)
    failures_map = state.get("failures_by_class") if isinstance(state, dict) else {}
    stored_fail = 0
    if isinstance(failures_map, dict):
        try:
            stored_fail = int(failures_map.get(task_class) or 0)
        except (TypeError, ValueError):
            stored_fail = 0
    fails = max(0, int(prior_failures if prior_failures is not None else stored_fail))

    board = _leaders_for_route()
    pool = _pool_for_task(task_class, pref)
    model_speed = _settings_model_speed(workspace_root)
    pool = apply_model_speed(pool, model_speed)
    if budget_action == "cheaper":
        pool = "cheap_free_ok"
    if pool == "high_iq":
        ladder = _smart_ladder(repo_root)
    elif pool == "cheap_capable":
        ladder = _cheap_capable_ladder(repo_root)
    elif pool == "balanced":
        ladder = _balanced_ladder(repo_root)
    else:
        ladder = _ladder(repo_root)
    helper = _settings_model_pin(workspace_root)
    if helper and "auto" not in helper.lower() and pool != "high_iq":
        # Unlocked stored model is the default helper for /ask + light work.
        # Hard / high-IQ jobs may still pick a smarter catalog model.
        ladder = _merge_ladder((helper,), ladder)
    # Info / math / facts / short answers / cheap code: free workers first
    # when their env is set. Ox is an OpenRouter id so it can lead the
    # cheap ladder. Kimi stays on chat() — not this catalog. No workers
    # → existing OpenRouter ladder.
    free = pick_free_worker() if pool == "cheap_free_ok" else None
    helper_name = helper_display_name(free) if free else None
    # First pick is already in the right pool. Preference no longer
    # means "step past cheap on a usage-rank ladder."
    idx = 0
    escalate = False
    if fails > 0:
        idx = min(len(ladder) - 1, idx + fails)
        escalate = True

    model = ladder[idx]
    reason_parts = [
        f"task_class={task_class}",
        f"preference={pref}",
        f"model_speed={model_speed}",
        f"pool={pool}",
        f"ladder_idx={idx}",
        f"catalog={board.source}",
    ]
    if budget_action == "cheaper":
        reason_parts.append("budget near cap; switched to cheaper model")
    if escalate:
        reason_parts.append(f"escalate_after_failures={fails}")
    if pool == "balanced" and idx == 0:
        reason_parts.append("balanced middle path; not cheapest and not usage-rank one")
    if task_class == "hard" and not escalate and pool == "high_iq":
        reason_parts.append("high-IQ paid catalog first pick")
    if task_class == "routine_build" and idx == 0 and pool == "cheap_capable":
        reason_parts.append("cheap capable catalog/scorecard model for routine builds")
    if task_class == "light" and idx == 0 and pool == "cheap_free_ok":
        if helper_name:
            reason_parts.append(f"free worker {helper_name} for light jobs")
        else:
            reason_parts.append("cheap catalog model; free ok for light jobs")
    reason = "; ".join(reason_parts)
    return ModelRouteChoice(
        model=model,
        reason=reason,
        task_class=task_class,
        preference=pref,
        pinned=False,
        escalate=escalate,
        budget_action=budget_action,
        metadata={
            "ladder": ladder,
            "pool": pool,
            "prior_failures": fails,
            "bench_cheap": load_bench_preferred_cheap(repo_root),
            "scorecard_path": scorecard_path,
            "leaderboard_source": board.source,
            "leaderboard_as_of": board.as_of,
            "leaderboard_ids": list(board.ids),
            "budget": budget,
            "helper_name": helper_name,
            "free_worker": free.key if free else None,
            "model_speed": model_speed,
        },
    )


def why_model_blob(choice: ModelRouteChoice) -> dict[str, Any]:
    """Shape for agent health / bridge events / tool surfaces."""
    blob = {
        "model": choice.model,
        "reason": choice.reason,
        "task_class": choice.task_class,
        "preference": choice.preference,
        "pinned": choice.pinned,
        "escalate": choice.escalate,
        "budget_action": choice.budget_action,
    }
    name = (choice.metadata or {}).get("helper_name")
    if isinstance(name, str) and name in HELPER_DISPLAY_NAMES:
        blob["helper_name"] = name
    return blob
