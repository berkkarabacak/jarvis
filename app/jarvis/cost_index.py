"""Jarvis bench scorecard (ORCH-331 / ORCH-336 / ORCH-334).

Headline metrics (publish all three):
  pass@1, USD per success, escalate %

Failed runs stay in the USD denominator for $ per success.

One cost_unknown *task* does not wipe the model: $ per success uses
known-cost rows only (those rows' failures still sit in the $ sum).
If every row is cost_unknown, the model stays cost_unknown.

Fail-then-escalate (ORCH-336): when a cheap attempt fails and a stronger
model retries, both attempts stay visible on the row (`attempts`) and
their USD is summed. Do not hide retries. escalate % counts that path.

Optional *ours* composite for ranking our table only:
  successes / (USD + TIME_PENALTY_USD_PER_SEC * elapsed_sec)

This is not an Artificial Analysis number. AA publishes an Intelligence Index
and plots Intelligence vs Cost per Task; they do not officially rank
Quality÷Price. We do not invent a single fake IQ/$.

Provider-reported $0 / missing cost is cost_unknown — never treated as free.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

INDEX_LATEST = Path("benchmarks") / "jarvis-index-latest.json"
INDEX_VERSION = 3
INDEX_NAME = "Jarvis bench scorecard"
TIME_PENALTY_USD_PER_SEC = 0.0001  # small: 10s ≈ $0.001 vs typical API cents
OURS_COMPOSITE_FORMULA = (
    "successes / (cost_usd + time_penalty_usd_per_sec * elapsed_sec)"
)
HEADLINE_METRICS = ("pass_at_1", "usd_per_success", "escalate_pct")
AA_NOTE = (
    "Inspired by Artificial Analysis, which plots Intelligence vs Cost per Task "
    "and does not officially rank Quality÷Price. Headline metrics are pass@1, "
    "$ per success, and escalate %. ours_composite is our optional ranking key "
    "only — not an AA IQ/$ number."
)


@dataclass(frozen=True)
class CostNorm:
    cost_usd: float | None
    cost_unknown: bool
    cost_source: str


@dataclass(frozen=True)
class ModelIndexRow:
    model: str
    ok: int
    n: int
    seconds: float
    cost_usd: float | None
    cost_unknown: bool
    known_n: int
    escalate: int
    pass_at_1: float | None
    usd_per_success: float | None
    escalate_pct: float | None
    ours_composite: float | None
    rankable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "ok": self.ok,
            "n": self.n,
            "seconds": round(self.seconds, 4),
            "cost_usd": self.cost_usd,
            "cost_unknown": self.cost_unknown,
            "known_n": self.known_n,
            "escalate": self.escalate,
            "pass_at_1": None if self.pass_at_1 is None else round(self.pass_at_1, 4),
            "usd_per_success": self.usd_per_success,
            "escalate_pct": None if self.escalate_pct is None else round(self.escalate_pct, 2),
            "ours_composite": None if self.ours_composite is None else round(self.ours_composite, 4),
            "rankable": self.rankable,
        }


def model_slug(model: str) -> str:
    raw = (model or "").strip().replace("/", "__").replace(":", "_")
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in raw) or "model"


def unique_artifact_rel(
    *,
    task: str,
    model: str,
    run_id: str,
    suffix: str,
    kind: str = "",
) -> str:
    """Exports/bench-{task}-{kind?}-{model}-{seed}{suffix} — unique per model+task+seed.

    Optional ``kind`` inserts a label after the task (e.g. stub / readme) so a
    single run can name two seeded files without colliding.
    """
    t = (task or "task").strip().replace("/", "-").replace(" ", "-")
    k = (kind or "").strip().replace("/", "-").replace(" ", "-")
    if k:
        t = f"{t}-{k}"
    ext = suffix if suffix.startswith(".") else f".{suffix}"
    rid = (run_id or "run").strip() or "run"
    return f"Exports/bench-{t}-{model_slug(model)}-{rid}{ext}"


def seed_in_text(text: str, seed: str) -> bool:
    s = (seed or "").strip()
    return bool(s) and s in (text or "")


def normalize_reported_cost(raw: Any, *, source: str = "openrouter") -> CostNorm:
    """Honest cost: missing or non-positive provider cost is unknown, not free."""
    if raw is None:
        return CostNorm(None, True, "unavailable")
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return CostNorm(None, True, "invalid")
    if val != val or val == float("inf") or val == float("-inf"):
        return CostNorm(None, True, "invalid")
    if val <= 0.0:
        return CostNorm(None, True, "cost_unknown")
    return CostNorm(val, False, source or "openrouter")


def _as_bool(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in {"1", "true", "yes", "on"}
    return bool(val)


def _row_seconds(row: dict[str, Any]) -> float:
    for key in ("elapsed_sec", "seconds"):
        try:
            return max(0.0, float(row.get(key) or 0.0))
        except (TypeError, ValueError):
            continue
    return 0.0


def _child_attempt_rows(row: dict[str, Any]) -> list[dict[str, Any]]:
    raw = row.get("attempts")
    if not isinstance(raw, list) or not raw:
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        # Prevent recursive re-fold of an already-folded parent.
        child = {k: v for k, v in item.items() if k != "attempts"}
        out.append(child)
    return out


def score_task(row: dict[str, Any]) -> dict[str, Any]:
    """Per-task contribution. Failure → 0 successes; known spend still counts.

    Nested ``attempts`` (fail-then-escalate) are billed in full: every
    known USD stays in the denominator. Provider $0 on any attempt →
    cost_unknown for the whole row.
    """
    children = _child_attempt_rows(row)
    if children:
        parts = [score_task(child) for child in children]
        unknown = any(p["cost_unknown"] for p in parts)
        billed_parts = [p["cost_usd"] for p in parts if not p["cost_unknown"] and p["cost_usd"] is not None]
        billed = None if unknown else round(sum(billed_parts), 8)
        escalate = 1 if (
            _as_bool(row.get("escalate"))
            or any(p["escalate"] for p in parts)
            or len(parts) > 1
        ) else 0
        return {
            "ok": 1 if _as_bool(row.get("ok")) else 0,
            "seconds": sum(p["seconds"] for p in parts),
            "cost_usd": billed,
            "cost_unknown": unknown,
            "cost_source": "attempts" if not unknown else "cost_unknown",
            "escalate": escalate,
        }

    ok = _as_bool(row.get("ok"))
    flagged_unknown = row.get("cost_unknown") is True
    if flagged_unknown:
        billed = None
        unknown = True
        source = str(row.get("cost_source") or "cost_unknown")
    else:
        norm = normalize_reported_cost(row.get("cost_usd"), source=str(row.get("cost_source") or "openrouter"))
        billed = norm.cost_usd
        unknown = norm.cost_unknown
        source = norm.cost_source
    return {
        "ok": 1 if ok else 0,
        "seconds": _row_seconds(row),
        "cost_usd": billed,
        "cost_unknown": unknown,
        "cost_source": source,
        "escalate": 1 if _as_bool(row.get("escalate")) else 0,
    }


def fold_attempt_rows(
    attempts: list[dict[str, Any]],
    *,
    model: str,
    task: str,
) -> dict[str, Any]:
    """Fold cheap-fail + escalate-retry into one scorecard row.

    Retries stay on the row under ``attempts`` (not hidden). USD is the
    sum of every attempt. The starting (cheap) model owns the row.
    """
    cleaned = [dict(a) for a in attempts if isinstance(a, dict)]
    if not cleaned:
        return {
            "model": model,
            "task": task,
            "ok": False,
            "elapsed_sec": 0.0,
            "status": "error",
            "artifact": None,
            "artifact_bytes": 0,
            "cost_usd": None,
            "cost_unknown": True,
            "cost_source": "unavailable",
            "escalate": False,
            "summary": "",
            "heuristics_pass": False,
            "run_id": "",
            "seed": "",
            "tools_used": [],
            "attempts": [],
            "attempt_count": 0,
            "escalated_to": None,
            "parent_cost_usd": None,
            "child_cost_usd": 0.0,
            "models_used": [model] if model else [],
            "who_did_what": "",
            "depth": 0,
            "agent_count": 1,
        }
    last = cleaned[-1]
    escalated = len(cleaned) > 1
    stronger = str(last.get("model") or "") if escalated else None
    folded = {
        "model": model,
        "task": task,
        "ok": _as_bool(last.get("ok")),
        "elapsed_sec": sum(_row_seconds(a) for a in cleaned),
        "status": last.get("status") or ("done" if last.get("ok") else "failed"),
        "artifact": last.get("artifact"),
        "artifact_bytes": int(last.get("artifact_bytes") or 0),
        "escalate": escalated or _as_bool(last.get("escalate")),
        "summary": last.get("summary") or "",
        "heuristics_pass": _as_bool(last.get("heuristics_pass")),
        "run_id": str(last.get("run_id") or cleaned[0].get("run_id") or ""),
        "seed": str(last.get("seed") or cleaned[0].get("seed") or ""),
        "tools_used": list(last.get("tools_used") or []),
        "attempts": cleaned,
        "attempt_count": len(cleaned),
        "escalated_to": stronger or None,
        "parent_cost_usd": last.get("parent_cost_usd"),
        "child_cost_usd": last.get("child_cost_usd", 0.0),
        "models_used": list(last.get("models_used") or ([model] if model else [])),
        "who_did_what": str(last.get("who_did_what") or ""),
        "depth": int(last.get("depth") or 0),
        "agent_count": int(last.get("agent_count") or 1),
    }
    scored = score_task(folded)
    folded["cost_usd"] = scored["cost_usd"]
    folded["cost_unknown"] = scored["cost_unknown"]
    folded["cost_source"] = scored["cost_source"]
    return folded


def aggregate_model_index(model: str, rows: list[dict[str, Any]]) -> ModelIndexRow:
    scored = [score_task(r) for r in rows]
    ok_n = sum(s["ok"] for s in scored)
    n = len(scored)
    seconds = sum(s["seconds"] for s in scored)
    known = [s for s in scored if not s["cost_unknown"] and s["cost_usd"] is not None]
    known_n = len(known)
    all_unknown = known_n == 0
    billed_parts = [s["cost_usd"] for s in known]
    cost_usd = None if all_unknown else round(sum(billed_parts), 8)
    known_ok = sum(s["ok"] for s in known)
    known_seconds = sum(s["seconds"] for s in known)
    escalate = sum(s["escalate"] for s in scored)
    pass_at_1 = (ok_n / n) if n else None
    escalate_pct = (100.0 * escalate / n) if n else None
    usd_per_success: float | None = None
    # Known-cost rows only. Failures among those rows stay in the $ sum.
    if (not all_unknown) and cost_usd is not None and known_ok > 0:
        usd_per_success = cost_usd / known_ok
    rankable = (not all_unknown) and n > 0
    ours: float | None = None
    if rankable and cost_usd is not None:
        denom = cost_usd + TIME_PENALTY_USD_PER_SEC * known_seconds
        if denom > 0:
            ours = known_ok / denom
        elif known_ok == 0:
            ours = 0.0
    return ModelIndexRow(
        model=model,
        ok=ok_n,
        n=n,
        seconds=seconds,
        cost_usd=cost_usd,
        cost_unknown=all_unknown,
        known_n=known_n,
        escalate=escalate,
        pass_at_1=pass_at_1,
        usd_per_success=usd_per_success,
        escalate_pct=escalate_pct,
        ours_composite=ours,
        rankable=rankable,
    )


def score_suite(results: list[dict[str, Any]]) -> list[ModelIndexRow]:
    """Roll up per-task rows. Rankable first, then lower $ per success."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in results:
        if not isinstance(row, dict):
            continue
        model = str(row.get("model") or "").strip()
        if not model:
            continue
        grouped.setdefault(model, []).append(row)
    rolled = [aggregate_model_index(m, rows) for m, rows in grouped.items()]

    def _sort_key(r: ModelIndexRow) -> tuple[int, float, float, str]:
        # rankable + cheaper $ per success first; optional composite as tie-break
        if r.rankable and r.usd_per_success is not None:
            comp = -(r.ours_composite or 0.0)
            return (0, r.usd_per_success, comp, r.model)
        if r.rankable and r.ours_composite is not None:
            return (1, -r.ours_composite, 0.0, r.model)
        return (2, 0.0, 0.0, r.model)

    rolled.sort(key=_sort_key)
    return rolled


