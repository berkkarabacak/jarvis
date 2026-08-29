"""ORCH-410 — on-demand Grok-style viewer for Jarvis's live desktop."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CEO = ROOT / "app" / "static" / "ceo.html"
VIEWER = ROOT / "app" / "static" / "jarvis-screen.html"
SCREEN_PY = ROOT / "app" / "jarvis" / "screen_viewer.py"
SCREEN_ROUTES = ROOT / "app" / "jarvis" / "screen_routes.py"
MAIN_JS = ROOT / "desktop" / "main.js"
PRELOAD = ROOT / "desktop" / "preload.js"
COMPOSE = ROOT / "deploy" / "jarvis-computer" / "docker-compose.yml"
DOCS = ROOT / "docs" / "jarvis-computer.md"


def test_contract_points_at_existing_localhost_session():
    from app.jarvis.screen_viewer import (
        NOVNC_URL,
        VIEWER_CONTROL,
        VIEWER_TITLE,
        compose_up_argv,
        viewer_contract,
    )

    body = viewer_contract()
    assert body["title"] == "Jarvis's screen"
    assert body["control"] == "Open Jarvis's screen"
    assert body["url"] == "http://127.0.0.1:6080"
    assert body["host"] == "127.0.0.1"
    assert body["port"] == 6080
    assert body["bind"] == "127.0.0.1"
    assert body["public_bind"] is False
    assert body["same_desktop"] is True
    assert body["recording"] is False
    assert body["container"] == "jarvis-computer"
    assert body["path"] == "/ceo/jarvis-screen"
    assert "6080" in body["session_url"]
    assert "autoconnect=1" in body["session_url"]
    assert VIEWER_TITLE == "Jarvis's screen"
    assert VIEWER_CONTROL == "Open Jarvis's screen"
    assert NOVNC_URL == "http://127.0.0.1:6080"

    argv = compose_up_argv()
    assert argv[:2] == ["docker", "compose"]
    assert "up" in argv and "-d" in argv
    assert "--build" not in argv
    assert "run" not in argv
    assert str(COMPOSE) in argv
    assert "jarvis-computer" in " ".join(argv)


def test_control_exists_in_ceo_and_electron():
    ceo = CEO.read_text(encoding="utf-8")
    assert "Open Jarvis's screen" in ceo
    assert 'iu-open-jarvis-screen' in ceo
    assert "/ceo/jarvis-screen" in ceo
    assert "jarvisDesktop.openScreen" in ceo
    assert "http://127.0.0.1:6080" not in ceo

    main = MAIN_JS.read_text(encoding="utf-8")
    assert 'JARVIS_SCREEN_TITLE = "Jarvis\'s screen"' in main
    assert 'JARVIS_SCREEN_CONTROL = "Open Jarvis\'s screen"' in main
    assert 'JARVIS_NOVNC_URL = "http://127.0.0.1:6080"' in main
    assert "function openJarvisScreen" in main
    assert "/ceo/jarvis-screen" in main
    assert "new BrowserWindow" in main.split("function openJarvisScreen")[1]
    assert "setTitle(JARVIS_SCREEN_TITLE)" in main
    assert "page-title-updated" in main
    assert "jarvis:open-screen" in main
    assert "0.0.0.0" not in main.split("function openJarvisScreen")[1].split("function ")[0]

    preload = PRELOAD.read_text(encoding="utf-8")
    assert "openScreen" in preload
    assert "jarvis:open-screen" in preload


def test_viewer_page_is_live_session_not_a_fake_picture():
    html = VIEWER.read_text(encoding="utf-8")
    assert "<title>Jarvis's screen</title>" in html
    assert 'id="caption">Jarvis\'s screen</div>' in html
    assert "Jarvis's screen" in html
    assert 'id="live"' in html
    assert "http://127.0.0.1:6080/vnc.html?autoconnect=1" in html
    assert "Jarvis's computer is not running." in html
    assert "Start Jarvis's computer" in html
    assert "not a recording" in html.lower() or "not a screenshot" in html.lower()
    assert "fake" not in html.lower() or "not a screenshot" in html
    assert "data:image" not in html
    assert ".png" not in html
    assert "0.0.0.0" not in html


def test_compose_stays_localhost_only():
    compose = COMPOSE.read_text(encoding="utf-8")
    assert "127.0.0.1:6080:6080" in compose
    assert "0.0.0.0" not in compose
    src = SCREEN_PY.read_text(encoding="utf-8")
    assert "127.0.0.1" in src
    assert "6080" in src
    assert "0.0.0.0" not in src
    assert "--build" not in src
    routes = SCREEN_ROUTES.read_text(encoding="utf-8")
    assert "localhost only" in routes.lower()


def test_fallback_argv_when_compose_is_missing():
    from app.jarvis.screen_viewer import (
        compose_is_missing,
        compose_up_argv,
        docker_run_argv,
        docker_start_argv,
        start_argv_after_compose,
    )

    assert compose_is_missing("docker: 'compose' is not a docker command.")
    assert compose_is_missing("unknown command: compose")
    assert compose_is_missing("compose plugin not found")
    assert not compose_is_missing("no such image: jarvis-computer:local")
    assert not compose_is_missing("Cannot connect to the Docker daemon")

    assert compose_up_argv()[:2] == ["docker", "compose"]
    assert "--build" not in compose_up_argv()
    assert docker_start_argv() == ["docker", "start", "jarvis-computer"]
    assert start_argv_after_compose(container_exists=True) == docker_start_argv()
    assert start_argv_after_compose(container_exists=False) == docker_run_argv()

    run = docker_run_argv()
    assert run[:3] == ["docker", "run", "-d"]
    assert run[run.index("--name") + 1] == "jarvis-computer"
    assert "127.0.0.1:6080:6080" in run
    assert "jarvis-computer-home:/home/jarvis" in run
    assert run[-1] == "jarvis-computer:local"
    assert "0.0.0.0" not in run
    assert "--build" not in run
    assert run.count("jarvis-computer") >= 2


def test_start_computer_falls_back_to_docker_start(monkeypatch):
    from app.jarvis import screen_viewer as sv

    sv.reset_screen_viewer_state()
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_jarvis_screen_viewer.py")
    monkeypatch.delenv("JARVIS_ALLOW_REAL_COMPUTER", raising=False)
    calls: list[list[str]] = []

    def runner(argv: list[str]) -> dict:
        calls.append(list(argv))
        if argv[:2] == ["docker", "compose"]:
            return {
                "returncode": 1,
                "stderr": "docker: 'compose' is not a docker command.\nSee 'docker --help'\n",
                "stdout": "",
            }
        if argv[:2] == ["docker", "inspect"]:
            return {"returncode": 0, "stdout": "/jarvis-computer\n", "stderr": ""}
        if argv[:2] == ["docker", "start"]:
            return {"returncode": 0, "stdout": "jarvis-computer\n", "stderr": ""}
        raise AssertionError(argv)

    sv.set_screen_run(runner)
    sv.set_screen_probe(lambda: {"running": True, "status_code": 200})
    out = sv.start_computer()
    assert out["ok"] is True
    assert out["running"] is True
    assert out["url"] == "http://127.0.0.1:6080"
    assert out["argv"] == ["docker", "start", "jarvis-computer"]
    assert calls[0][:2] == ["docker", "compose"]
    assert "--build" not in calls[0]
    assert ["docker", "inspect", "jarvis-computer"] in calls
    assert ["docker", "start", "jarvis-computer"] in calls
    assert not any(cmd[:2] == ["docker", "run"] for cmd in calls)
    sv.reset_screen_viewer_state()


def test_start_computer_falls_back_to_docker_run(monkeypatch):
    from app.jarvis import screen_viewer as sv

    sv.reset_screen_viewer_state()
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_jarvis_screen_viewer.py")
    monkeypatch.delenv("JARVIS_ALLOW_REAL_COMPUTER", raising=False)
    calls: list[list[str]] = []

    def runner(argv: list[str]) -> dict:
        calls.append(list(argv))
        if argv[:2] == ["docker", "compose"]:
            return {"returncode": 1, "stderr": "docker: 'compose' is not a docker command.", "stdout": ""}
        if argv[:2] == ["docker", "inspect"]:
            return {"returncode": 1, "stdout": "", "stderr": "Error: No such object: jarvis-computer"}
        if argv[:2] == ["docker", "run"]:
            assert "127.0.0.1:6080:6080" in argv
            assert "jarvis-computer-home:/home/jarvis" in argv
            assert argv[-1] == "jarvis-computer:local"
            assert "--name" in argv and argv[argv.index("--name") + 1] == "jarvis-computer"
            assert "0.0.0.0" not in argv
            assert "--build" not in argv
            return {"returncode": 0, "stdout": "abc123\n", "stderr": ""}
        raise AssertionError(argv)

    sv.set_screen_run(runner)
    sv.set_screen_probe(lambda: {"running": True, "status_code": 200})
    out = sv.start_computer()
    assert out["ok"] is True
    assert out["running"] is True
    assert out["argv"][:3] == ["docker", "run", "-d"]
    assert "127.0.0.1:6080:6080" in out["argv"]
    assert not any(cmd[:2] == ["docker", "start"] for cmd in calls)
    sv.reset_screen_viewer_state()


def test_probe_and_start_use_test_seams(monkeypatch):
    from app.jarvis import screen_viewer as sv

    sv.reset_screen_viewer_state()
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_jarvis_screen_viewer.py")
    monkeypatch.delenv("JARVIS_ALLOW_REAL_COMPUTER", raising=False)

    down = sv.probe_novnc()
    assert down["running"] is False
    assert down["error"] == "Jarvis's computer is not running."
    assert "screenshot" not in str(down).lower()

    sv.set_screen_probe(lambda: {"running": True, "status_code": 200})
    up = sv.screen_status()
    assert up["running"] is True
    assert up["title"] == "Jarvis's screen"
    assert up["url"] == "http://127.0.0.1:6080"
    assert up["control"] == "Open Jarvis's screen"
    assert up["public_bind"] is False

    blocked = sv.start_computer()
    assert blocked["ok"] is False
    assert blocked["running"] is False
    assert "off during tests" in blocked["reason"]

    sv.set_screen_start(
        lambda: {
            "ok": True,
            "started": True,
            "running": True,
            "url": "http://127.0.0.1:6080",
        }
    )
    started = sv.start_computer()
    assert started["ok"] is True
    assert started["running"] is True
    assert started["url"] == "http://127.0.0.1:6080"
    sv.reset_screen_viewer_state()


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("API_SECRET", "test-secret")
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.setenv("LLM_MODEL_MODE", "fixed")
    monkeypatch.setenv("DEFAULT_MODEL", "openai/gpt-4.1-mini")
    os.environ["API_SECRET"] = "test-secret"
    os.environ["TOKEN_ENCRYPTION_KEY"] = ""
    os.environ["TOKEN_PROVIDER"] = "api_key"

    from app.config import get_settings
    from app.jarvis.screen_viewer import reset_screen_viewer_state, set_screen_probe, set_screen_start

    reset_screen_viewer_state()
    set_screen_probe(lambda: {"running": True, "status_code": 200})
    set_screen_start(
        lambda: {
            "ok": True,
            "started": True,
            "running": True,
            "title": "Jarvis's screen",
            "url": "http://127.0.0.1:6080",
        }
    )
    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    reset_screen_viewer_state()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_viewer_page_and_status_api(client):
    page = await client.get("/ceo/jarvis-screen")
    assert page.status_code == 200
    assert "text/html" in page.headers.get("content-type", "")
    assert "Jarvis's screen" in page.text
    assert "http://127.0.0.1:6080" in page.text
    assert "Start Jarvis's computer" in page.text

    status = await client.get("/api/jarvis/computer/screen")
    assert status.status_code == 200
    body = status.json()
    assert body["title"] == "Jarvis's screen"
    assert body["control"] == "Open Jarvis's screen"
    assert body["url"] == "http://127.0.0.1:6080"
    assert body["running"] is True
    assert body["public_bind"] is False
    assert "screenshot" not in body
    assert "image" not in body

    started = await client.post("/api/jarvis/computer/screen/start")
    assert started.status_code == 200
    out = started.json()
    assert out["ok"] is True
    assert out["running"] is True
    assert out["url"] == "http://127.0.0.1:6080"
    assert out["title"] == "Jarvis's screen"


def test_docs_explain_on_demand_viewer():
    docs = DOCS.read_text(encoding="utf-8")
    assert "ORCH-410" in docs
    assert "Open Jarvis's screen" in docs
    assert "Jarvis's screen" in docs
    assert "http://127.0.0.1:6080" in docs
    later = docs.split("## Later tickets")[-1].split("## ")[0]
    assert "ORCH-410" not in later
