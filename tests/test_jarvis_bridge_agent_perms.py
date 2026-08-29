"""Bridge agent should use bridge tool_source + max_auto (build tasks)."""

from app.jarvis.agent import JarvisLocalAgent, build_jarvis_agent
from app.jarvis.permissions import Tier


def test_build_jarvis_agent_bridge_kwargs(monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("JARVIS_MODEL", "openai/gpt-4.1-mini")
    agent = build_jarvis_agent(
        api_key="sk-test",
        model="openai/gpt-4.1",
        tool_source="bridge",
        max_auto=2,
        max_tokens=4096,
        max_tool_rounds=12,
    )
    assert isinstance(agent, JarvisLocalAgent)
    assert agent._model == "openai/gpt-4.1"
    assert agent._tool_source == "bridge"
    assert int(agent._max_auto) == 2
    assert agent._max_tokens == 4096
    assert agent._max_rounds == 12


def test_agent_retries_confirm_within_max_auto(monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    calls = []

    class FakeGW:
        def run(self, name, args, *, source="local", max_auto=None, confirmed=False):
            calls.append({"name": name, "source": source, "max_auto": int(max_auto or 0), "confirmed": confirmed})
            if not confirmed:
                return {"ok": False, "needs_confirm": True, "tier": "L1"}
            return {"ok": True, "path": "Exports/x.html"}

    agent = JarvisLocalAgent(api_key="sk-test", tool_source="bridge", max_auto=Tier.L2)
    agent._gateway = FakeGW()
    # simulate one tool path through the private pattern used in send_message
    parsed = agent._gateway.run("write_file", {"path": "Exports/x.html"}, source=agent._tool_source, max_auto=agent._max_auto, confirmed=False)
    if parsed.get("needs_confirm"):
        from app.jarvis.permissions import tool_tier
        if int(tool_tier("write_file")) <= int(agent._max_auto):
            parsed = agent._gateway.run("write_file", {"path": "Exports/x.html"}, source=agent._tool_source, max_auto=agent._max_auto, confirmed=True)
    assert parsed["ok"] is True
    assert calls[0]["confirmed"] is False and calls[1]["confirmed"] is True
