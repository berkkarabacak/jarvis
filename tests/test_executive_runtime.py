import pytest

from app.executive.confidence import EvidenceItem
from app.executive.session import (
    ExecutiveSession,
    ExecutiveSessionError,
    handoff_from_specialist_outcome,
)
from app.executive.store import InMemoryHandoffStore


@pytest.mark.asyncio
async def test_session_handoff_persistence_and_scope_filter():
    store = InMemoryHandoffStore()
    session = ExecutiveSession.open(
        mission_id="m-1",
        brief="Ship landing page",
        confidence_target=75,
        handoff_store=store,
    )
    pkt = handoff_from_specialist_outcome(
        from_role="ui-builder",
        objective="build hero",
        attempted_work="implemented hero section",
        outcome="hero renders",
        confidence=0.85,
        evidence_refs=["artifact:hero-1"],
    )
    row = await session.record_handoff(pkt, memory_scope="team")
    assert row.mission_id == "m-1"
    assert row.session_id == session.session_id
    assert row.memory_scope == "team"
    assert row.seq == 1

    # company-scoped second handoff
    await session.record_handoff(
        handoff_from_specialist_outcome(
            from_role="executive",
            to_role="company-memory",
            objective="promote learning",
            attempted_work="reviewed handoff",
            outcome="noted pattern",
            confidence=0.6,
        ),
        memory_scope="company",
    )

    team_only = await session.handoffs(memory_scope="team")
    assert len(team_only) == 1
    assert team_only[0].id == row.id

    all_rows = await store.list_for_mission("m-1")
    assert len(all_rows) == 2
    assert all_rows[0].seq == 1 and all_rows[1].seq == 2


@pytest.mark.asyncio
async def test_confidence_aggregates_evidence_and_handoffs():
    session = ExecutiveSession.open(mission_id="m-conf", confidence_target=80)
    session.record_evidence(
        EvidenceItem(kind="automated_test", weight=1.2, passed=True, summary="unit ok")
    )
    session.record_evidence(
        EvidenceItem(kind="ui_test", weight=1.3, passed=True, summary="e2e ok")
    )
    await session.record_handoff(
        handoff_from_specialist_outcome(
            from_role="reviewer",
            objective="review",
            attempted_work="read diffs",
            outcome="lgtm",
            confidence=0.9,
            risks=["flaky safari"],
        )
    )
    conf = session.confidence()
    assert 0 <= conf.score <= 100
    assert "flaky safari" in conf.unresolved_risks
    # handoff contributed an evidence component
    kinds = [c["kind"] for c in conf.components]
    assert "handoff" in kinds
    assert "automated_test" in kinds
    snap = session.snapshot()
    assert snap["confidence"]["score"] == conf.score
    assert snap["runtime"]["prime_agent"] is False
    assert snap["runtime"]["llm_provider"] is None


@pytest.mark.asyncio
async def test_executive_session_boundary_and_specialists():
    session = ExecutiveSession.open(mission_id="m-bound", brief="demo")
    exec_child = session.spawn_specialist("executive-planner")
    spec = session.spawn_specialist("cost-optimizer-v2", parent_instance_id=exec_child.instance_id)
    assert spec.role_name == "cost-optimizer-v2"
    assert spec.parent_instance_id == exec_child.instance_id

    with pytest.raises(ValueError):
        session.spawn_specialist("bad role!!!")

    with pytest.raises(ExecutiveSessionError):
        session.spawn_specialist("orphan", parent_instance_id="missing")

    session.stop_specialist(spec.instance_id)
    assert session.specialists[spec.instance_id].status == "stopped"

    session.transition("completed", reason="confidence_reached")
    assert session.status == "completed"
    assert session.ended_reason == "confidence_reached"

    with pytest.raises(ExecutiveSessionError):
        session.record_evidence(EvidenceItem(kind="artifact", weight=1.0, passed=True))

    with pytest.raises(ExecutiveSessionError):
        await session.record_handoff(
            handoff_from_specialist_outcome(
                from_role="x",
                objective="o",
                attempted_work="a",
                outcome="b",
                confidence=0.5,
            )
        )

    with pytest.raises(ExecutiveSessionError):
        session.transition("active")


@pytest.mark.asyncio
async def test_store_rejects_blank_ids_and_bad_scope():
    store = InMemoryHandoffStore()
    pkt = handoff_from_specialist_outcome(
        from_role="a",
        objective="o",
        attempted_work="w",
        outcome="x",
        confidence=0.5,
    )
    with pytest.raises(ValueError):
        await store.append(mission_id="", session_id="s", packet=pkt)
    with pytest.raises(ValueError):
        await store.append(mission_id="m", session_id="s", packet=pkt, memory_scope="galaxy")
