"""Durable Jarvis settings (ORCH-322 / ORCH-380).

One shared config object. Web, Windows, and Android all read the same file:

    {JARVIS_WORKSPACE}/Memory/jarvis_settings.json

Do not invent a second settings store. Atomic replace on write so a crash
mid-save cannot leave a half-written file. Env vars remain the fallback when
a key is unset. API keys never live here.

Shared shape (``config_version`` 2) — every key listed is always present
after ``load()``; ``null`` means “unset / fall back to env or default”:

* ``permission_profile`` — locked | personal | power | null
* ``provider`` — openrouter | openai | xai | null
* ``model`` — optional default helper / hard-pin model id | null
* ``model_lock`` — bool; when true, Settings ``model`` is a hard pin
  (no escalate). When false, stored ``model`` is the default helper.
* ``model_lock_pin`` — sha256 of an optional 4-digit PIN (never returned)
* ``realtime_voice`` — OpenAI Realtime voice id | null
* ``look_speed`` — off | 30s | 10s | 1s | null  (ORCH-366; separate from quality)
* ``quality_vs_price`` — fast | balanced | smart | null  (ORCH-384; drives router)
* ``monthly_budget_usd`` — number | null  (ORCH-383; 0/null = use default $20)
* ``daily_budget_usd`` — number | null  (ORCH-383; 0/null = use default $2)
* ``spend`` — runtime ledger (not a user control):
      {day_key, day_usd, month_key, month_usd}
* ``model_preference`` — cheap_fast | balanced | quality | null
      (Windows alias of quality_vs_price; same file, not a second store)
* ``model_speed`` — fast | balanced | careful | null
      (how fast models should work; separate from look_speed)
* ``approve_countdown_sec`` — number | null  (ORCH-411; seconds before
      Allow happens on its own. Default 10. Clamped 1–120)
* ``computer_kind`` — linux | android | null  (ORCH-461; which box Jarvis
      drives. Default linux. Android is a second machine, not the Play
      Store phone app.)

Router reads ``quality_vs_price`` (or the ``model_preference`` alias) and the budget caps from this object.
A locked stored ``model`` is a hard pin. An unlocked stored ``model`` is
the default helper for /ask and children. Look-speed is intentionally
not merged into Fast / Balanced / Smart.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.jarvis.audit import redact
from app.jarvis.permissions import PROFILE_MAX_AUTO
from app.jarvis.realtime import ALLOWED_REALTIME_VOICES
from app.jarvis.workspace import default_workspace

SETTINGS_FILENAME = "jarvis_settings.json"
CONFIG_VERSION = 2

PROFILE_BLURBS: dict[str, dict[str, str]] = {
    "locked": {
        "label": "Locked",
        "allows": (
            "Read-only facts only (disk space, system info, memory recall). "
            "Jarvis will not write files, touch your folders, or run apps."
        ),
    },
    "personal": {
        "label": "Personal",
        "allows": (
            "Everyday help: read and write the Jarvis workspace, and work in "
            "Desktop / Documents / Downloads. Shell and apps still ask first."
        ),
    },
    "power": {
        "label": "Power",
        "allows": (
            "Trusted mode: apps and PowerShell can run automatically when "
            "allowlisted. Destructive or unknown actions still need a confirm."
        ),
    },
}

ALLOWED_PROVIDERS = frozenset({"openrouter", "openai", "xai"})

# ORCH-366: user-picked look interval. Default off = look only when a job
# needs a picture. Do not hardcode one speed. Separate from quality_vs_price.
ALLOWED_LOOK_SPEEDS = frozenset({"off", "30s", "10s", "1s"})
LOOK_SPEED_INTERVALS: dict[str, float | None] = {
    "off": None,
    "30s": 30.0,
    "10s": 10.0,
    "1s": 1.0,
}
LOOK_SPEED_BLURBS: dict[str, dict[str, str]] = {
    "off": {
        "label": "Off",
        "allows": "I only look when a job needs a picture.",
    },
    "30s": {
        "label": "Every 30 seconds",
        "allows": "While I work on the screen, I look again every 30 seconds.",
    },
    "10s": {
        "label": "Every 10 seconds",
        "allows": "While I work on the screen, I look again every 10 seconds.",
    },
    "1s": {
        "label": "Every second",
        "allows": "While I work on the screen, I look again every second.",
    },
}

# ORCH-384: Fast / Balanced / Smart. Maps to the model router. Not look-speed.
ALLOWED_QUALITY = frozenset({"fast", "balanced", "smart"})
QUALITY_BLURBS: dict[str, dict[str, str]] = {
    "fast": {
        "label": "Fast",
        "allows": "Cheaper and quicker. Good for everyday asks.",
    },
    "balanced": {
        "label": "Balanced",
        "allows": "A middle path — not the cheapest, not the most expensive.",
    },
    "smart": {
        "label": "Smart",
        "allows": "Thinks harder. May cost more.",
    },
}

# Env names whose VALUES must never appear in API/HTML — only configured flags.
SECRET_ENV_NAMES: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "KIMI_CODE_API_KEY",
    "KIMI_API_KEY",
    "BRIDGE_TOKEN",
    "JARVIS_BRIDGE_TOKEN",
    "TOKEN_ENCRYPTION_KEY",
    "API_SECRET",
    "XAI_API_KEY",
    "POSTGRES_PASSWORD",
)

_DEFAULT_MODEL_SUGGESTIONS: tuple[str, ...] = (
    "deepseek/deepseek-v4-flash-0731",
    "deepseek/deepseek-v4-pro-0813",
    "z-ai/glm-5.2",
    "openai/gpt-5.6-luna",
    "tencent/hy3",
    "openrouter/auto",
    "gpt-realtime-mini",
)

_STRING_KEYS = frozenset(
    {
        "permission_profile",
        "provider",
        "model",
        "model_lock_pin",
        "realtime_voice",
        "look_speed",
        "quality_vs_price",
        "model_preference",
        "model_speed",
        "computer_kind",
    }
)
_BOOL_KEYS = frozenset({"model_lock"})
_FLOAT_KEYS = frozenset({"monthly_budget_usd", "daily_budget_usd"})
_INT_KEYS = frozenset({"approve_countdown_sec"})
_PIN_SALT = "jarvis-model-lock-v1:"
DEFAULT_DAILY_BUDGET_USD = 2.0
DEFAULT_MONTHLY_BUDGET_USD = 20.0
DEFAULT_APPROVE_COUNTDOWN_SEC = 10
APPROVE_COUNTDOWN_MIN = 1
APPROVE_COUNTDOWN_MAX = 120
ALLOWED_MODEL_PREFERENCES = frozenset({"cheap_fast", "balanced", "quality"})
ALLOWED_MODEL_SPEEDS = frozenset({"fast", "balanced", "careful"})

# ORCH-461: Jarvis's own computer. linux is the usual box. android is a
# phone-shaped box he can tap. Not the Play Store client under android/.
ALLOWED_COMPUTER_KINDS = frozenset({"linux", "android"})
DEFAULT_COMPUTER_KIND = "linux"
COMPUTER_KIND_BLURBS: dict[str, dict[str, str]] = {
    "linux": {
        "label": "Linux",
        "allows": "The usual desktop. Chrome, notepad, files.",
    },
    "android": {
        "label": "Android",
        "allows": "A phone-shaped box he can tap. Same Jarvis, different computer.",
    },
}
_QUALITY_TO_PREF = {"fast": "cheap_fast", "balanced": "balanced", "smart": "quality"}
_PREF_TO_QUALITY = {"cheap_fast": "fast", "balanced": "balanced", "quality": "smart"}

_lock = threading.RLock()
_cache: dict[str, Any] | None = None
_cache_path: Path | None = None


def settings_path(root: Path | None = None) -> Path:
    base = (root or default_workspace()).resolve()
    return base / "Memory" / SETTINGS_FILENAME


def _empty_spend() -> dict[str, Any]:
    return {
        "day_key": "",
        "day_usd": 0.0,
        "month_key": "",
        "month_usd": 0.0,
    }


def _empty() -> dict[str, Any]:
    return {
        "permission_profile": None,
        "provider": None,
        "model": None,
        "model_lock": False,
        "model_lock_pin": None,
        "realtime_voice": None,
        "look_speed": None,
        "quality_vs_price": None,
        "monthly_budget_usd": None,
        "daily_budget_usd": None,
        "model_preference": None,
        "model_speed": None,
        "approve_countdown_sec": None,
        "computer_kind": None,
        "spend": _empty_spend(),
    }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _day_key(now: datetime | None = None) -> str:
    return (now or _utc_now()).strftime("%Y-%m-%d")


def _month_key(now: datetime | None = None) -> str:
    return (now or _utc_now()).strftime("%Y-%m")


def _normalize_spend(raw: Any, *, now: datetime | None = None) -> dict[str, Any]:
    out = _empty_spend()
    if not isinstance(raw, dict):
        return out
    day_key = str(raw.get("day_key") or "").strip()
    month_key = str(raw.get("month_key") or "").strip()
    try:
        day_usd = float(raw.get("day_usd") or 0.0)
    except (TypeError, ValueError):
        day_usd = 0.0
    try:
        month_usd = float(raw.get("month_usd") or 0.0)
    except (TypeError, ValueError):
        month_usd = 0.0
    if day_usd != day_usd or day_usd < 0:
        day_usd = 0.0
    if month_usd != month_usd or month_usd < 0:
        month_usd = 0.0
    today = _day_key(now)
    month = _month_key(now)
    out["day_key"] = today if day_key == today else today
    out["day_usd"] = round(day_usd, 6) if day_key == today else 0.0
    out["month_key"] = month if month_key == month else month
    out["month_usd"] = round(month_usd, 6) if month_key == month else 0.0
    return out


def _coerce_int(val: Any) -> int | None:
    if val is None or val == "":
        return None
    try:
        n = int(float(val))
    except (TypeError, ValueError):
        return None
    return n


def clamp_approve_countdown_sec(val: int) -> int:
    return max(APPROVE_COUNTDOWN_MIN, min(APPROVE_COUNTDOWN_MAX, int(val)))


def _coerce_float(val: Any) -> float | None:
    if val is None or val == "":
        return None
    try:
        n = float(val)
    except (TypeError, ValueError):
        return None
    if n != n or n < 0:
        return None
    return n


def _coerce_bool(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)) and val in {0, 1}:
        return bool(val)
    if isinstance(val, str):
        return val.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _hash_pin(pin: str) -> str:
    return hashlib.sha256((_PIN_SALT + pin).encode("utf-8")).hexdigest()


def _normalize_pin(raw: str | None) -> str | None:
    s = (raw or "").strip()
    if not s:
        return None
    if not (s.isdigit() and len(s) == 4):
        raise ValueError("PIN must be 4 digits")
    return s


def _read_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return _empty()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    if not isinstance(raw, dict):
        return _empty()
    out = _empty()
    for key in _STRING_KEYS:
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = val.strip()
    for key in _BOOL_KEYS:
        if key in raw and raw[key] is not None:
            out[key] = _coerce_bool(raw[key])
    for key in _FLOAT_KEYS:
        if key in raw:
            out[key] = _coerce_float(raw[key])
    for key in _INT_KEYS:
        if key in raw:
            out[key] = _coerce_int(raw[key])
    out["spend"] = _normalize_spend(raw.get("spend"))
    return out


def _write_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: data.get(k) for k in _empty()}
    if isinstance(payload.get("spend"), dict):
        payload["spend"] = _normalize_spend(payload["spend"])
    payload["config_version"] = CONFIG_VERSION
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def load(root: Path | None = None, *, force: bool = False) -> dict[str, Any]:
    """Return the stored settings dict (values may be None = fall back to env)."""
    global _cache, _cache_path
    path = settings_path(root)
    with _lock:
        if not force and _cache is not None and _cache_path == path:
            return dict(_cache)
        data = _read_file(path)
        _cache = dict(data)
        _cache_path = path
        return dict(data)


def reset_cache() -> None:
    """Test helper — drop the in-process cache."""
    global _cache, _cache_path
    with _lock:
        _cache = None
        _cache_path = None


def save(updates: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    """Merge ``updates`` into the store and persist. Returns the new raw store."""
    global _cache, _cache_path
    path = settings_path(root)
    with _lock:
        cur = _read_file(path)
        for key in _empty():
            if key not in updates:
                continue
            if key == "spend":
                # Runtime ledger — use record_spend(), not a user PUT.
                continue
            val = updates[key]
            if key in _BOOL_KEYS:
                cur[key] = _coerce_bool(val)
            elif key in _FLOAT_KEYS:
                cur[key] = _coerce_float(val)
            elif key in _INT_KEYS:
                n = _coerce_int(val)
                cur[key] = clamp_approve_countdown_sec(n) if n is not None else None
            elif key == "model_lock_pin":
                if val is None or val == "":
                    cur[key] = None
                elif isinstance(val, str):
                    s = val.strip()
                    if s.isdigit() and len(s) == 4:
                        cur[key] = _hash_pin(s)
                    else:
                        cur[key] = s or None
            elif val is None:
                cur[key] = None
            elif isinstance(val, str):
                cur[key] = val.strip() or None
        if "quality_vs_price" in updates and cur.get("quality_vs_price") in _QUALITY_TO_PREF:
            cur["model_preference"] = _QUALITY_TO_PREF[cur["quality_vs_price"]]
        elif "model_preference" in updates and cur.get("model_preference") in _PREF_TO_QUALITY:
            cur["quality_vs_price"] = _PREF_TO_QUALITY[cur["model_preference"]]
        _write_file(path, cur)
        _cache = dict(cur)
        _cache_path = path
        return dict(cur)


def record_spend(usd: float, root: Path | None = None) -> dict[str, Any]:
    """Add known provider spend to the persisted daily/monthly ledger."""
    global _cache, _cache_path
    try:
        amount = float(usd)
    except (TypeError, ValueError):
        return load(root)
    if amount != amount or amount <= 0:
        return load(root)
    path = settings_path(root)
    with _lock:
        cur = _read_file(path)
        spend = _normalize_spend(cur.get("spend"))
        spend["day_usd"] = round(float(spend["day_usd"]) + amount, 6)
        spend["month_usd"] = round(float(spend["month_usd"]) + amount, 6)
        cur["spend"] = spend
        _write_file(path, cur)
        _cache = dict(cur)
        _cache_path = path
        return dict(cur)


def _env_profile() -> str:
    p = (os.environ.get("JARVIS_PERMISSION_PROFILE") or "personal").strip().lower()
    return p if p in PROFILE_MAX_AUTO else "personal"


def _env_provider() -> str:
    p = (os.environ.get("JARVIS_PROVIDER") or os.environ.get("LLM_PROVIDER") or "openrouter")
    p = p.strip().lower()
    if p in {"grok"}:
        p = "xai"
    return p if p in ALLOWED_PROVIDERS else "openrouter"


def _env_model() -> str:
    return (
        os.environ.get("JARVIS_MODEL")
        or os.environ.get("DEFAULT_MODEL")
        or "deepseek/deepseek-v4-flash-0731"
    ).strip()


def _env_voice() -> str:
    v = (os.environ.get("OPENAI_REALTIME_VOICE") or "marin").strip().lower()
    return v if v in ALLOWED_REALTIME_VOICES else "marin"


def get_permission_profile(root: Path | None = None) -> str:
    stored = load(root).get("permission_profile")
    if isinstance(stored, str) and stored.lower() in PROFILE_MAX_AUTO:
        return stored.lower()
    return _env_profile()


def get_provider(root: Path | None = None) -> str:
    stored = load(root).get("provider")
    if isinstance(stored, str) and stored.lower() in ALLOWED_PROVIDERS:
        return stored.lower()
    return _env_provider()


def get_model(root: Path | None = None) -> str:
    stored = load(root).get("model")
    if isinstance(stored, str) and stored.strip():
        return stored.strip()
    return _env_model()


def get_model_lock(root: Path | None = None) -> bool:
    return bool(load(root).get("model_lock"))


def model_lock_pin_set(root: Path | None = None) -> bool:
    stored = load(root).get("model_lock_pin")
    return isinstance(stored, str) and bool(stored.strip())


def verify_unlock_pin(pin: str | None, root: Path | None = None) -> bool:
    stored = load(root).get("model_lock_pin")
    if not (isinstance(stored, str) and stored.strip()):
        return True
    try:
        normalized = _normalize_pin(pin)
    except ValueError:
        return False
    if not normalized:
        return False
    return _hash_pin(normalized) == stored


def get_realtime_voice(root: Path | None = None) -> str:
    stored = load(root).get("realtime_voice")
    if isinstance(stored, str) and stored.strip().lower() in ALLOWED_REALTIME_VOICES:
        return stored.strip().lower()
    return _env_voice()


def _normalize_look_speed(raw: str | None) -> str | None:
    s = (raw or "").strip().lower()
    aliases = {"30": "30s", "10": "10s", "1": "1s", "0": "off", "none": "off"}
    s = aliases.get(s, s)
    return s if s in ALLOWED_LOOK_SPEEDS else None


def _env_look_speed() -> str:
    parsed = _normalize_look_speed(os.environ.get("JARVIS_LOOK_SPEED"))
    return parsed or "off"


def get_look_speed(root: Path | None = None) -> str:
    """off | 30s | 10s | 1s. Default off."""
    stored = load(root).get("look_speed")
    parsed = _normalize_look_speed(stored if isinstance(stored, str) else None)
    if parsed:
        return parsed
    return _env_look_speed()


def look_speed_interval_seconds(root: Path | None = None) -> float | None:
    """Seconds between looks, or None when look speed is off."""
    return LOOK_SPEED_INTERVALS[get_look_speed(root)]


def _normalize_quality(raw: str | None) -> str | None:
    s = (raw or "").strip().lower()
    aliases = {
        "fast": "fast",
        "cheap": "fast",
        "cheap_fast": "fast",
        "balanced": "balanced",
        "default": "balanced",
        "medium": "balanced",
        "normal": "balanced",
        "smart": "smart",
        "quality": "smart",
        "premium": "smart",
        "hard": "smart",
    }
    mapped = aliases.get(s)
    return mapped if mapped in ALLOWED_QUALITY else None


def _env_quality() -> str | None:
    return _normalize_quality(os.environ.get("JARVIS_MODEL_PREFERENCE"))


def get_quality_vs_price(root: Path | None = None) -> str:
    """fast | balanced | smart. Default balanced (user-facing)."""
    data = load(root)
    stored = data.get("quality_vs_price")
    parsed = _normalize_quality(stored if isinstance(stored, str) else None)
    if parsed:
        return parsed
    alias = _normalize_quality(data.get("model_preference") if isinstance(data.get("model_preference"), str) else None)
    if alias:
        return alias
    return _env_quality() or "balanced"


def router_preference(root: Path | None = None) -> str | None:
    """Preference the router should honor, or None to keep legacy pool rules.

    Reads stored ``quality_vs_price`` or the Windows ``model_preference``
    alias. Env still flows through the router’s own
    ``JARVIS_MODEL_PREFERENCE`` fallback so existing tests and ORCH-362/363
    hard-task behavior stay intact when unset.
    """
    data = load(root)
    stored = data.get("quality_vs_price")
    parsed = _normalize_quality(stored if isinstance(stored, str) else None)
    if parsed:
        return parsed
    alias = data.get("model_preference")
    return _normalize_quality(alias if isinstance(alias, str) else None)


def _normalize_model_preference(raw: str | None) -> str | None:
    q = _normalize_quality(raw)
    if q:
        return _QUALITY_TO_PREF[q]
    p = (raw or "").strip().lower()
    return p if p in ALLOWED_MODEL_PREFERENCES else None


def get_model_preference(root: Path | None = None) -> str:
    """cheap_fast | balanced | quality. Alias of quality_vs_price."""
    data = load(root)
    stored = data.get("model_preference")
    parsed = _normalize_model_preference(stored if isinstance(stored, str) else None)
    if parsed:
        return parsed
    q = _normalize_quality(data.get("quality_vs_price") if isinstance(data.get("quality_vs_price"), str) else None)
    if q:
        return _QUALITY_TO_PREF[q]
    env = _normalize_model_preference(os.environ.get("JARVIS_MODEL_PREFERENCE"))
    return env or "balanced"


def _normalize_model_speed(raw: str | None) -> str | None:
    s = (raw or "").strip().lower()
    aliases = {
        "quick": "fast",
        "faster": "fast",
        "normal": "balanced",
        "medium": "balanced",
        "default": "balanced",
        "slow": "careful",
        "slower": "careful",
        "thorough": "careful",
    }
    s = aliases.get(s, s)
    return s if s in ALLOWED_MODEL_SPEEDS else None


def get_model_speed(root: Path | None = None) -> str:
    """fast | balanced | careful. Separate from look_speed. Default balanced."""
    stored = load(root).get("model_speed")
    parsed = _normalize_model_speed(stored if isinstance(stored, str) else None)
    if parsed:
        return parsed
    env = _normalize_model_speed(os.environ.get("JARVIS_MODEL_SPEED"))
    return env or "balanced"


def get_monthly_budget_usd(root: Path | None = None) -> float:
    val = _coerce_float(load(root).get("monthly_budget_usd"))
    if val is not None and val > 0:
        return val
    env = _coerce_float(os.environ.get("JARVIS_MONTHLY_BUDGET_USD"))
    return env if env is not None and env > 0 else DEFAULT_MONTHLY_BUDGET_USD


def get_approve_countdown_sec(root: Path | None = None) -> int:
    """Seconds before Allow happens on its own. Default 10. Range 1–120."""
    stored = _coerce_int(load(root).get("approve_countdown_sec"))
    if stored is not None:
        return clamp_approve_countdown_sec(stored)
    env = _coerce_int(os.environ.get("JARVIS_APPROVE_COUNTDOWN_SEC"))
    if env is not None:
        return clamp_approve_countdown_sec(env)
    return DEFAULT_APPROVE_COUNTDOWN_SEC


def _normalize_computer_kind(raw: str | None) -> str | None:
    s = (raw or "").strip().lower().replace("_", "-")
    aliases = {
        "linux": "linux",
        "jarvis-computer": "linux",
        "jarvis_computer": "linux",
        "desktop": "linux",
        "android": "android",
        "jarvis-android": "android",
        "jarvis_android": "android",
        "redroid": "android",
        "phone-box": "android",
    }
    mapped = aliases.get(s, s)
    return mapped if mapped in ALLOWED_COMPUTER_KINDS else None


def get_computer_kind(root: Path | None = None, env: dict[str, str] | None = None) -> str:
    """linux | android. Default linux. Android is Jarvis's other box."""
    stored = load(root).get("computer_kind")
    parsed = _normalize_computer_kind(stored if isinstance(stored, str) else None)
    if parsed:
        return parsed
    environ = env if env is not None else os.environ
    env_kind = _normalize_computer_kind(str(environ.get("JARVIS_COMPUTER_KIND") or ""))
    return env_kind or DEFAULT_COMPUTER_KIND


