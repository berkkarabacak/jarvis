"""ORCH-313 — usage/settings overlay contract.

Reads app/static/ceo.html straight from disk so it needs no ASGI client and no
app config (the baseline's test_ceo_home fixture is red for unrelated reasons,
ORCH-312). This asserts the overlay's contract: present, self-contained,
transparent, honest about the estimate, and observing the real usage source.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CEO = Path(__file__).resolve().parents[1] / "app" / "static" / "ceo.html"
HTML = CEO.read_text(encoding="utf-8")

START = "<!-- iris-usage-overlay ORCH-313 start -->"
END = "<!-- iris-usage-overlay ORCH-313 end -->"


@pytest.fixture(scope="module")
def block() -> str:
    assert START in HTML and END in HTML, "overlay markers missing"
    return HTML[HTML.index(START): HTML.index(END) + len(END)]


def test_overlay_is_injected_once(block: str):
    assert HTML.count(START) == 1 and HTML.count(END) == 1
    # It lives in the head, before the body opens.
    assert HTML.index(START) < HTML.index("<body")


def test_default_state_shows_nothing(block: str):
    # The usage menu starts fully transparent; pointer proximity reveals it.
    # There is no leftover #iu-gear Settings/usage control.
    assert "#iu-menu {" in block and "opacity: 0;" in block
    assert "body.iu-open #iu-menu" in block           # menu opens on hover
    assert 'gear.id = "iu-gear"' not in block
    assert 'id = "iu-gear"' not in block
    assert "#iu-gear {" not in block


def test_reveal_is_by_pointer_position_not_a_blocking_hitbox(block: str):
    # A blocking corner element would obscure the wallpaper and could swallow
    # the click-to-start gesture; reveal is driven by pointermove instead.
    assert "pointermove" in block
    assert "window.innerWidth - 180" in block
    assert "pointer-events: none;" in block           # hidden state cannot block


def test_everything_is_translucent_over_the_wallpaper(block: str):
    # No opaque backgrounds anywhere in the overlay.
    bg_decls = re.findall(r"background:\s*([^;]+);", block)
    assert bg_decls, "expected background declarations"
    for decl in bg_decls:
        d = decl.strip().lower()
        assert d.startswith("rgba("), f"non-translucent background: {decl!r}"
        alpha = float(d.rsplit(",", 1)[1].rstrip(") "))
        assert alpha < 0.4, f"background too opaque (alpha={alpha}): {decl!r}"


def test_usage_shows_real_tokens_and_a_labelled_estimate(block: str):
    assert 'id="iu-usage"' in block or "iu-usage" in block
    assert "≈ $" in block                              # the dollar figure is approximate
    assert "estimate" in block                          # and labelled as such
    # Real counts, not just a made-up number.
    assert "in ·" in block and "out ·" in block


def test_spend_comes_from_the_real_realtime_usage_events(block: str):
    assert "createDataChannel" in block                 # observe without editing connect()
    assert "response.done" in block
    assert "response.usage" in block
    assert "input_token_details" in block               # audio vs text breakdown


def test_overlay_is_self_contained(block: str):
    # No external requests, and dynamic text is set via textContent, never
    # parsed as markup. The connector form may show an example URL placeholder.
    live = block.replace('placeholder = "https://mcp.example/rpc"', "")
    assert "http://" not in live and "https://" not in live
    assert "innerHTML" not in block
    assert "IrisUsage" in block                          # test/automation seam


def test_ids_do_not_collide_with_the_page(block: str):
    # Everything is iu- prefixed; must not reuse the page's own ids.
    for page_id in ('id="wall"', 'id="dock"', 'id="orb"'):
        assert page_id not in block


def test_settings_panels_are_enabled(block: str):
    """Voice / Wallpaper / About are real panels, not "soon" stubs."""
    assert 'id="iu-voice"' in block or "iu-voice" in block
    assert 'id="iu-wall"' in block or "iu-wall" in block
    assert 'id="iu-about"' in block or "iu-about" in block
    assert "IrisSettings" in block
    # The three categories must not be disabled stubs.
    assert 'item("Voice", false)' not in block
    assert 'item("Wallpaper", false)' not in block
    assert 'item("About", false)' not in block
    # Voice chips include at least marin + alloy.
    assert "marin" in block and "alloy" in block
    # Wallpaper scenes + auto-rotate control.
    assert "Auto-rotate" in block
    assert "Coast" in block or "Dusk" in block


def test_settings_persist_via_local_storage(block: str):
    assert 'localStorage.getItem("iu-settings")' in block
    assert 'localStorage.setItem("iu-settings"' in block


def test_single_settings_control_is_top_right(block: str):
    assert block.count('id = "iu-settings-fab"') == 1
    assert 'item("Settings"' not in block
    assert 'gear.id = "iu-gear"' not in block
    assert "#iu-gear {" not in block
    fab = block[block.index("#iu-settings-fab {") : block.index("#iu-settings-fab:focus-visible")]
    assert "right: 16px" in fab
    assert "left: 16px" not in fab
    assert "left:" not in fab
    assert 'settingsFab.textContent = "Settings"' not in block
    assert 'settingsFab.textContent = "⚙"' in block
    assert 'setAttribute("aria-label", "Settings")' in block
    assert "border-radius: 50%" in fab


def test_hover_menu_rows_are_icon_first(block: str):
    assert "IU_ICONS" in block
    assert 'name.textContent = label' not in block
    assert 'setAttribute("aria-label", label)' in block
    assert 'setAttribute("title", label)' in block
    for label in ("Usage", "Voice", "Wallpaper", "About", "Open Jarvis's screen"):
        assert f'"{label}"' in block or f"'{label}'" in block
    assert 'closeBtn.textContent = "Close"' not in block
    assert 'closeBtn.textContent = "×"' in block
    assert 'setAttribute("aria-label", "Close")' in block
