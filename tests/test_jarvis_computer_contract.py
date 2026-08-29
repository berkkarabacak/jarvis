"""ORCH-401 / ORCH-402 / ORCH-403 / ORCH-404 / ORCH-405 / ORCH-406 / ORCH-410 — one cheap persistent Linux computer."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPUTER = ROOT / "deploy" / "jarvis-computer"
COMPOSE = COMPUTER / "docker-compose.yml"
DOCKERFILE = COMPUTER / "Dockerfile"
ENTRYPOINT = COMPUTER / "entrypoint.sh"
COMPUTER_README = COMPUTER / "README.md"
DOCS = ROOT / "docs" / "jarvis-computer.md"
SMOKE = ROOT / "scripts" / "smoke_jarvis_computer.sh"
PROOF = ROOT / "scripts" / "proof_jarvis_computer_notepad.py"
THEME = COMPUTER / "theme"
THEME_PANEL = THEME / "xfce-config" / "xfce4-panel.xml"
THEME_XFWM = THEME / "xfce-config" / "xfwm4.xml"
THEME_XSETTINGS = THEME / "xfce-config" / "xsettings.xml"
THEME_DESKTOP = THEME / "xfce-config" / "xfce4-desktop.xml"
APPS = COMPUTER / "apps"
CHROME_WRAPPER = COMPUTER / "bin" / "chrome"

REQUIRED_IMAGE_PACKAGES = (
    "chromium",
    "mousepad",
    "thunar",
    "xfce4-terminal",
    "galculator",
    "ristretto",
)

REMOTE_VIEW_PACKAGES = (
    "novnc",
    "x11vnc",
    "websockify",
)

FORBIDDEN_REMOTE_STACKS = (
    "kasmvnc",
    "kasmweb",
    "webtop",
)

DESKTOP_SHORTCUTS = (
    "chrome.desktop",
    "notepad.desktop",
    "files.desktop",
    "terminal.desktop",
    "calculator.desktop",
    "image-viewer.desktop",
)


def _compose_service_keys(text: str) -> list[str]:
    keys: list[str] = []
    in_services = False
    for line in text.splitlines():
        if line.startswith("services:"):
            in_services = True
            continue
        if in_services:
            if line and not line[0].isspace() and not line.startswith("#"):
                break
            if re.match(r"^  [A-Za-z0-9_-]+:\s*$", line):
                keys.append(line.strip().rstrip(":"))
    return keys


def test_definition_files_exist():
    assert DOCKERFILE.is_file()
    assert COMPOSE.is_file()
    assert ENTRYPOINT.is_file()
    assert COMPUTER_README.is_file()
    assert DOCS.is_file()
    assert SMOKE.is_file()
    assert PROOF.is_file()
    assert THEME.is_dir()
    assert APPS.is_dir()
    assert CHROME_WRAPPER.is_file()
    assert (COMPUTER / "novnc" / "index.html").is_file()


def test_one_linux_desktop_service():
    text = COMPOSE.read_text(encoding="utf-8")
    assert _compose_service_keys(text) == ["jarvis-computer"]
    assert "container_name: jarvis-computer" in text
    assert "hostname: jarvis-computer" in text
    assert text.count("container_name:") == 1
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert "FROM debian:bookworm-slim" in dockerfile
    assert "xvfb" in dockerfile
    assert "xfce4-session" in dockerfile
    assert "useradd" in dockerfile
    assert "jarvis" in dockerfile
    entry = ENTRYPOINT.read_text(encoding="utf-8")
    assert "Xvfb" in entry
    assert "startxfce4" in entry
    assert "/home/jarvis" in entry


def test_named_volume_persists_home():
    text = COMPOSE.read_text(encoding="utf-8")
    assert "jarvis-home:/home/jarvis" in text
    assert re.search(r"jarvis-home:\s*\n\s+name:\s+jarvis-computer-home", text)
    entry = ENTRYPOINT.read_text(encoding="utf-8")
    assert ".jarvis-computer-ready" in entry
    assert "chown -R jarvis:jarvis" in entry
    docs = DOCS.read_text(encoding="utf-8")
    assert "jarvis-computer-home" in docs
    assert "/home/jarvis" in docs
    assert "persist" in docs.lower()
    assert "down -v" in docs


def test_restart_policy_keeps_computer_up():
    text = COMPOSE.read_text(encoding="utf-8")
    assert "restart: unless-stopped" in text


def test_image_is_linux_not_windows():
    dockerfile = DOCKERFILE.read_text(encoding="utf-8").lower()
    assert "from debian:" in dockerfile
    assert "from mcr.microsoft.com/windows" not in dockerfile
    assert "from winamd64" not in dockerfile
    docs = (DOCS.read_text(encoding="utf-8") + COMPUTER_README.read_text(encoding="utf-8")).lower()
    assert "linux, not windows" in docs or "linux not windows" in docs


def test_windows_like_theme_files_exist():
    assert (THEME / "xfwm4" / "themerc").is_file()
    assert (THEME / "gtk-3.0" / "gtk.css").is_file()
    assert (THEME / "gtk-2.0" / "gtkrc").is_file()
    assert (THEME / "wallpaper.png").is_file()
    assert (THEME / "index.theme").is_file()
    assert (THEME / "icons" / "index.theme").is_file()
    assert (THEME / "icons" / "32x32" / "apps" / "start-here.png").is_file()
    assert (THEME / "icons" / "32x32" / "places" / "folder.png").is_file()
    assert THEME_PANEL.is_file()
    assert THEME_XFWM.is_file()
    assert THEME_XSETTINGS.is_file()
    assert THEME_DESKTOP.is_file()

    panel = THEME_PANEL.read_text(encoding="utf-8")
    assert "applicationsmenu" in panel
    assert "Start" in panel
    assert "tasklist" in panel
    assert "p=11" in panel
    assert "start-here" in panel

    xfwm = THEME_XFWM.read_text(encoding="utf-8")
    assert "JarvisWin" in xfwm
    assert "O|HMC" in xfwm

    xsettings = THEME_XSETTINGS.read_text(encoding="utf-8")
    assert "JarvisWin" in xsettings
    assert "IconThemeName" in xsettings

    desktop = THEME_DESKTOP.read_text(encoding="utf-8")
    assert "windows-like.png" in desktop
    assert "show-home" in desktop

    themerc = (THEME / "xfwm4" / "themerc").read_text(encoding="utf-8")
    assert "button_layout=O|HMC" in themerc
    assert "#FFFFFF" in themerc

    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert "jarvis-windows-theme" in dockerfile
    assert "JarvisWin" in dockerfile
    assert "windows-like.png" in dockerfile
    entry = ENTRYPOINT.read_text(encoding="utf-8")
    assert ".jarvis-windows-theme-ready" in entry
    assert "xfce4-panel.xml" in entry


def test_image_ships_basic_apps():
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    dockerfile_low = dockerfile.lower()
    for word in REQUIRED_IMAGE_PACKAGES:
        assert word in dockerfile_low, f"{word} must be installed in the image"
    assert "google-chrome" not in dockerfile_low
    assert "dl.google.com" not in dockerfile_low

    wrapper = CHROME_WRAPPER.read_text(encoding="utf-8")
    assert "chromium" in wrapper
    assert "exec chromium" in wrapper

    expected_exec = {
        "chrome.desktop": "chrome",
        "notepad.desktop": "mousepad",
        "files.desktop": "thunar",
        "terminal.desktop": "xfce4-terminal",
        "calculator.desktop": "galculator",
        "image-viewer.desktop": "ristretto",
    }
    for name in DESKTOP_SHORTCUTS:
        path = APPS / name
        assert path.is_file(), name
        text = path.read_text(encoding="utf-8")
        assert "Type=Application" in text
        assert f"Exec={expected_exec[name]}" in text

    assert "jarvis-computer/apps" in dockerfile
    assert "/usr/share/applications" in dockerfile
    assert "/usr/local/bin/chrome" in dockerfile

    entry = ENTRYPOINT.read_text(encoding="utf-8")
    assert ".jarvis-apps-ready" in entry
    assert "Desktop" in entry
    assert "*.desktop" in entry
    for launch in ("chromium &", "mousepad &", "thunar &", "galculator &", "ristretto &"):
        assert launch not in entry


def test_remote_view_is_localhost_novnc():
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    dockerfile_low = dockerfile.lower()
    for word in REMOTE_VIEW_PACKAGES:
        assert word in dockerfile_low, f"{word} must be in the image for ORCH-404"
    assert "x11vnc" in dockerfile_low or "tigervnc" in dockerfile_low
    assert "/usr/share/novnc/index.html" in dockerfile
    for word in FORBIDDEN_REMOTE_STACKS:
        assert word not in dockerfile_low, f"{word} is a heavier stack than noVNC"

    compose = COMPOSE.read_text(encoding="utf-8")
    assert "ports:" in compose
    assert "127.0.0.1:6080:6080" in compose
    assert "0.0.0.0" not in compose
    assert "local-only" in compose.lower() or "localhost only" in compose.lower()
    assert re.search(r"5900\s*:", compose) is None

    entry = ENTRYPOINT.read_text(encoding="utf-8")
    entry_low = entry.lower()
    assert "x11vnc" in entry_low
    assert "websockify" in entry_low
    assert "/usr/share/novnc" in entry
    assert "6080" in entry
    assert "127.0.0.1" in entry
    assert "-viewonly" not in entry_low
    assert "see_screen" not in entry_low
    assert "-display" in entry_low
    assert "$display" in entry_low or ":1" in entry

    index = (COMPUTER / "novnc" / "index.html").read_text(encoding="utf-8")
    assert "vnc.html" in index
    assert "autoconnect=1" in index

    theme_text = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (THEME_PANEL, THEME_XFWM, THEME_XSETTINGS, THEME_DESKTOP)
    ).lower()
    for word in ("novnc", "tigervnc", "x11vnc", "kasmvnc"):
        assert word not in theme_text


def test_orch405_helpers_exist_and_do_not_spawn():
    computer = ROOT / "app" / "jarvis" / "computer.py"
    assert computer.is_file()
    text = computer.read_text(encoding="utf-8")
    assert "JARVIS_COMPUTER" in text
    assert "docker exec" in text
    assert "xdotool" in text
    assert "scrot" in text
    assert "DISPLAY" in text
    assert '["docker", "run"]' not in text
    assert "docker compose up -d" not in text
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert "xdotool" in dockerfile
    assert "scrot" in dockerfile
    compose = COMPOSE.read_text(encoding="utf-8")
    assert compose.count("container_name:") == 1
    assert "127.0.0.1:6080:6080" in compose
    assert compose.count("6080") >= 1
    children = (ROOT / "app" / "jarvis" / "children.py").read_text(encoding="utf-8")
    assert "docker compose" not in children
    assert "docker run" not in children


def test_this_slice_does_not_ship_later_tickets():
    dockerfile = DOCKERFILE.read_text(encoding="utf-8").lower()
    for word in FORBIDDEN_REMOTE_STACKS:
        assert word not in dockerfile, f"{word} belongs to a rejected stack"
    compose = COMPOSE.read_text(encoding="utf-8").lower()
    for word in FORBIDDEN_REMOTE_STACKS:
        assert word not in compose
    entry = ENTRYPOINT.read_text(encoding="utf-8").lower()
    for word in FORBIDDEN_REMOTE_STACKS:
        assert word not in entry
    assert "see_screen" not in entry
    assert "mousepad &" not in entry


def test_docs_explain_start_stop_and_scope():
    combined = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (DOCS, COMPUTER_README, ROOT / "README.md", ROOT / "docs" / "jarvis.md")
    )
    low = combined.lower()
    assert "docker compose up" in combined
    assert "docker compose stop" in combined
    assert "one computer" in low or "one cheap persistent linux" in low
    assert "not one per sub-agent" in low or "not one per subagent" in low
    assert "ORCH-402" in combined
    assert "ORCH-403" in combined
    assert "ORCH-404" in combined
    assert "ORCH-405" in combined
    assert "ORCH-406" in combined
    assert "ORCH-410" in combined
    assert "http://127.0.0.1:6080" in combined
    assert "Open Jarvis's screen" in combined
    assert "chrome" in low
    assert "notepad" in low
    assert "windows-look" in low or "looks like windows" in low or "windows-like" in low
    assert "taskbar" in low
    assert "start" in low
    assert "user" in low and ("watch" in low or "see and use" in low)
    assert "ORCH-381" in combined
    docs = DOCS.read_text(encoding="utf-8")
    assert "ORCH-402" in docs
    assert "ORCH-403" in docs
    assert "ORCH-404" in docs
    assert "Windows-like XFCE" in docs or "windows-like XFCE" in docs
    assert "chromium" in docs.lower() or "chrome" in docs.lower()
    assert "http://127.0.0.1:6080" in docs
    assert "novnc" in docs.lower()
    later = docs.split("## Later tickets")[-1].split("## ")[0]
    assert "ORCH-404" not in later
    assert "ORCH-405" not in later
    assert "ORCH-406" not in later
    assert "ORCH-410" not in later
    assert "ORCH-402" not in later
    assert "ORCH-403" not in later
    assert "ORCH-405" in docs
    assert "ORCH-406" in docs
    assert "ORCH-410" in docs
    assert "Open Jarvis's screen" in docs
    assert "proof_jarvis_computer_notepad" in docs
    assert "refuses to invent" in docs.lower() or "refusing to invent" in docs.lower()
    assert "xdotool" in docs.lower() or "docker exec" in docs.lower()
    proof = PROOF.read_text(encoding="utf-8")
    assert "ORCH-406" in proof
    assert "refusing to invent a screenshot" in proof
    assert "plan_linux_run_app" in proof
    assert "linux_type" in proof


def test_distinct_from_user_windows_android():
    docs = DOCS.read_text(encoding="utf-8")
    assert "ORCH-381" in docs
    assert "Windows/Android" in docs or "Windows or Android" in docs
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "jarvis-computer" in readme
    assert "ORCH-401" in readme


def test_smoke_script_passes_without_a_live_vm():
    assert SMOKE.is_file()
    script = SMOKE.read_text(encoding="utf-8")
    assert "No GPU" in script or "no cloud VM" in script.lower()
    assert "docker compose config" in script or "compose config" in script
    result = subprocess.run(
        ["bash", str(SMOKE)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ORCH-401 smoke: OK" in result.stdout
    assert "ORCH-403" in result.stdout
    assert "ORCH-404" in result.stdout
    assert "ORCH-405" in result.stdout
    assert "ORCH-406" in result.stdout
    assert "ORCH-410" in result.stdout


def test_compose_config_when_docker_available():
    if shutil.which("docker") is None:
        return
    probe = subprocess.run(
        ["docker", "compose", "version"],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        return
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE), "--project-directory", str(COMPUTER), "config"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "jarvis-computer" in result.stdout
    assert "jarvis-computer-home" in result.stdout
    assert "/home/jarvis" in result.stdout
    assert "6080" in result.stdout
    assert "127.0.0.1" in result.stdout