def _parse_by_model(raw: dict[str, Any]) -> ModelIndexRow | None:
    model = str(raw.get("model") or "").strip()
    if not model:
        return None
    n = int(raw.get("n") or 0)
    ok = int(raw.get("ok") or 0)
    ours = raw.get("ours_composite", raw.get("index"))
    usd = raw.get("usd_per_success")
    p1 = raw.get("pass_at_1")
    ep = raw.get("escalate_pct")
    unknown = bool(raw.get("cost_unknown"))
    if "known_n" in raw:
        known_n = int(raw.get("known_n") or 0)
    else:
        known_n = 0 if unknown else n
    rankable = bool(raw.get("rankable")) if "rankable" in raw else (not unknown and n > 0)
    return ModelIndexRow(
        model=model,
        ok=ok,
        n=n,
        seconds=float(raw.get("seconds") or 0),
        cost_usd=raw.get("cost_usd") if isinstance(raw.get("cost_usd"), (int, float)) else None,
        cost_unknown=unknown,
        known_n=known_n,
        escalate=int(raw.get("escalate") or 0),
        pass_at_1=float(p1) if isinstance(p1, (int, float)) else ((ok / n) if n else None),
        usd_per_success=float(usd) if isinstance(usd, (int, float)) else None,
        escalate_pct=float(ep) if isinstance(ep, (int, float)) else ((100.0 * int(raw.get("escalate") or 0) / n) if n else None),
        ours_composite=float(ours) if isinstance(ours, (int, float)) else None,
        rankable=rankable,
    )


