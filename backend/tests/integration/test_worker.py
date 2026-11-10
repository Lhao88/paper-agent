from datetime import UTC, datetime, timedelta

import pytest

from app.db import Run
from app.db.session import create_engine, get_test_settings, session_factory
from app.errors import DomainError
from app.repositories.projects import ProjectRepository
from app.worker.claim import claim_next_run, heartbeat, release_run


async def test_claim_is_exclusive_and_expired_lease_does_not_auto_takeover():
    engine = create_engine(get_test_settings())
    factory = session_factory(engine)
    try:
        # Other tests leave queued synthetic runs; claim a known run explicitly here.
        async with factory.begin() as session:
            project = await ProjectRepository(session).create("claim test", "synthetic")
            run = await ProjectRepository(session).create_run(project.id, "run", "hash", {}, {})
            run_id = run.id
        first = await claim_next_run(factory, "first", run_id)
        assert first is not None
        assert await claim_next_run(factory, "second", run_id) is None
        async with factory.begin() as session:
            stored = await session.get(Run, run_id)
            stored.lease_until = datetime.now(UTC) - timedelta(seconds=100)
        assert await claim_next_run(factory, "second", run_id) is None
        await heartbeat(factory, first, 3.5)
        await release_run(factory, first, "waiting_user", None)
        async with factory() as session:
            stored = await session.get(Run, run_id)
            assert stored.active_elapsed_seconds == 3.5
            assert stored.worker_id is None
        with pytest.raises(DomainError) as lost:
            await heartbeat(factory, first, 100)
        assert lost.value.code == "CLAIM_LOST"
    finally:
        await engine.dispose()
