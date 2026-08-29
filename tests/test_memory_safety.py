import os
from pathlib import Path

import pytest

os.environ.setdefault("API_SECRET", "test-secret")
os.environ.setdefault("DATABASE_PATH", str(Path(__file__).parent / "_mem.db"))

from app.config import get_settings
from app.crypto import TokenCipher
from app.db import Database
from app.store.jobs import JobStore


@pytest.mark.asyncio
async def test_memory_update_versions(tmp_path):
    get_settings.cache_clear()
    db = Database(tmp_path / "m.db")
    await db.connect()
    store = JobStore(db, memory_versions_keep=3)
    job = await store.create_job(
        name="t",
        prompt_template="x",
        model="grok-4.3",
        memory_doc="v0",
    )
    assert job.memory_doc == "v0"
    j1 = await store.update_memory(job.id, "v1")
    assert j1.memory_version == 1
    assert j1.memory_doc == "v1"
    await store.update_memory(job.id, "v2")
    await store.update_memory(job.id, "v3")
    await store.update_memory(job.id, "v4")
    cur = await db.conn.execute(
        "SELECT COUNT(*) AS c FROM memory_versions WHERE job_id = ?", (job.id,)
    )
    row = await cur.fetchone()
    assert row["c"] <= 3
    final = await store.get_job(job.id)
    assert final.memory_doc == "v4"
    await db.close()
