"""PR1: Agents API child runner behind JARVIS_AGENTS_API (issue #26)."""

from __future__ import annotations

import json
import threading

import httpx
import pytest

from app.jarvis.agents_api import AGENTS_BETA_HEADER, DEFAULT_MODEL, cancel_event
from app.jarvis.agents_child import (
    CHILD_BACKEND_AGENTS,
    CHILD_BACKEND_LOCAL,
    FLAG_ENV,
    agents_api_child_runner_enabled,
    apply_agents_events,
    prefer_agents_for_goal,
    should_use_agents_child_runner,
)
from app.jarvis.children import (
    ChildRecord,
    default_child_runner,
    reset_supervisor_for_tests,
)
from app.jarvis.taint import CHILD_TAINT_SOURCE

TEST_KEY = "sk-test-agents-child-not-a-real-key"
RESEARCH_GOAL = "Research the trade-offs between TCP and UDP congestion control."
WRITE_GOAL = "Create a report with write_file under Exports/report.md"
CLICK_GOAL = "click the Allow button on screen in chrome"


def _sse(*events: dict) -> str:
    return "".join(f"data: {json.dumps(event)}\n\n" for event in events)


def _client(handler) -> httpx.Client:
    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport, base_url="https://api.openai.com/v1")


def _api(handler):
    from app.jarvis.agents_api import AgentsApiClient

    return AgentsApiClient(api_key=TEST_KEY, client=_client(handler))


def _record(**extra) -> ChildRecord:
    rec = ChildRecord(
        child_id="c_test0001",
        parent_job_id="job_test",
        goal=RESEARCH_GOAL,
        model="openai/gpt-4.1-mini",
        budget_seconds=5,
        budget_usd=0.05,
        status="running",
    )
    for key, value in extra.items():
        setattr(rec, key, value)
    return rec


@pytest.fixture
def agents_flag_off(monkeypatch):
    monkeypatch.delenv(FLAG_ENV, raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("HOSTED_OPENAI_KEY", raising=False)


@pytest.fixture
def agents_flag_on(tmp_path, monkeypatch):
    ws = tmp_path / "Jarvis"
    ws.mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE", str(ws))
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "0")
    monkeypatch.setenv(FLAG_ENV, "1")
    monkeypatch.setenv("OPENAI_API_KEY", TEST_KEY)
    monkeypatch.delenv("JARVIS_MODEL_PIN", raising=False)
    from app.jarvis.openrouter_leaders import reset_leaders_cache_for_tests

    reset_leaders_cache_for_tests()
    import app.jarvis.gateway as gw

    gw._gateway = None
    yield ws
    reset_supervisor_for_tests()
    gw._gateway = None


def test_flag_default_off(agents_flag_off):
    assert agents_api_child_runner_enabled() is False
    assert should_use_agents_child_runner(RESEARCH_GOAL) is False


def test_flag_on_requires_key(monkeypatch):
    monkeypatch.setenv(FLAG_ENV, "true")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("HOSTED_OPENAI_KEY", raising=False)
    assert agents_api_child_runner_enabled() is False
    monkeypatch.setenv("OPENAI_API_KEY", TEST_KEY)
    assert agents_api_child_runner_enabled() is True
    monkeypatch.setenv(FLAG_ENV, "off")
    assert agents_api_child_runner_enabled() is False


def test_soft_router_local_for_desktop_and_tools():
    assert prefer_agents_for_goal(WRITE_GOAL) is False
    assert prefer_agents_for_goal(CLICK_GOAL) is False
    assert prefer_agents_for_goal("see_screen the chrome tab") is False
    assert prefer_agents_for_goal(RESEARCH_GOAL) is True
    assert prefer_agents_for_goal("Summarize the architecture trade-offs") is True
    assert prefer_agents_for_goal("please handle this carefully") is True


