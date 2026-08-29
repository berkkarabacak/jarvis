"""See the screen now: capture → vision describe (ORCH-371).

Describing the desktop does not wait for confirm. Click/type/scroll already
shipped (ORCH-368). The leftover proposal hook must never claim vision or
clicks are deferred / unimplemented.
"""

from __future__ import annotations

from app.llm.openrouter_attribution import openrouter_attribution_headers

import asyncio
import base64
import concurrent.futures
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("jarvis.screen_loop")


@dataclass
class ScreenProposal:
    proposal_id: str
    description: str
    proposed_action: str
    risk_tier: str = "L4"
    needs_confirm: bool = False
    screenshot_path: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        desc = self.description or ""
        if self.needs_confirm and self.proposed_action:
            prompt = (
                f"I see: {desc[:200]}. "
                f"I propose: {self.proposed_action}. "
                "Say confirm to proceed, or cancel."
            )
        else:
            prompt = desc[:400]
        return {
            "proposal_id": self.proposal_id,
            "description": desc,
            "proposed_action": self.proposed_action,
            "risk_tier": self.risk_tier,
            "needs_confirm": self.needs_confirm,
            "screenshot_path": self.screenshot_path,
            "user_prompt": prompt,
        }


_PENDING: dict[str, ScreenProposal] = {}


def pending_proposals() -> list[dict[str, Any]]:
    return [p.to_dict() for p in _PENDING.values()]


def get_proposal(proposal_id: str) -> ScreenProposal | None:
    return _PENDING.get(proposal_id)


def confirm_proposal(proposal_id: str, decision: str) -> dict[str, Any]:
    """Record confirm/cancel. Acting uses click/type/keys/scroll, not this hook."""
    prop = _PENDING.pop(proposal_id, None)
    if not prop:
        return {"ok": False, "error": "unknown or expired proposal_id"}
    dec = (decision or "").strip().lower()
    if dec in {"deny", "cancel", "no", "abort"}:
        return {
            "ok": True,
            "decision": "deny",
            "message": "Cancelled. No UI automation ran.",
            "proposal_id": proposal_id,
        }
    if dec not in {"approve", "confirm", "yes", "ok", "proceed"}:
        _PENDING[proposal_id] = prop
        return {"ok": False, "error": "decision must be confirm or cancel"}
    return {
        "ok": True,
        "decision": "approve",
        "acted": False,
        "message": (
            "Noted. Click, type, keys, and scroll are already available as tools "
            f"(proposed: {prop.proposed_action})."
        ),
        "proposal": prop.to_dict(),
    }


_DESTRUCTIVE_SCREEN_RE = re.compile(
    r"\b(save(?:\s+the\s+file)?|delete|overwrite|format|wipe|erase|uninstall)\b",
    re.I,
)


def screen_goal_needs_confirm(user_goal: str) -> bool:
    """Look / click / keys / close / news are not confirm. Destructive L4 still is."""
    goal = (user_goal or "").strip()
    if not goal:
        return False
    return bool(_DESTRUCTIVE_SCREEN_RE.search(goal))


def build_proposal_from_vision(
    *,
    description: str,
    user_goal: str = "",
    screenshot_path: str = "",
) -> ScreenProposal:
    desc = (description or "").strip() or "Desktop captured; no vision description."
    goal = (user_goal or "").strip()
    needs_confirm = screen_goal_needs_confirm(goal)
    if needs_confirm:
        action = f"Next UI step toward: {goal[:200]}"
    elif goal:
        action = f"Next UI step toward: {goal[:200]}"
    else:
        action = ""
    pid = "prop_" + uuid.uuid4().hex[:12]
    prop = ScreenProposal(
        proposal_id=pid,
        description=desc[:4000],
        proposed_action=action,
        needs_confirm=needs_confirm,
        screenshot_path=screenshot_path,
    )
    _PENDING[pid] = prop
    # cap pending
    if len(_PENDING) > 20:
        oldest = sorted(_PENDING.values(), key=lambda p: p.created_at)[:10]
        for o in oldest:
            _PENDING.pop(o.proposal_id, None)
    return prop


