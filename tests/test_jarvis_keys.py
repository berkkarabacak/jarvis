"""ORCH-391: keys sends real shortcuts. type still only types letters."""

from __future__ import annotations

import pytest

from app.jarvis.desktop import (
    KEYEVENTF_KEYUP,
    KEYEVENTF_UNICODE,
    VK_CONTROL,
    VK_MENU,
    VK_SHIFT,
    VK_TAB,
    is_chrome_tab_combo,
    keys,
    parse_hotkey,
    reset_input_backend,
    set_input_backend,
    type_text,
    unicode_type_events,
)
from app.jarvis.permissions import NO_CONFIRM_TOOLS, TOOL_TIERS, Tier, requires_confirm, skips_confirm
from app.jarvis.taint import ALLOW, BLOCK, UNTRUSTED_TOOLS, gate


@pytest.fixture
def jarvis_env(tmp_path, monkeypatch):
    ws = tmp_path / "Jarvis"
    ws.mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE", str(ws))
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    monkeypatch.setenv("JARVIS_MODEL", "openai/gpt-4.1-mini")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-secret-value-XXXX")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-secret-value-YYYY")
    monkeypatch.setenv("BRIDGE_TOKEN", "bridge-secret-value-ZZZZ")
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.delenv("PUBLIC_GUEST_PROFILE", raising=False)
    monkeypatch.delenv("JARVIS_PUBLIC_CLOUD", raising=False)
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://127.0.0.1:8787")

    import app.jarvis.gateway as gw
    from app.jarvis import settings_store
    from app.jarvis.capture import reset_look_target

    gw._gateway = None
    settings_store.reset_cache()
    reset_input_backend()
    reset_look_target()
    yield ws
    gw._gateway = None
    settings_store.reset_cache()
    reset_input_backend()
    reset_look_target()


def _fake_keys_backend(log):
    def click(**kwargs):
        log.append(("click", kwargs))
        return {"ok": True, **kwargs}

    def type_fn(**kwargs):
        log.append(("type", kwargs))
        return {"ok": True, "typed": len(kwargs.get("text") or "")}

    def keys_fn(**kwargs):
        log.append(("keys", kwargs))
        return {
            "ok": True,
            "combo": kwargs.get("combo"),
            "vk": kwargs.get("vk"),
            "events": kwargs.get("events"),
            "modifiers": kwargs.get("modifiers"),
            "key": kwargs.get("key"),
        }

    set_input_backend({"click": click, "type": type_fn, "keys": keys_fn})


# ---------------------------------------------------------------- parse


@pytest.mark.parametrize(
    "combo, modifiers, key, vk",
    [
        ("ctrl+tab", ["ctrl"], "tab", [VK_CONTROL, VK_TAB]),
        ("Ctrl+Tab", ["ctrl"], "tab", [VK_CONTROL, VK_TAB]),
        ("ctrl+shift+t", ["ctrl", "shift"], "t", [VK_CONTROL, VK_SHIFT, ord("T")]),
        ("ctrl+2", ["ctrl"], "2", [VK_CONTROL, ord("2")]),
        ("ctrl+l", ["ctrl"], "l", [VK_CONTROL, ord("L")]),
        ("ctrl+w", ["ctrl"], "w", [VK_CONTROL, ord("W")]),
        ("alt+tab", ["alt"], "tab", [VK_MENU, VK_TAB]),
        ("control+shift+t", ["ctrl", "shift"], "t", [VK_CONTROL, VK_SHIFT, ord("T")]),
    ],
)
def test_parse_hotkey_examples(combo, modifiers, key, vk):
    parsed = parse_hotkey(combo)
    assert parsed.get("ok") is True, parsed
    assert parsed["modifiers"] == modifiers
    assert parsed["key"] == key
    assert parsed["vk"] == vk


def test_parse_ctrl_tab_events_are_vk_down_up_not_unicode():
    parsed = parse_hotkey("ctrl+tab")
    assert parsed["ok"] is True
    events = parsed["events"]
    assert events == [
        (VK_CONTROL, 0),
        (VK_TAB, 0),
        (VK_TAB, KEYEVENTF_KEYUP),
        (VK_CONTROL, KEYEVENTF_KEYUP),
    ]
    assert all((flags & KEYEVENTF_UNICODE) == 0 for _vk, flags in events)