def _rows_from_index(data: dict[str, Any]) -> list[ModelIndexRow]:
    results = data.get("results")
    if isinstance(results, list) and results:
        return score_suite(results)
    by_model = data.get("by_model")
    if not isinstance(by_model, list):
        return []
    rows: list[ModelIndexRow] = []
    for raw in by_model:
        if isinstance(raw, dict):
            parsed = _parse_by_model(raw)
            if parsed:
                rows.append(parsed)
    return rows


def _usable_for_router(row: ModelIndexRow) -> bool:
    if "auto" in row.model.lower():
        return False
    return row.ok > 0


def _has_usd_per_success(row: ModelIndexRow) -> bool:
    return (not row.cost_unknown) and row.usd_per_success is not None


def order_models_from_index(
    data: dict[str, Any],
    *,
    current_cheap: str | None = None,
) -> list[str]:
    """Escalate ladder from a scorecard.

    Models with pass@1 at least as good as the current cheap, ordered by
    lowest $ per success. Then remaining models: best pass@1, then cheapest.
    """
    return _order_models_for_router(_rows_from_index(data), current_cheap=current_cheap)


def _order_models_for_router(
    rows: list[ModelIndexRow],
    *,
    current_cheap: str | None = None,
) -> list[str]:
    usable = [r for r in rows if _usable_for_router(r)]
    if not usable:
        return []
    current = (current_cheap or "").strip()
    current_row = next((r for r in rows if r.model == current), None)
    threshold: float | None = None
    if current_row is not None and current_row.pass_at_1 is not None:
        threshold = current_row.pass_at_1

    def sort_key(r: ModelIndexRow) -> tuple[int, float, float, str]:
        has_usd = _has_usd_per_success(r)
        meets = (
            threshold is not None
            and (r.pass_at_1 or 0.0) >= threshold
            and has_usd
        )
        if meets:
            return (0, float(r.usd_per_success or 0.0), -(r.pass_at_1 or 0.0), r.model)
        usd = float(r.usd_per_success) if has_usd else float("inf")
        return (1, -(r.pass_at_1 or 0.0), usd, r.model)

    return [r.model for r in sorted(usable, key=sort_key)]


