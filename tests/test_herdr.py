import json
from unittest.mock import AsyncMock, patch

import pytest

from app.integrations.herdr import (
    HerdrClient,
    HerdrConfig,
    HerdrError,
    _extract_json,
    sanitize_agent_name,
)


def test_extract_json_plain():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_with_prefix_noise():
    out = _extract_json('log line\n{"pane_id": "p1"}')
    assert out["pane_id"] == "p1"


def test_extract_json_rejects_garbage():
    with pytest.raises(HerdrError):
        _extract_json("not json at all")


def test_sanitize_agent_name():
    assert sanitize_agent_name("Reviewer") == "reviewer"
    assert sanitize_agent_name("My Agent!!") == "my-agent"
    assert sanitize_agent_name("123bad")[0].isalpha()
    assert len(sanitize_agent_name("a" * 100)) <= 32


@pytest.mark.asyncio
async def test_available_false_when_bin_missing(tmp_path):
    client = HerdrClient(HerdrConfig(bin=str(tmp_path / "no-such-herdr"), enabled=True))
    st = await client.status()
    assert st["available"] is False


@pytest.mark.asyncio
async def test_workspace_create_parses_nested_result():
    client = HerdrClient(HerdrConfig(bin="herdr", enabled=True))

    async def fake_run(args, timeout_ms=None, allow_plain=False):
        assert args[:2] == ["workspace", "create"]
        assert "--no-focus" in args
        return {
            "result": {
                "workspace": {"workspace_id": "w1"},
                "root_pane": {"pane_id": "w1:p1"},
            }
        }, ""

    with patch.object(client, "resolved_bin", return_value="herdr"):
        with patch.object(client, "_run", new=AsyncMock(side_effect=fake_run)):
            pane = await client.workspace_create("/tmp/x", label="t")
    assert pane == "w1:p1"


@pytest.mark.asyncio
async def test_agent_start_cli_shape():
    client = HerdrClient(HerdrConfig(bin="herdr", enabled=True, timeout_ms=5000))
    seen = {}

    async def fake_run(args, timeout_ms=None, allow_plain=False):
        seen["args"] = args
        return {"result": {"agent": {"name": "reviewer"}}}, ""

    with patch.object(client, "resolved_bin", return_value="herdr"):
        with patch.object(client, "_run", new=AsyncMock(side_effect=fake_run)):
            await client.agent_start("Reviewer!", "opencode", "w1:p1", extra_args=["-m", "x"])
    assert seen["args"][0:3] == ["agent", "start", "reviewer"]
    assert "--kind" in seen["args"] and "opencode" in seen["args"]
    assert "--pane" in seen["args"] and "w1:p1" in seen["args"]
    assert "--" in seen["args"]
    assert seen["args"][seen["args"].index("--") + 1 :] == ["-m", "x"]


@pytest.mark.asyncio
async def test_agent_prompt_uses_timeout_flag():
    client = HerdrClient(HerdrConfig(bin="herdr", enabled=True, timeout_ms=9000))
    seen = {}

    async def fake_run(args, timeout_ms=None, allow_plain=False):
        seen["args"] = args
        return {"result": {"agent": {}}}, ""

    with patch.object(client, "resolved_bin", return_value="herdr"):
        with patch.object(client, "_run", new=AsyncMock(side_effect=fake_run)):
            await client.agent_prompt("reviewer", "do work", wait=True, timeout_ms=12000)
    assert seen["args"][:4] == ["agent", "prompt", "reviewer", "do work"]
    assert "--wait" in seen["args"]
    assert "--timeout" in seen["args"]
    assert "12000" in seen["args"]
    assert "--timeout-ms" not in seen["args"]


@pytest.mark.asyncio
async def test_agent_read_plain_text():
    client = HerdrClient(HerdrConfig(bin="herdr", enabled=True))

    async def fake_run(args, timeout_ms=None, allow_plain=False):
        return "hello from agent", "hello from agent"

    with patch.object(client, "resolved_bin", return_value="herdr"):
        with patch.object(client, "_run", new=AsyncMock(side_effect=fake_run)):
            text = await client.agent_read("agent-1")
    assert text == "hello from agent"


@pytest.mark.asyncio
async def test_agent_read_nested_json():
    client = HerdrClient(HerdrConfig(bin="herdr", enabled=True))

    async def fake_run(args, timeout_ms=None, allow_plain=False):
        return {"result": {"read": {"text": "nested"}}}, ""

    with patch.object(client, "resolved_bin", return_value="herdr"):
        with patch.object(client, "_run", new=AsyncMock(side_effect=fake_run)):
            text = await client.agent_read("agent-1")
    assert text == "nested"


@pytest.mark.asyncio
async def test_run_raises_on_nonzero_exit():
    client = HerdrClient(HerdrConfig(bin="herdr", enabled=True, timeout_ms=5000))

    class FakeProc:
        returncode = 2

        async def communicate(self):
            return b"", b"boom"

        def kill(self):
            pass

    async def fake_exec(*a, **k):
        return FakeProc()

    with patch.object(client, "resolved_bin", return_value="herdr"):
        with patch("asyncio.create_subprocess_exec", new=fake_exec):
            with pytest.raises(HerdrError) as ei:
                await client._run(["status"])
    assert "exit 2" in str(ei.value)


@pytest.mark.asyncio
async def test_create_herdr_job_via_api(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "h.db"))
    monkeypatch.setenv("API_SECRET", "test-secret")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "x")
    monkeypatch.setenv("HERDR_ENABLED", "false")

    from app.config import get_settings

    get_settings.cache_clear()
    from httpx import ASGITransport, AsyncClient
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post(
                "/api/jobs",
                headers={"X-Api-Key": "test-secret"},
                json={
                    "name": "herdr-smoke",
                    "prompt_template": "Say hi {{date}}",
                    "runner": "herdr",
                    "herdr_agent_kind": "opencode",
                    "herdr_cwd": str(tmp_path / "ws"),
                },
            )
            assert r.status_code == 200
            job = r.json()["job"]
            assert job["runner"] == "herdr"
            assert job["herdr"]["agent_kind"] == "opencode"

            r2 = await ac.post(
                f"/api/jobs/{job['id']}/run",
                headers={"X-Api-Key": "test-secret"},
            )
            assert r2.status_code == 200
            assert r2.json()["run"]["status"] == "failed"
            assert "HERDR_ENABLED" in (r2.json()["run"]["error"] or "")

            st = await ac.get("/api/status", headers={"X-Api-Key": "test-secret"})
            assert st.status_code == 200
            assert "herdr" in st.json()
            assert st.json()["herdr"]["enabled"] is False
    get_settings.cache_clear()
