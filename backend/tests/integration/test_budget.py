import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import Run
from app.db.session import create_engine, get_test_settings, session_factory
from app.errors import DomainError
from app.llm.budget import BudgetService
from app.repositories.projects import ProjectRepository


@pytest.fixture
async def budget_run() -> AsyncIterator[tuple[UUID, async_sessionmaker[AsyncSession]]]:
    engine = create_engine(get_test_settings())
    factory = session_factory(engine)
    async with factory.begin() as session:
        repo = ProjectRepository(session)
        project = await repo.create("budget fixture", "test only")
        run = await repo.create_run(project.id, "request", "hash", {}, {})
        run.max_calls = 2
        run.max_tokens = 100
        run_id = run.id
    try:
        yield run_id, factory
    finally:
        await engine.dispose()


async def test_concurrent_reservations_cannot_exceed_call_budget(budget_run) -> None:
    run_id, factory = budget_run
    budget = BudgetService(factory)
    results = await asyncio.gather(
        *(budget.reserve_call(run_id, f"op-{i}", "hash", 20) for i in range(3)),
        return_exceptions=True,
    )
    assert sum(isinstance(item, DomainError) for item in results) == 1
    async with factory() as session:
        run = await session.get(Run, run_id)
        assert run.reserved_calls == 2
        assert run.reserved_tokens == 40


async def test_settlement_is_idempotent_and_releases_only_known_usage(budget_run) -> None:
    run_id, factory = budget_run
    budget = BudgetService(factory)
    reservation = await budget.reserve_call(run_id, "operation", "hash", 60)
    await budget.mark_sent(reservation.call_id)
    await budget.settle_call(reservation.call_id, 12, {"answer": "done"})
    await budget.settle_call(reservation.call_id, 12, {"answer": "done"})
    async with factory() as session:
        run = await session.get(Run, run_id)
        assert (run.used_calls, run.reserved_calls) == (1, 0)
        assert (run.used_tokens, run.reserved_tokens) == (12, 0)
    cached = await budget.reserve_call(run_id, "operation", "hash", 60)
    assert cached.cached_output == {"answer": "done"}


async def test_unknown_call_keeps_token_reservation_and_blocks_automatic_retry(budget_run) -> None:
    run_id, factory = budget_run
    budget = BudgetService(factory)
    reservation = await budget.reserve_call(run_id, "operation", "hash", 60)
    await budget.mark_sent(reservation.call_id)
    await budget.mark_unknown(reservation.call_id)
    with pytest.raises(DomainError) as exc:
        await budget.reserve_call(run_id, "operation", "hash", 60)
    assert exc.value.code == "MODEL_TIMEOUT_UNKNOWN"
    with pytest.raises(DomainError) as other:
        await budget.reserve_call(run_id, "another-operation", "different", 10)
    assert other.value.code == "UNRESOLVED_MODEL_CALLS"
    async with factory() as session:
        run = await session.get(Run, run_id)
        assert run.used_calls == 1
        assert run.reserved_tokens == 60


async def test_known_result_without_usage_is_cached_but_not_charged_as_zero(budget_run) -> None:
    run_id, factory = budget_run
    budget = BudgetService(factory)
    reservation = await budget.reserve_call(run_id, "operation", "hash", 60)
    await budget.mark_sent(reservation.call_id)
    await budget.settle_call(reservation.call_id, None, {"answer": "done"})
    cached = await budget.reserve_call(run_id, "operation", "hash", 60)
    assert cached.cached_output == {"answer": "done"}
    async with factory() as session:
        run = await session.get(Run, run_id)
        assert run.reserved_tokens == 60