def preferred_cheap_from_index(
    data: dict[str, Any],
    *,
    current_cheap: str | None = None,
) -> str | None:
    """Cheap default from a scorecard.

    Lowest $ per success among models with pass@1 at least as good as the
    current cheap. If that set is empty, best pass@1 then cheapest.
    Models without known $ are never chosen when a priced alternative exists.
    """
    rows = _rows_from_index(data)
    ordered = _order_models_for_router(rows, current_cheap=current_cheap)
    by_name = {r.model: r for r in rows}
    for name in ordered:
        row = by_name.get(name)
        if row is not None and _has_usd_per_success(row):
            return name
    return None


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def resolve_index_path(repo_root: Path | None = None) -> Path:
    root = repo_root or Path.cwd()
    path = root / INDEX_LATEST
    if path.is_file():
        return path
    alt = Path(__file__).resolve().parents[2] / INDEX_LATEST
    return alt if alt.is_file() else path


def load_index_data(repo_root: Path | None = None) -> dict[str, Any]:
    return _read_json(resolve_index_path(repo_root))


def load_index_preferred_cheap(
    repo_root: Path | None = None,
    *,
    current_cheap: str | None = None,
) -> str | None:
    data = load_index_data(repo_root)
    if not data:
        return None
    return preferred_cheap_from_index(data, current_cheap=current_cheap)


def load_index_model_order(
    repo_root: Path | None = None,
    *,
    current_cheap: str | None = None,
) -> list[str]:
    data = load_index_data(repo_root)
    if not data:
        return []
    return order_models_from_index(data, current_cheap=current_cheap)


def index_payload(
    *,
    results: list[dict[str, Any]],
    run_id: str,
    created_at: float,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    by_model = score_suite(results)
    payload: dict[str, Any] = {
        "index_name": INDEX_NAME,
        "index_version": INDEX_VERSION,
        "headline_metrics": list(HEADLINE_METRICS),
        "ours_composite_formula": OURS_COMPOSITE_FORMULA,
        "time_penalty_usd_per_sec": TIME_PENALTY_USD_PER_SEC,
        "note": AA_NOTE,
        "created_at": created_at,
        "run_id": run_id,
        "seed": run_id,
        "results": results,
        "by_model": [row.to_dict() for row in by_model],
    }
    if extra:
        payload.update(extra)
    return payload