async def vision_describe_png(
    png_bytes: bytes,
    *,
    user_goal: str = "",
    http_post: Callable[..., Any] | None = None,
) -> str:
    """Call OpenRouter/OpenAI vision; return short description text."""
    if not png_bytes:
        return ""
    b64 = base64.b64encode(png_bytes).decode("ascii")
    # shrink if huge — still ok for many models under ~4MB b64
    if len(b64) > 3_500_000:
        return "Screenshot too large for vision; path saved only."

    if http_post is not None:
        try:
            data = await http_post()
            return (
                ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            )[:4000]
        except Exception as exc:
            log.warning("vision describe failed: %s", exc)
            return f"Vision error: {str(exc)[:180]}"

    key = (os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        return "Vision unavailable (no OPENROUTER_API_KEY / OPENAI_API_KEY)."

    model = (
        os.environ.get("JARVIS_VISION_MODEL")
        or "openai/gpt-4o-mini"
    ).strip()
    prompt = (
        "Describe what is visible on this desktop screenshot right now. "
        "Name the focused window, the page, and readable text. "
        "Do not tell the person how to press keys, close a tab, or click. "
        "Do not write how-to. Do not mention Ctrl+W. Do not ask them to confirm. "
        f"User goal: {user_goal[:300] or 'what is on the screen now'}."
    )
    # Prefer OpenRouter if key looks like it, else OpenAI
    use_or = key.startswith("sk-or-") or bool(os.environ.get("OPENROUTER_API_KEY"))
    if use_or and os.environ.get("OPENROUTER_API_KEY"):
        key = os.environ["OPENROUTER_API_KEY"].strip()
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            **openrouter_attribution_headers(),
        }
        body = {
            "model": model if "/" in model else f"openai/{model}",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        },
                    ],
                }
            ],
            "max_tokens": 400,
        }
    else:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        vis_model = os.environ.get("OPENAI_VISION_MODEL") or "gpt-4o-mini"
        body = {
            "model": vis_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        },
                    ],
                }
            ],
            "max_tokens": 400,
        }

    try:
        import httpx

        async def _default_post():
            async with httpx.AsyncClient(timeout=45.0) as client:
                r = await client.post(url, headers=headers, json=body)
                r.raise_for_status()
                return r.json()

        data = await (http_post() if http_post else _default_post())
        return (
            ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        )[:4000]
    except Exception as exc:
        log.warning("vision describe failed: %s", exc)
        return f"Vision error: {str(exc)[:180]}"


def png_bytes_from_shot(
    screenshot_result: dict[str, Any],
    workspace_root: Path,
) -> bytes:
    """Restore PNG bytes from the result or the saved file (b64 may be stripped)."""
    png = b""
    b64_full = screenshot_result.get("png_base64_full") or ""
    if not b64_full:
        raw_b64 = screenshot_result.get("png_base64") or ""
        if raw_b64 and not str(raw_b64).endswith("..."):
            b64_full = raw_b64
    if b64_full:
        try:
            png = base64.b64decode(b64_full)
        except Exception:
            png = b""
    rel = str(screenshot_result.get("path") or "")
    path = workspace_root / rel if rel else None
    if not png and path and path.is_file():
        try:
            png = path.read_bytes()[:2_000_000]
        except Exception:
            png = b""
    return png



def looks_like_jarvis_chat(description: str) -> bool:
    """Cheap hint: vision text looks like this Jarvis/Grok chat, not a website."""
    low = (description or "").lower()
    markers = ("company org", "plugins", "berk k", "jarvis chat", "grok chat")
    return sum(1 for m in markers if m in low) >= 2


def looks_like_blank_page(text: str) -> bool:
    """True when a WINDOW TITLE is still about:blank / empty / Untitled.

    A vision essay that mentions Restore pages / Leave this page is not blank.
    Those overlays sit on a real page — dismiss them, do not wipe the look.
    """
    from app.jarvis.desktop import is_dismissible_chrome_dialog, is_placeholder_title

    raw = (text or "").strip()
    if not raw:
        return False
    # HWND titles are short. Vision paragraphs must not use title needles.
    if len(raw) > 80 or raw.count(" ") > 10:
        return False
    if is_dismissible_chrome_dialog(raw):
        return False
    if "about:blank" in raw.lower():
        return True
    return is_placeholder_title(raw)