def get_daily_budget_usd(root: Path | None = None) -> float:
    val = _coerce_float(load(root).get("daily_budget_usd"))
    if val is not None and val > 0:
        return val
    env = _coerce_float(os.environ.get("JARVIS_DAILY_BUDGET_USD"))
    return env if env is not None and env > 0 else DEFAULT_DAILY_BUDGET_USD


def budget_status(root: Path | None = None) -> dict[str, Any]:
    """Spend so far vs caps. Windows/Android can render this same object."""
    data = load(root)
    spend = _normalize_spend(data.get("spend"))
    daily_cap = get_daily_budget_usd(root)
    monthly_cap = get_monthly_budget_usd(root)
    day_usd = float(spend["day_usd"] or 0.0)
    month_usd = float(spend["month_usd"] or 0.0)
    daily_remaining = None if daily_cap is None else max(0.0, daily_cap - day_usd)
    monthly_remaining = None if monthly_cap is None else max(0.0, monthly_cap - month_usd)
    hit_period = None
    if daily_cap is not None and day_usd >= daily_cap:
        hit_period = "daily"
    if monthly_cap is not None and month_usd >= monthly_cap:
        hit_period = "monthly"
    remaining_parts = [p for p in (daily_remaining, monthly_remaining) if p is not None]
    remaining_usd = min(remaining_parts) if remaining_parts else None
    near = False
    if daily_cap and daily_remaining is not None and daily_remaining <= max(0.05, 0.2 * daily_cap):
        near = True
    if monthly_cap and monthly_remaining is not None and monthly_remaining <= max(0.05, 0.2 * monthly_cap):
        near = True
    return {
        "daily_cap_usd": daily_cap,
        "monthly_cap_usd": monthly_cap,
        "daily_spent_usd": round(day_usd, 6),
        "monthly_spent_usd": round(month_usd, 6),
        "daily_remaining_usd": None if daily_remaining is None else round(daily_remaining, 6),
        "monthly_remaining_usd": None if monthly_remaining is None else round(monthly_remaining, 6),
        "remaining_usd": None if remaining_usd is None else round(remaining_usd, 6),
        "hit": hit_period is not None,
        "hit_period": hit_period,
        "near_cap": bool(near and hit_period is None),
        "action": "stop" if hit_period else ("cheaper" if near else "ok"),
    }


