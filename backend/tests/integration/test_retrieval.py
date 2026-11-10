from unittest.mock import AsyncMock
from uuid import uuid4

from app.agents.context import AgentContext, RepositoryAccess
from app.agents.retrieval import RetrievalAgent
from app.db import Run
from app.db.session import create_engine, get_test_settings, session_factory
from app.errors import DomainError
from app.llm.budget import BudgetService
from app.llm.gateway import ModelGateway
from app.repositories.projects import ProjectRepository
from app.schemas.contracts import (
    PaperRecord,
    QueryPlan,
    Scope,
    SearchPage,
    SearchQuery,
    SourceRecord,
)


class SourceStub:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.requests = 0

    async def search(self, query, cursor, limit):
        self.requests += 1
        page = next(self.pages)
        if isinstance(page, Exception):
            raise page
        return page


async def test_retrieval_merges_duplicate_doi_and_reuses_saved_results_without_new_requests() -> (
    None
):
    settings = get_test_settings()
    engine = create_engine(settings)
    factory = session_factory(engine)
    doi = f"10.1234/{uuid4()}"
    records = [
        PaperRecord(
            title="Synthetic graph research",
            doi=doi,
            abstract="Original abstract",
            abstract_status="provided",
            sources=[
                SourceRecord(
                    provider="fixture",
                    provider_id=str(uuid4()),
                    version_label="v1",
                    abstract="Original abstract",
                )
            ],
        )
        for _ in range(2)
    ]
    source = SourceStub([SearchPage(records=records, raw_count=2)])
    try:
        async with factory.begin() as session:
            repo = ProjectRepository(session)
            project = await repo.create("检索测试", "synthetic test")
            run = await repo.create_run(project.id, "run", "hash", {}, {})
            run_id = run.id
        context = AgentContext(
            run_id,
            None,
            AsyncMock(spec=ModelGateway),
            BudgetService(factory),
            settings,
            RepositoryAccess(factory),
        )
        query = QueryPlan(
            queries=[
                SearchQuery(query_id="s1", question_ids=["q1"], provider="fixture", terms="graph")
            ]
        )
        agent = RetrievalAgent({"fixture": source})
        result = await agent.retrieve(query, context)
        repeat = await agent.retrieve(query, context)
        assert len(result.records) == 1
        assert len(result.records[0].sources) == 2
        assert repeat.records[0].paper_id == result.records[0].paper_id
        assert source.requests == 1
        async with factory() as session:
            stored = await session.get(Run, run_id)
            assert stored.used_source_requests == 1
    finally:
        await engine.dispose()


async def test_scope_year_filter_is_enforced_even_when_a_source_ignores_it() -> None:
    settings = get_test_settings()
    engine = create_engine(settings)
    factory = session_factory(engine)
    source = SourceStub(
        [
            SearchPage(
                records=[
                    PaperRecord(
                        title=f"Synthetic {year}",
                        year=year,
                        sources=[
                            SourceRecord(
                                provider="fixture", provider_id=str(uuid4()), version_label="v1"
                            )
                        ],
                    )
                    for year in (2020, 2024)
                ],
                raw_count=2,
            )
        ]
    )
    try:
        async with factory.begin() as session:
            repo = ProjectRepository(session)
            project = await repo.create("年份过滤", "synthetic test")
            run = await repo.create_run(project.id, "run", "hash", {}, {})
            run_id = run.id
        context = AgentContext(
            run_id,
            None,
            AsyncMock(spec=ModelGateway),
            BudgetService(factory),
            settings,
            RepositoryAccess(factory),
        )
        query = QueryPlan(
            scope=Scope(year_from=2022),
            queries=[
                SearchQuery(
                    query_id="s",
                    question_ids=["q1"],
                    provider="fixture",
                    terms="research",
                    year_from=2022,
                )
            ],
        )
        result = await RetrievalAgent({"fixture": source}).retrieve(query, context)
        assert [record.year for record in result.records] == [2024]
        assert result.filtered_out[0]["reason"] == "YEAR_BEFORE_SCOPE"
    finally:
        await engine.dispose()


async def test_one_failed_source_does_not_erase_other_results_and_candidate_cap_is_enforced() -> (
    None
):
    settings = get_test_settings().model_copy(update={"max_candidates": 1})
    engine = create_engine(settings)
    factory = session_factory(engine)
    first = SourceStub([DomainError("SOURCE_UNAVAILABLE", "fixture failure")])
    second = SourceStub(
        [
            SearchPage(
                records=[
                    PaperRecord(
                        title=f"Synthetic paper {i}",
                        sources=[
                            SourceRecord(
                                provider="fixture",
                                provider_id=str(uuid4()),
                                version_label="v1",
                            )
                        ],
                    )
                    for i in range(3)
                ],
                raw_count=3,
            )
        ]
    )
    try:
        async with factory.begin() as session:
            repo = ProjectRepository(session)
            project = await repo.create("来源失败测试", "synthetic test")
            run = await repo.create_run(project.id, "run", "hash", {}, {})
            run_id = run.id
        context = AgentContext(
            run_id,
            None,
            AsyncMock(spec=ModelGateway),
            BudgetService(factory),
            settings,
            RepositoryAccess(factory),
        )
        query = QueryPlan(
            queries=[
                SearchQuery(query_id=str(i), question_ids=["q1"], provider=name, terms="graph")
                for i, name in enumerate(("first", "second"))
            ]
        )
        result = await RetrievalAgent({"first": first, "second": second}).retrieve(query, context)
        assert len(result.records) == 1
        assert "SOURCE_UNAVAILABLE:first" in result.warnings
        assert "CANDIDATE_LIMIT_REACHED" in result.warnings
    finally:
        await engine.dispose()