def classify_vision_text(desc: str) -> tuple[str, str | None]:
    """Split a vision helper string into (description, vision_error)."""
    text = (desc or "").strip()
    if not text:
        return "", "Vision returned no description."
    low = text.lower()
    if text.startswith("Vision error:") or text.startswith("Vision unavailable"):
        return "", text
    if text.startswith("Screenshot too large"):
        return "", text
    if "vision deferred" in low or "deferred in this version" in low:
        return "", text
    return text, None


def run_async_blocking(factory: Callable[[], Any], *, timeout: float = 90.0) -> Any:
    """Run an async factory from sync code, including inside a running event loop."""

    def _call() -> Any:
        return asyncio.run(factory())

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _call()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_call).result(timeout=timeout)


async def run_see_screen(
    screenshot_result: dict[str, Any],
    *,
    workspace_root: Path,
    user_goal: str = "",
    http_post: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Run vision NOW after a screenshot result. Describe-only looks skip the old v1 hook."""
    if not screenshot_result.get("ok"):
        return screenshot_result
    rel = str(screenshot_result.get("path") or "")
    png = png_bytes_from_shot(screenshot_result, workspace_root)

    from app.jarvis.capture import BLACK_FRAME_ERROR, is_near_black, look_has_http_url
    from app.jarvis.desktop import BLANK_PAGE_ERROR

    shot_title = str(screenshot_result.get("title") or "")
    title_is_placeholder = looks_like_blank_page(shot_title)
    # Restore pages? is a dialog on a live session, not an unloaded tab.
    # Do not refuse the look — caller dismisses, then looks again.
    if (
        look_has_http_url(goal=user_goal, title=shot_title)
        and title_is_placeholder
        and "about:blank" in shot_title.lower()
    ):
        out = dict(screenshot_result)
        out.pop("png_base64_full", None)
        out.pop("png_base64", None)
        out["ok"] = False
        out["page_ready"] = False
        out["vision_description"] = ""
        out["error"] = BLANK_PAGE_ERROR
        out["note"] = BLANK_PAGE_ERROR
        out["hint"] = BLANK_PAGE_ERROR
        out["screen_loop"] = "see_describe"
        return out

    if screenshot_result.get("black_frame") or (png and is_near_black(png)):
        out = dict(screenshot_result)
        out.pop("png_base64_full", None)
        out.pop("png_base64", None)
        out["ok"] = False
        out["black_frame"] = True
        out["vision_description"] = ""
        out["vision_error"] = BLACK_FRAME_ERROR
        out["error"] = BLACK_FRAME_ERROR
        out["screen_loop"] = "see_describe"
        return out

    raw = await vision_describe_png(png, user_goal=user_goal, http_post=http_post)
    desc, vis_err = classify_vision_text(raw)
    if not desc and not vis_err and not png:
        vis_err = "Vision error: screenshot bytes missing; could not describe the screen."

    out = dict(screenshot_result)
    out.pop("png_base64_full", None)
    out.pop("png_base64", None)
    if vis_err:
        out["ok"] = False
        out["vision_description"] = ""
        out["vision_error"] = vis_err
        out["error"] = vis_err
        out["screen_loop"] = "see_describe"
        return out

    out["vision_description"] = desc
    # HWND title is the source of truth. A real page title (Example Domain)
    # is not blank even if vision mentions a leave-page / Restore overlay.
    # Never wipe a real vision essay — hosted Talk often has an empty title
    # (full-desktop grab) and a Restore pages bubble on a live BBC/Reuters tab.
    if (
        look_has_http_url(goal=user_goal, title=shot_title)
        and looks_like_blank_page(desc)
        and (not shot_title or title_is_placeholder)
        and len(desc) < 80
    ):
        out["ok"] = False
        out["page_ready"] = False
        out["looks_like_blank_page"] = True
        out["vision_description"] = ""
        out["error"] = BLANK_PAGE_ERROR
        out["note"] = BLANK_PAGE_ERROR
        out["hint"] = BLANK_PAGE_ERROR
        out["screen_loop"] = "see_describe"
        return out
    if looks_like_jarvis_chat(desc):
        out["looks_like_wrong_window"] = True
        out["hint"] = (
            "This looks like the Jarvis chat, not the target page. "
            "Do not type a URL into this chat. Open the URL with run_app "
            "first, then look. Then focus_app chrome and see_screen again. "
            "If focus_app finds no Chrome window, retry run_app — do not "
            "ask the user to click Chrome. "
            "If you need the Chrome address bar, click near the top of the "
            "Chrome window, not the message box at the bottom."
        )
    goal = (user_goal or "").strip()
    # Public look / click / keys / close / news must not return an L4 confirm.
    if goal and screen_goal_needs_confirm(goal):
        prop = build_proposal_from_vision(
            description=desc,
            user_goal=goal,
            screenshot_path=rel,
        )
        out["proposal"] = prop.to_dict()
    out["screen_loop"] = "see_describe"
    return out


# ---------------------------------------------------------------------------
# ORCH-367: look -> act -> look while a desktop job runs
# ---------------------------------------------------------------------------

DESKTOP_ACT_TOOLS = frozenset({"click", "type", "keys", "scroll"})
DESKTOP_JOB_TOOLS = frozenset(
    {"click", "type", "keys", "scroll", "screenshot", "see_screen", "run_app", "focus_app"}
)


def normalize_look_speed(raw: str | None) -> str:
    try:
        from app.jarvis.settings_store import _normalize_look_speed

        parsed = _normalize_look_speed(raw)
        if parsed:
            return parsed
    except Exception:
        pass
    s = (raw or "off").strip().lower()
    aliases = {"30": "30s", "10": "10s", "1": "1s", "0": "off", "none": "off"}
    s = aliases.get(s, s)
    return s if s in {"off", "30s", "10s", "1s"} else "off"


class LookLoop:
    """Decide when to capture the screen during a desktop job.

    off: one look to aim, then batch click/type/keys without another screenshot.
    1s / 10s / 30s: look at the start of a desktop job, then again when
    that many seconds have passed.
    """

    def __init__(
        self,
        speed: str = "off",
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.speed = normalize_look_speed(speed)
        self._clock = clock or time.monotonic
        self._last_look: float | None = None
        self.desktop = False
        self.looks = 0

    @property
    def interval(self) -> float | None:
        try:
            from app.jarvis.settings_store import LOOK_SPEED_INTERVALS

            return LOOK_SPEED_INTERVALS.get(self.speed)
        except Exception:
            return {"off": None, "30s": 30.0, "10s": 10.0, "1s": 1.0}.get(self.speed)

    def note_tool(self, name: str) -> None:
        if (name or "").strip() in DESKTOP_JOB_TOOLS:
            self.desktop = True

    def should_look(self, *, next_action_needs_shot: bool = False) -> bool:
        interval = self.interval
        if interval is None:
            # Already have a picture — click/type/keys in a burst, no new shot.
            if self._last_look is not None:
                return False
            return bool(next_action_needs_shot)
        if self._last_look is None:
            return True
        return (float(self._clock()) - self._last_look) >= float(interval)

    def mark_looked(self) -> None:
        self._last_look = float(self._clock())
        self.looks += 1


def look_decision(loop: LookLoop, tool_name: str) -> bool:
    """True when this tool should be preceded by a screen look."""
    name = (tool_name or "").strip()
    loop.note_tool(name)
    if not loop.desktop:
        return False
    if name in {"screenshot", "see_screen", "focus_app"}:
        return False
    return loop.should_look(next_action_needs_shot=name in DESKTOP_ACT_TOOLS)


def look_loop_from_settings(
    root: Path | None = None,
    *,
    clock: Callable[[], float] | None = None,
) -> LookLoop:
    try:
        from app.jarvis.settings_store import get_look_speed

        speed = get_look_speed(root)
    except Exception:
        speed = "off"
    return LookLoop(speed, clock=clock)
