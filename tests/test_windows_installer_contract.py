"""ORCH-359 — installer scripts and first-run UI stay in-repo (no fake exe)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "scripts" / "windows"
DESKTOP = ROOT / "desktop"


def _embeddable_pth():
    path = WINDOWS / "embeddable_pth.py"
    spec = importlib.util.spec_from_file_location("embeddable_pth", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_installer_build_script_is_the_source_of_truth():
    ps1 = (WINDOWS / "build-installer.ps1").read_text(encoding="utf-8")
    assert "Jarvis-Setup.exe" in ps1
    assert "python.org/ftp/python" in ps1
    assert "embed-amd64.zip" in ps1
    assert "electron-builder" in ps1
    assert "electron-builder.installer.yml" in ps1
    assert "Windows_NT" in ps1
    assert "get-pip.py" in ps1
    assert "embeddable_pth.py" in ps1
    assert "LOCALAPPDATA" not in ps1 or "installer-payload" in ps1
    sh = (WINDOWS / "build-installer.sh").read_text(encoding="utf-8")
    assert "Windows" in sh
    assert "exit 1" in sh
    assert (WINDOWS / "embeddable_pth.py").is_file()


def test_installer_nsis_is_one_click_named_jarvis():
    yml = (DESKTOP / "electron-builder.installer.yml").read_text(encoding="utf-8")
    assert "productName: Jarvis" in yml
    assert "oneClick: true" in yml
    assert "shortcutName: Jarvis" in yml
    assert "Jarvis-Setup.${ext}" in yml
    assert "installer-payload/python" in yml
    assert "installer-payload/backend" in yml
    assert "packaged-python.js" in yml
    nsh = (DESKTOP / "nsis" / "jarvis-install-dir.nsh").read_text(encoding="utf-8")
    assert r"$LOCALAPPDATA\Jarvis" in nsh


XPS13_PYTHON312_PTH = (
    "python312.zip\n"
    ".\n"
    "\n"
    "# Uncomment to run site.main() automatically\n"
    "import site\n"
)


def test_xps13_python312_pth_gets_backend_root():
    mod = _embeddable_pth()
    out = mod.rewrite_embeddable_pth(XPS13_PYTHON312_PTH)
    lines = out.splitlines()
    assert lines[0] == "python312.zip"
    assert "." in lines
    assert "../backend" in lines
    assert "import site" in lines
    assert lines.index("../backend") < lines.index("import site")
    assert XPS13_PYTHON312_PTH.splitlines().count("import site") == 1


def test_embeddable_pth_adds_backend_and_uncomments_site():
    mod = _embeddable_pth()
    raw = (
        "python312.zip\n"
        ".\n"
        "\n"
        "# Uncomment to run site.main() automatically\n"
        "#import site\n"
    )
    out = mod.rewrite_embeddable_pth(raw)
    assert "../backend" in out.splitlines()
    assert "import site" in out.splitlines()
    assert "#import site" not in out.splitlines()
    assert out.splitlines().index("../backend") < out.splitlines().index("import site")


def test_embeddable_pth_is_idempotent_and_preserves_crlf(tmp_path):
    mod = _embeddable_pth()
    raw = "python312.zip\r\n.\r\nimport site\r\n"
    once = mod.rewrite_embeddable_pth(raw)
    twice = mod.rewrite_embeddable_pth(once)
    assert once == twice
    assert once.count("../backend") == 1
    assert "\r\n" in once
    pth = tmp_path / "python312._pth"
    pth.write_bytes(raw.encode("utf-8"))
    mod.apply_embeddable_pth(pth)
    text = pth.read_bytes().decode("utf-8")
    assert "../backend" in text
    assert "import site" in text
    assert "\r\n" in text


def test_embeddable_pth_cli_rewrites_file(tmp_path):
    pth = tmp_path / "python312._pth"
    pth.write_text("python312.zip\n.\n#import site\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(WINDOWS / "embeddable_pth.py"), str(pth)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    text = pth.read_text(encoding="utf-8")
    assert "../backend" in text
    assert "import site" in text.splitlines()


def test_isolated_python_imports_app_only_when_backend_on_path():
    isolated_env = {**os.environ, "PYTHONPATH": str(ROOT)}
    missing = subprocess.run(
        [sys.executable, "-I", "-c", "import app"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=isolated_env,
        check=False,
    )
    assert missing.returncode != 0
    assert "No module named 'app'" in (missing.stderr + missing.stdout)

    ok = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); import app",
            str(ROOT),
        ],
        cwd=str(Path.cwd().anchor or "/"),
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": ""},
        check=False,
    )
    assert ok.returncode == 0, ok.stderr or ok.stdout


def test_isolated_python_runs_first_run_env_by_script_not_dash_m(tmp_path):
    env_path = tmp_path / "user" / ".env"
    script = ROOT / "app" / "first_run_env.py"
    child_env = {**os.environ, "PYTHONPATH": str(ROOT)}

    missing = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "app.first_run_env",
            "ensure",
            "--env",
            str(env_path),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=child_env,
        check=False,
    )
    assert missing.returncode != 0
    assert "No module named 'app'" in (missing.stderr + missing.stdout)

    ok = subprocess.run(
        [
            sys.executable,
            "-I",
            str(script),
            "ensure",
            "--env",
            str(env_path),
            "--workspace",
            str(tmp_path / "Documents" / "Jarvis"),
            "--database",
            str(tmp_path / "user" / "data" / "control_room.db"),
            "--force-local",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": ""},
        check=False,
    )
    assert ok.returncode == 0, ok.stderr or ok.stdout
    payload = json.loads(ok.stdout.strip().splitlines()[-1])
    assert payload["ok"] is True
    assert payload["needs_key"] is True
    assert env_path.is_file()


def test_packaged_talk_policy_is_shipped_with_the_shell():
    pkg = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))
    assert "talk-policy.js" in pkg["build"]["files"]
    yml = (DESKTOP / "electron-builder.installer.yml").read_text(encoding="utf-8")
    assert "talk-policy.js" in yml
    assert (DESKTOP / "talk-policy.js").is_file()
    assert (DESKTOP / "talk-policy.test.js").is_file()


def test_packaged_python_helpers_are_shipped_with_the_shell():
    pkg = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))
    assert "packaged-python.js" in pkg["build"]["files"]
    assert (DESKTOP / "packaged-python.js").is_file()
    assert (DESKTOP / "packaged-python.test.js").is_file()


def test_first_run_window_never_asks_for_a_key():
    html = (DESKTOP / "first-run.html").read_text(encoding="utf-8")
    low = html.lower()
    assert "api key" not in low
    assert "openrouter" not in low
    assert "openai" not in low
    assert 'id="key"' not in html
    assert "Welcome to Jarvis" in html
    assert "Free" in html
    assert "$3" in html
    assert "$8" in html
    assert "Documents\\Jarvis" in html
    assert "notepad" not in low
    preload = (DESKTOP / "first-run-preload.js").read_text(encoding="utf-8")
    assert "saveKey" not in preload
    assert "first-run:continue" in preload
    main = (DESKTOP / "main.js").read_text(encoding="utf-8")
    assert "first-run.html" in main
    assert "firstRunArgv" in main
    assert "uvicornArgv" in main
    assert "packaged-python" in main
    assert "talk-policy" in main
    assert "shouldShowFirstRunKeyWindow" in main
    assert '-m", "app.first_run_env' not in main
    assert "write-key" not in main


def test_portable_zip_script_still_exists():
    ps1 = (WINDOWS / "build-portable.ps1").read_text(encoding="utf-8")
    assert "Jarvis-Windows-Portable-GRoK.zip" in ps1
    assert "RUN-JARVIS.bat" in ps1
    assert "START-HERE.txt" in ps1
    assert (ROOT / "RUN-JARVIS.bat").is_file()


def test_no_installer_binary_committed():
    for pattern in ("*.exe", "*.msi"):
        hits = [
            p
            for p in ROOT.rglob(pattern)
            if ".git" not in p.parts
            and "node_modules" not in p.parts
            and ".venv" not in p.parts
        ]
        assert hits == [], f"do not commit installer binaries: {hits}"


def test_mom_start_here_exists():
    text = (ROOT / "docs" / "START-HERE-WINDOWS.txt").read_text(encoding="utf-8")
    assert "Jarvis-Setup.exe" in text
    assert "Double-click" in text
    assert "API key" not in text
    assert "OpenRouter" not in text
    assert "Documents\\Jarvis" in text
    assert "No Python" in text
    assert "No unzip" in text
    assert "Settings" in text
    assert "gear" in text
    assert "top right" in text
    assert "top left" not in text
    assert "budget" in text.lower()


def test_windows_app_opens_settings_without_console():
    main = (DESKTOP / "main.js").read_text(encoding="utf-8")
    assert 'q.set("settings", "1")' in main or "settings=1" in main
    assert 'label: "Settings"' in main
    assert "installAppMenu" in main
    assert "autoHideMenuBar: false" in main
    assert "first-run.html" in main
    assert "windowsHide: true" in main
    html = (ROOT / "app" / "static" / "ceo.html").read_text(encoding="utf-8")
    assert "iu-settings-fab" in html
    assert 'settingsFab.textContent = "Settings"' not in html
    assert 'settingsFab.textContent = "⚙"' in html
    assert 'title.textContent = "Settings"' in html
    assert html.count('id = "iu-settings-fab"') == 1
    assert 'item("Settings"' not in html
    assert 'gear.id = "iu-gear"' not in html
    assert "#iu-gear {" not in html
    fab = html[html.index("#iu-settings-fab {") : html.index("#iu-settings-fab:focus-visible")]
    assert "right: 16px" in fab
    assert "left: 16px" not in fab
    assert "left:" not in fab
    assert "Daily cap" in html
    assert "Quality vs price" in html
    assert "model_preference" in html
    assert "daily_budget_usd" in html
    assert 'id = "iu-subscribe"' in html
    assert "Current plan: Free" in html
    assert '"$3"' in html or "$3" in html
    assert '"$8"' in html or "$8" in html
    assert 'id = "iu-plan-pay"' in html
    assert "does not charge a card" in html


def test_public_download_is_the_one_click_exe():
    page = (ROOT / "deploy" / "jarvis-public" / "index.html").read_text(encoding="utf-8")
    assert "<title>Jarvis</title>" in page
    assert 'aria-label="Jarvis"' not in page
    assert ">Jarvis</h1>" not in page
    assert 'href="/download/Jarvis-Setup.exe"' in page
    assert 'aria-label="Get app"' in page
    assert "Get app" in page
    assert ">Download</a>" not in page
    assert 'id="wall"' not in page
    assert 'id="log"' in page
    assert 'id="box"' in page
    assert 'id="mic"' in page
    assert 'id="more"' in page
    assert 'aria-label="Mute me"' in page
    assert "/api/jarvis/ask" in page
    assert "/api/jarvis/speak" in page
    assert "Can't talk right now" in page
    assert "Open it. Talk." not in page
    assert "Download for Windows" not in page
    assert "Jarvis-Windows-Portable.zip" not in page
    assert "Advanced download" not in page
    assert "RUN-JARVIS.bat" not in page
    assert "API key" not in page
    assert "OpenRouter" not in page
    assert "paste your key" not in page.lower()
    assert "SmartScreen" not in page
    assert "Windows protected" not in page
    assert "play.google.com" not in page
    assert "App Store" not in page
    assert "iOS" not in page
    assert "What it is" not in page
    assert "How to run" not in page