def test_flag_off_default_runner_stays_local(agents_flag_off, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", TEST_KEY)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(500, text="should not be called")

    rec = _record()
    sup = reset_supervisor_for_tests(agents_client=_api(handler))
    default_child_runner(rec, sup)
    assert rec.backend == CHILD_BACKEND_LOCAL
    assert rec.error == "OPENROUTER_API_KEY missing"
    assert calls == []


def test_apply_events_taint_shape_and_usage():
    rec = _record()
    apply_agents_events(
        rec,
        [
            {"type": "agent.session.created", "session_id": "sess_a"},
            {"type": "agent.session.subagent.created", "subagent_id": "sa_9"},
            {
                "type": "agent.session.turn.output_text.done",
                "text": "UDP is simpler; TCP is reliable.",
            },
            {
                "type": "agent.session.turn.completed",
                "turn": {"subagent_id": None, "usage": {"cost": 0.003}},
            },
        ],
    )
    assert rec.agents_session_id == "sess_a"
    assert rec.agents_subagent_ids == ["sa_9"]
    assert rec.result_text.startswith("UDP")
    assert rec.spent_usd == pytest.approx(0.003)
    assert rec.status == "done"
    payload = rec.wait_payload()
    assert payload["tainted"] is True
    assert payload["taint_source"] == CHILD_TAINT_SOURCE
    assert payload["usage"]["usd"] == pytest.approx(0.003)


def test_apply_events_does_not_invent_usage():
    rec = _record()
    apply_agents_events(
        rec,
        [
            {
                "type": "agent.session.turn.completed",
                "turn": {"subagent_id": None},
            }
        ],
    )
    assert rec.spent_usd == 0.0
    assert rec.status == "done"


def _bind_spawnable(sup):
    sup.org_depth_override = 2
    job_id = sup.job_id_for("local")
    sup.bind_job(
        job_id,
        goal="hire two helpers to research two topics",
        remaining_usd=1.0,
        remaining_seconds=120.0,
    )
    return job_id


def test_flag_on_spawn_message_wait_mapping(agents_flag_on):
    calls: list[dict[str, object]] = []
    started = threading.Event()
    release = threading.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode()) if request.content else None
        calls.append(
            {
                "method": request.method,
                "path": request.url.path,
                "beta": request.headers.get("OpenAI-Beta"),
                "body": body,
            }
        )
        path = request.url.path
        if request.method == "POST" and path.endswith("/agents/sessions"):
            assert body["environment"] == {"type": "none"}
            assert body["agent"]["multi_agent"]["enabled"] is True
            assert body["agent"]["multi_agent"]["max_concurrent_subagents"] == 4
            assert body["input"] == RESEARCH_GOAL
            return httpx.Response(
                200,
                json={"id": "sess_child_1", "object": "agent.session"},
            )
        if request.method == "GET" and path.endswith("/events"):
            started.set()
            release.wait(timeout=2)
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=_sse(
                    {
                        "type": "agent.session.subagent.created",
                        "subagent_id": "sa_1",
                    },
                    {
                        "type": "agent.session.turn.output_text.done",
                        "text": "UDP skips handshake.",
                    },
                    {
                        "type": "agent.session.turn.completed",
                        "turn": {"subagent_id": None, "usage": {"cost": 0.002}},
                    },
                ),
            )
        if request.method == "POST" and path.endswith("/events"):
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, text="unexpected")

    sup = reset_supervisor_for_tests(agents_client=_api(handler))
    job_id = _bind_spawnable(sup)
    spawned = sup.spawn(
        RESEARCH_GOAL,
        budget_seconds=8,
        budget_usd=0.05,
        parent_job_id=job_id,
    )
    assert spawned.get("ok") is True
    cid = spawned["id"]
    child = sup.get_child(cid)
    assert child is not None
    assert child.backend == CHILD_BACKEND_AGENTS
    assert started.wait(timeout=2)

    msg = sup.message(cid, "Also compare SCTP.")
    assert msg == {"ok": True, "id": cid, "delivered": True}
    release.set()
    waited = sup.wait(cid, timeout=3)
    assert waited.get("ok") is True
    assert waited.get("status") == "done"
    assert waited.get("tainted") is True
    assert waited.get("taint_source") == CHILD_TAINT_SOURCE
    assert waited.get("result") == "UDP skips handshake."
    assert waited["usage"]["usd"] == pytest.approx(0.002)
    assert waited["usage"]["model"] == DEFAULT_MODEL
    assert child.agents_session_id == "sess_child_1"
    assert "sa_1" in child.agents_subagent_ids

    create = next(c for c in calls if c["method"] == "POST" and str(c["path"]).endswith("/agents/sessions"))
    assert create["beta"] == AGENTS_BETA_HEADER
    messages = [
        c
        for c in calls
        if c["method"] == "POST"
        and str(c["path"]).endswith("/sess_child_1/events")
        and (c["body"] or {}).get("events", [{}])[0].get("type")
        == "agent.session.input.message"
    ]
    assert messages
    assert TEST_KEY not in json.dumps(waited)
    assert TEST_KEY not in json.dumps(spawned)