def test_parse_ctrl_shift_t_holds_ctrl_and_shift():
    parsed = parse_hotkey("ctrl+shift+t")
    assert parsed["ok"] is True
    events = parsed["events"]
    assert events[0] == (VK_CONTROL, 0)
    assert events[1] == (VK_SHIFT, 0)
    assert events[2] == (ord("T"), 0)
    assert events[3] == (ord("T"), KEYEVENTF_KEYUP)
    assert events[4] == (VK_SHIFT, KEYEVENTF_KEYUP)
    assert events[5] == (VK_CONTROL, KEYEVENTF_KEYUP)


def test_chrome_tab_combo_is_ctrl_tab_not_ctrl_l():
    assert is_chrome_tab_combo("ctrl+tab") is True
    assert is_chrome_tab_combo("ctrl+2") is True
    assert is_chrome_tab_combo("ctrl+shift+t") is True
    assert is_chrome_tab_combo("ctrl+w") is True
    assert is_chrome_tab_combo("ctrl+l") is False
    assert is_chrome_tab_combo("alt+tab") is False
    assert is_chrome_tab_combo("") is False
    from app.jarvis.desktop import is_close_all_combo

    assert is_close_all_combo("close-all") is True
    assert is_close_all_combo("close_all") is True
    assert is_close_all_combo("close-windows") is True
    assert is_close_all_combo("ctrl+w") is False
    assert is_close_all_combo("escape") is False


def test_parse_rejects_empty_and_unknown():
    assert parse_hotkey("")["ok"] is False
    assert parse_hotkey("ctrl+")["ok"] is False
    assert parse_hotkey("ctrl")["ok"] is False
    assert parse_hotkey("ctrl+shift")["ok"] is False
    assert parse_hotkey("ctrl+notakey")["ok"] is False
    assert parse_hotkey("ctrl+a+b")["ok"] is False


# -------------------------------------------------------- type stays text


def test_type_events_are_unicode_only_even_for_ctrl_tab():
    """type('ctrl+tab') would type those letters, not press Ctrl and Tab."""
    events = unicode_type_events("ctrl+tab")
    assert events
    for w_vk, w_scan, flags in events:
        assert w_vk == 0
        assert flags & KEYEVENTF_UNICODE
        assert w_scan != 0
    scans = [scan for _vk, scan, flags in events if not (flags & KEYEVENTF_KEYUP)]
    assert scans == [ord(ch) for ch in "ctrl+tab"]
    assert VK_CONTROL not in [w_vk for w_vk, _scan, _flags in events]
    assert VK_TAB not in [w_vk for w_vk, _scan, _flags in events]


def test_type_tool_does_not_parse_modifiers(jarvis_env):
    log = []
    _fake_keys_backend(log)
    result = type_text(text="ctrl+tab")
    assert result.get("ok") is True
    assert log == [("type", {"text": "ctrl+tab"})]
    assert "vk" not in log[0][1]


# -------------------------------------------------------- keys sends vk


def test_keys_ctrl_tab_sends_vk_control_and_vk_tab(jarvis_env):
    log = []
    _fake_keys_backend(log)
    result = keys(combo="ctrl+tab")
    assert result.get("ok") is True, result
    assert result["vk"] == [VK_CONTROL, VK_TAB]
    assert result["combo"] == "ctrl+tab"
    assert log[0][0] == "keys"
    sent = log[0][1]
    assert sent["vk"] == [VK_CONTROL, VK_TAB]
    assert sent["events"][0] == (VK_CONTROL, 0)
    assert sent["events"][1] == (VK_TAB, 0)
    assert all((flags & KEYEVENTF_UNICODE) == 0 for _vk, flags in sent["events"])