def secrets_status() -> list[dict[str, Any]]:
    """Boolean configured flags only — never the secret values.

    Returned as a list of ``{name, configured}`` so structural redaction does
    not wipe the flags (a dict keyed by ``BRIDGE_TOKEN`` would look sensitive).
    """
    out: list[dict[str, Any]] = []
    for name in SECRET_ENV_NAMES:
        out.append(
            {
                "name": name,
                "configured": bool((os.environ.get(name) or "").strip()),
            }
        )
    return out


def public_view(root: Path | None = None) -> dict[str, Any]:
    """Safe GET payload: no secret values, redacted defensively."""
    path = settings_path(root)
    profiles = []
    for pid in ("locked", "personal", "power"):
        meta = PROFILE_BLURBS[pid]
        profiles.append(
            {
                "id": pid,
                "label": meta["label"],
                "allows": meta["allows"],
                "max_auto_tier": f"L{int(PROFILE_MAX_AUTO[pid])}",
            }
        )
    connectors: list[dict[str, Any]] = []
    try:
        from app.jarvis.mcp_registry import list_connectors_public

        connectors = list_connectors_public(root)
    except Exception:
        connectors = []
    mcp_presets: list[dict[str, Any]] = []
    try:
        from app.jarvis.mcp_presets import list_presets_public

        mcp_presets = list_presets_public()
    except Exception:
        mcp_presets = []
    helper_models: list[dict[str, Any]] = []
    try:
        from app.jarvis.openrouter_leaders import helper_models_public

        helper_models = helper_models_public()
    except Exception:
        helper_models = []
    helper_name = None
    try:
        from app.jarvis.model_router import helper_display_name

        helper_name = helper_display_name()
    except Exception:
        helper_name = None
    view = {
        "config_version": CONFIG_VERSION,
        "config_file": "Memory/jarvis_settings.json",
        "permission_profile": get_permission_profile(root),
        "permission_profiles": profiles,
        "provider": get_provider(root),
        "providers": sorted(ALLOWED_PROVIDERS),
        "model": get_model(root),
        "model_suggestions": list(_DEFAULT_MODEL_SUGGESTIONS),
        "model_lock": get_model_lock(root),
        "model_lock_pin_set": model_lock_pin_set(root),
        "realtime_voice": get_realtime_voice(root),
        "realtime_voices": sorted(ALLOWED_REALTIME_VOICES),
        "look_speed": get_look_speed(root),
        "look_speeds": [
            {
                "id": sid,
                "label": LOOK_SPEED_BLURBS[sid]["label"],
                "allows": LOOK_SPEED_BLURBS[sid]["allows"],
            }
            for sid in ("off", "30s", "10s", "1s")
        ],
        "quality_vs_price": get_quality_vs_price(root),
        "quality_vs_price_choices": [
            {
                "id": qid,
                "label": QUALITY_BLURBS[qid]["label"],
                "allows": QUALITY_BLURBS[qid]["allows"],
            }
            for qid in ("fast", "balanced", "smart")
        ],
        "monthly_budget_usd": get_monthly_budget_usd(root),
        "daily_budget_usd": get_daily_budget_usd(root),
        "budget": budget_status(root),
        "model_preference": get_model_preference(root),
        "model_preferences": [
            {"id": "cheap_fast", "label": "Cheaper", "allows": "Faster and cheaper. Good enough for everyday asks."},
            {"id": "balanced", "label": "Balanced", "allows": "A middle path — not the cheapest, not the most expensive."},
            {"id": "quality", "label": "Smarter", "allows": "Thinks harder. May cost more."},
        ],
        "model_speed": get_model_speed(root),
        "approve_countdown_sec": get_approve_countdown_sec(root),
        "approve_countdown_min": APPROVE_COUNTDOWN_MIN,
        "approve_countdown_max": APPROVE_COUNTDOWN_MAX,
        "computer_kind": get_computer_kind(root),
        "computer_kinds": [
            {
                "id": kid,
                "label": COMPUTER_KIND_BLURBS[kid]["label"],
                "allows": COMPUTER_KIND_BLURBS[kid]["allows"],
            }
            for kid in ("linux", "android")
        ],
        "model_speeds": [
            {"id": "fast", "label": "Fast", "allows": "Pick quicker models when I can."},
            {"id": "balanced", "label": "Normal", "allows": "Normal speed."},
            {"id": "careful", "label": "Careful", "allows": "Take more time when the job is hard."},
        ],
        "secrets": secrets_status(),
        "connectors": connectors,
        "connectors_empty": "None yet",
        "spent_today_usd": budget_status(root)["daily_spent_usd"],
        "spent_month_usd": budget_status(root)["monthly_spent_usd"],
        "remaining_budget_usd": budget_status(root)["remaining_usd"],
        "mcp_presets": mcp_presets,
        "helper_models": helper_models,
        "helper_name": helper_name,
        "settings_path": str(path),
        "note": (
            "Values in Memory/jarvis_settings.json override env until changed. "
            "API keys are never stored or returned — only configured/not-configured. "
            "MCP connector tokens are encrypted at rest and never returned. "
            "The PIN is stored hashed and never returned."
        ),
    }
    return redact(view)


