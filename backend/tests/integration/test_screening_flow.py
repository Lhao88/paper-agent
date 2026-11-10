from uuid import uuid4

import httpx
from sqlalchemy import func, select

from app.agents.context import AgentContext, RepositoryAccess
from app.agents.retrieval import RetrievalAgent
from app.config import PROJECT_ROOT
from app.db import Document, ModelCall
from app.db.session import create_engine, get_test_settings, session_factory
from app.llm.budget import BudgetService
from app.llm.gateway import ModelGateway
from app.llm.mock import MockModelTransport
from app.repositories.projects import ProjectRepository
from app.schemas.contracts import PlanDraft, QueryPlan, ResearchPlan, SearchQuery
from app.screening.service import screen_and_select
from app.sources.factory import build_sources


async def test_screening_persists_reasons_reuses_cards_and_never_downloads_fulltexts() -> None:
    settings = get_test_settings()
    engine = create_engine(settings)
    factory = session_factory(engine)
    try:
        async with factory.begin() as session:
            repo = ProjectRepository(session)
            project = await repo.create("分层筛选", "原创合成资料")
            run = await repo.create_run(project.id, "run", "hash", {}, {})
            run_id, project_id = run.id, project.id
        fixture = PROJECT_ROOT / "backend" / "fixtures" / "model"
        draft = PlanDraft.model_validate_json(
            (fixture / "PlanDraft.json").read_text(encoding="utf-8")
        )
        plan = ResearchPlan(**draft.model_dump(), plan_id=uuid4(), project_id=project_id, version=1)
        budget = BudgetService(factory)
        gateway = ModelGateway(budget, MockModelTransport(fixture), settings)
        context = AgentContext(
            run_id, plan.plan_id, gateway, budget, settings, RepositoryAccess(factory)
        )
        async with httpx.AsyncClient() as client:
            result = await RetrievalAgent(build_sources(settings, client)).retrieve(
                QueryPlan(
                    queries=[
                        SearchQuery(
                            query_id="s1",
                            question_ids=["q1"],
                            provider="openalex",
                            terms="research",
                        ),
                    ]
                ),
                context,
            )
        async with factory() as session:
            before = await session.scalar(select(func.count()).select_from(Document))
        screened = await screen_and_select(result.records, plan, context)
        repeated = await screen_and_select(result.records, plan, context)
        assert len(screened.cards) == 3
        assert len(screened.selection.selected_ids) == 2
        assert screened.failures == []
        assert screened.selection_artifact_id == repeated.selection_artifact_id
        manual = await screen_and_select(
            result.records, plan, context, manual_ids=[screened.selection.selected_ids[-1]]
        )
        assert (
            manual.selection.reasons_by_paper[str(screened.selection.selected_ids[-1])]
            == "user_selected"
        )
        assert any(
            card.relevance is None and card.decision == "insufficient_info"
            for card in screened.cards
        )
        async with factory() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(ModelCall)
                .where(
                    ModelCall.run_id == run_id,
                )
            )
            after = await session.scalar(select(func.count()).select_from(Document))
        assert count == 2
        assert after == before
    finally:
        await engine.dispose()