def test_keys_ctrl_shift_t_sends_ctrl_and_shift(jarvis_env):
    log = []
    _fake_keys_backend(log)
    result = keys(combo="ctrl+shift+t")
    assert result.get("ok") is True, result
    assert VK_CONTROL in result["vk"]
    assert VK_SHIFT in result["vk"]
    assert ord("T") in result["vk"]
    downs = [vk for vk, flags in result["events"] if flags == 0]
    assert downs == [VK_CONTROL, VK_SHIFT, ord("T")]


def test_keys_bad_combo_does_not_hit_backend(jarvis_env):
    log = []
    _fake_keys_backend(log)
    result = keys(combo="not-a-real-combo")
    assert result.get("ok") is False
    assert log == []


# ------------------------------------------- confirm / taint / wiring


def test_keys_no_needs_confirm_even_after_screenshot(jarvis_env):
    from app.jarvis.gateway import ToolGateway

    log = []
    _fake_keys_backend(log)
    g = ToolGateway()

    assert "keys" in NO_CONFIRM_TOOLS
    assert skips_confirm("keys")
    assert requires_confirm("keys", max_auto=Tier.L0) is False
    assert TOOL_TIERS["keys"] == Tier.L1

    g._tracker("test").observe("screenshot")
    assert g._tracker("test").tainted is True

    result = g.run("keys", {"combo": "ctrl+tab"}, source="test")
    assert result.get("ok") is True, result
    assert result.get("needs_confirm") in (None, False)
    assert "confirm_id" not in result
    assert "nonce_code" not in result
    assert result.get("vk") == [VK_CONTROL, VK_TAB]
    assert log[0][0] == "keys"


def test_keys_allowed_after_taint_powershell_still_blocked():
    assert "screenshot" in UNTRUSTED_TOOLS
    assert gate("keys", tainted=True, args={"combo": "ctrl+tab"}) == (ALLOW, "")
    assert gate("keys", tainted=True, args={"combo": "ctrl+shift+t"}) == (ALLOW, "")
    assert gate("keys", tainted=True, args={"combo": "ctrl+1"}) == (ALLOW, "")
    decision, reason = gate("run_powershell", True, args={"command": "SendKeys"})
    assert decision == BLOCK
    assert "untrusted" in reason


def test_look_then_keys_runs_and_powershell_stays_blocked(jarvis_env):
    from app.jarvis.gateway import ToolGateway

    log = []
    _fake_keys_backend(log)
    g = ToolGateway()
    g._tracker("test").observe("see_screen")
    assert g._tracker("test").tainted is True

    switched = g.run("keys", {"combo": "ctrl+tab"}, source="test")
    assert switched.get("ok") is True, switched
    assert switched.get("blocked") is not True
    assert switched.get("vk") == [VK_CONTROL, VK_TAB]

    blocked = g.run(
        "run_powershell",
        {"command": "[System.Windows.Forms.SendKeys]::SendWait('^{TAB}')"},
        source="test",
        confirmed=True,
    )
    assert blocked.get("ok") is False
    assert blocked.get("blocked") is True
    assert blocked.get("tainted") is True


def test_keys_in_specs_tiers_and_look_loop():
    from app.jarvis.realtime import tools_for_realtime
    from app.jarvis.screen_loop import DESKTOP_ACT_TOOLS, DESKTOP_JOB_TOOLS, LookLoop, look_decision
    from app.jarvis.tools import TOOL_SPECS

    names = {
        (spec.get("function") or {}).get("name")
        for spec in TOOL_SPECS
        if spec.get("type") == "function"
    }
    assert "keys" in names
    rt = {t["name"] for t in tools_for_realtime()}
    assert "keys" in rt
    assert "keys" in DESKTOP_ACT_TOOLS
    assert "keys" in DESKTOP_JOB_TOOLS

    off = LookLoop("off")
    assert look_decision(off, "keys") is True
    assert off.desktop is True


def test_prompts_say_use_keys_not_typed_letters():
    from app.jarvis.agent import SYSTEM_PROMPT
    from app.jarvis.realtime import JARVIS_REALTIME_INSTRUCTIONS

    for text in (SYSTEM_PROMPT, JARVIS_REALTIME_INSTRUCTIONS):
        low = text.lower()
        assert "keys" in low
        assert "ctrl+tab" in low
        assert "do not type the letters" in low
        assert "see_screen" in text