def test_flag_on_write_file_goal_stays_local(agents_flag_on, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(500, text="agents should not run")

    rec = _record(goal=WRITE_GOAL)
    sup = reset_supervisor_for_tests(agents_client=_api(handler))
    default_child_runner(rec, sup)
    assert rec.backend == CHILD_BACKEND_LOCAL
    assert rec.error == "OPENROUTER_API_KEY missing"
    assert calls == []


def test_budget_cancel_posts_agents_cancel(agents_flag_on):
    cancelled = threading.Event()
    created = threading.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content.decode()) if request.content else None
        if request.method == "POST" and path.endswith("/agents/sessions"):
            created.set()
            return httpx.Response(200, json={"id": "sess_budget"})
        if request.method == "GET" and path.endswith("/events"):
            # Block until cancel so the watch thread can fire.
            cancelled.wait(timeout=2)
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=_sse(
                    {
                        "type": "agent.session.turn.cancelled",
                        "turn": {"subagent_id": None},
                    }
                ),
            )
        if request.method == "POST" and path.endswith("/events"):
            assert body["events"] == [cancel_event()]
            cancelled.set()
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)

    sup = reset_supervisor_for_tests(agents_client=_api(handler))
    job_id = _bind_spawnable(sup)
    spawned = sup.spawn(
        RESEARCH_GOAL,
        budget_seconds=0.05,
        budget_usd=0.5,
        parent_job_id=job_id,
    )
    assert spawned.get("ok") is True
    waited = sup.wait(spawned["id"], timeout=3)
    assert waited.get("ok") is True
    assert waited.get("status") == "budget_seconds"
    assert waited.get("tainted") is True
    assert waited.get("taint_source") == CHILD_TAINT_SOURCE
    assert cancelled.is_set() or created.is_set()


def test_idle_is_not_success():
    rec = _record()
    apply_agents_events(rec, [{"type": "agent.session.idle"}])
    assert rec.agents_idle is True
    assert rec.status == "running"


def test_gateway_wait_still_taints_on_agents_path(agents_flag_on):
    from app.jarvis.gateway import ToolGateway

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path.endswith("/agents/sessions"):
            return httpx.Response(200, json={"id": "sess_gw"})
        if request.method == "GET" and path.endswith("/events"):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=_sse(
                    {
                        "type": "agent.session.turn.output_text.done",
                        "text": "notes",
                    },
                    {
                        "type": "agent.session.turn.completed",
                        "turn": {"subagent_id": None},
                    },
                ),
            )
        return httpx.Response(200, json={"ok": True})

    reset_supervisor_for_tests(agents_client=_api(handler))
    g = ToolGateway()
    from app.jarvis.children import get_supervisor

    _bind_spawnable(get_supervisor())
    spawned = g.run(
        "spawn_child",
        {
            "goal": RESEARCH_GOAL,
            "budget_seconds": 5,
            "budget_usd": 0.05,
        },
        source="local",
    )
    assert spawned.get("ok") is True
    g.clear_taint("local")
    waited = g.run("wait_child", {"id": spawned["id"]}, source="local")
    assert waited.get("ok") is True
    assert waited.get("tainted") is True
    assert waited.get("taint_source") == CHILD_TAINT_SOURCE
    assert g._tracker("local").source == CHILD_TAINT_SOURCE
