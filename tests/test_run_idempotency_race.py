from __future__ import annotations

import pytest


@pytest.fixture()
async def store(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "idem.db"))
    from app.config import get_settings
    from app.db import Database

    get_settings.cache_clear()
    db = Database(get_settings().database_path_resolved)
    await db.connect()
    yield _Store(db)
    await db.close()
    get_settings.cache_clear()


class _Store:
    def __init__(self, db) -> None:
        from app.store.jobs import JobStore

        self.jobs = JobStore(db)

    async def new_job(self) -> str:
        job = await self.jobs.create_job(
            name="t",
            prompt_template="p",
            model="m",
        )
        return job.id


async def test_duplicate_idempotency_key_returns_existing_run(store):
    job_id = await store.new_job()
    first = await store.jobs.create_run(
        job_id=job_id, status="running", idempotency_key="key-1"
    )
    second = await store.jobs.create_run(
        job_id=job_id, status="running", idempotency_key="key-1"
    )
    assert second.id == first.id


async def test_different_keys_create_distinct_runs(store):
    job_id = await store.new_job()
    a = await store.jobs.create_run(job_id=job_id, status="running", idempotency_key="a")
    b = await store.jobs.create_run(job_id=job_id, status="running", idempotency_key="b")
    assert a.id != b.id