def validate_update(body: dict[str, Any], *, require_unlock: bool = True) -> dict[str, Any]:
    """Return normalised updates or raise ValueError with a public message."""
    updates: dict[str, Any] = {}
    if "permission_profile" in body and body["permission_profile"] is not None:
        p = str(body["permission_profile"]).strip().lower()
        if p not in PROFILE_MAX_AUTO:
            raise ValueError("permission_profile must be locked, personal, or power")
        updates["permission_profile"] = p
    if "provider" in body and body["provider"] is not None:
        p = str(body["provider"]).strip().lower()
        if p in {"grok"}:
            p = "xai"
        if p not in ALLOWED_PROVIDERS:
            raise ValueError("provider must be openrouter, openai, or xai")
        updates["provider"] = p
    if "model" in body and body["model"] is not None:
        m = str(body["model"]).strip()
        if not m or len(m) > 120:
            raise ValueError("model must be a non-empty id (max 120 chars)")
        updates["model"] = m
    if "model" in body and body["model"] is None:
        updates["model"] = None
    if "realtime_voice" in body and body["realtime_voice"] is not None:
        v = str(body["realtime_voice"]).strip().lower()
        if v not in ALLOWED_REALTIME_VOICES:
            raise ValueError("realtime_voice is not in the allow-list")
        updates["realtime_voice"] = v
    if "look_speed" in body and body["look_speed"] is not None:
        parsed = _normalize_look_speed(str(body["look_speed"]))
        if not parsed:
            raise ValueError("look_speed must be off, 30s, 10s, or 1s")
        updates["look_speed"] = parsed
    if "quality_vs_price" in body and body["quality_vs_price"] is not None:
        parsed = _normalize_quality(str(body["quality_vs_price"]))
        if not parsed:
            raise ValueError("quality_vs_price must be fast, balanced, or smart")
        updates["quality_vs_price"] = parsed
    if "model_preference" in body and body["model_preference"] is not None:
        parsed = _normalize_model_preference(str(body["model_preference"]))
        if not parsed:
            raise ValueError("model_preference must be cheap_fast, balanced, or quality")
        updates["model_preference"] = parsed
        updates.setdefault("quality_vs_price", _PREF_TO_QUALITY[parsed])
    if "model_speed" in body and body["model_speed"] is not None:
        parsed = _normalize_model_speed(str(body["model_speed"]))
        if not parsed:
            raise ValueError("model_speed must be fast, balanced, or careful")
        updates["model_speed"] = parsed
    if "computer_kind" in body and body["computer_kind"] is not None:
        parsed = _normalize_computer_kind(str(body["computer_kind"]))
        if not parsed:
            raise ValueError("computer_kind must be linux or android")
        updates["computer_kind"] = parsed
    if "approve_countdown_sec" in body:
        raw = body["approve_countdown_sec"]
        if raw is None or raw == "":
            updates["approve_countdown_sec"] = None
        else:
            n = _coerce_int(raw)
            if n is None:
                raise ValueError("approve_countdown_sec must be a number")
            updates["approve_countdown_sec"] = clamp_approve_countdown_sec(n)
    if "monthly_budget_usd" in body:
        cap = _coerce_float(body["monthly_budget_usd"])
        updates["monthly_budget_usd"] = cap if cap and cap > 0 else None
    if "daily_budget_usd" in body:
        cap = _coerce_float(body["daily_budget_usd"])
        updates["daily_budget_usd"] = cap if cap and cap > 0 else None
    if "model_lock" in body and body["model_lock"] is not None:
        updates["model_lock"] = _coerce_bool(body["model_lock"])
        if updates["model_lock"] is False and "model" not in updates:
            updates["model"] = None
    if "model_lock_pin" in body:
        pin = _normalize_pin(str(body["model_lock_pin"]) if body["model_lock_pin"] is not None else None)
        updates["model_lock_pin"] = _hash_pin(pin) if pin else None
    if require_unlock and (
        "model_lock" in updates or "model" in updates or "model_lock_pin" in updates
    ):
        unlock = body.get("unlock_pin")
        unlock_s = str(unlock) if unlock is not None else None
        if model_lock_pin_set() and not verify_unlock_pin(unlock_s):
            raise ValueError("PIN required to change the model lock")
    return updates
