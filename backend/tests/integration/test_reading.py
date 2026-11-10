from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from app.agents.context import AgentContext, RepositoryAccess
from app.agents.retrieval import RetrievalAgent
from app.config import PROJECT_ROOT, Settings
from app.db import Chunk, Evidence, ModelCall
from app.db.session import create_engine, get_test_settings, session_factory
from app.documents.reading_service import ReadingService
from app.documents.service import download_selected
from app.errors import DomainError
from app.llm.budget import BudgetService
from app.llm.gateway import ModelGateway
from app.llm.mock import MockModelTransport
from app.repositories.papers import PaperRepository
from app.repositories.projects import ProjectRepository
from app.review.export import export_markdown
from app.review.repository import load_evidence_bundle
from app.review.service import generate_review
from app.schemas.contracts import (
    PaperRecord,
    PlanDraft,
    QueryPlan,
    ResearchPlan,
    SearchQuery,
    SelectionResult,
    SourceRecord,
)
from app.screening.service import screen_and_select
from app.sources.factory import build_sources


async def test_nonselected_paper_is_rejected_before_repository_or_download_access() -> None:
    paper = PaperRecord(title="not selected", sources=[])
    selection = SelectionResult(
        selected_ids=[],
        reasons_by_paper={},
        covered_question_ids=[],
        uncovered_question_ids=[],
        deferred_ids=[paper.paper_id],
    )
    context = AgentContext(
        uuid4(),
        None,
        AsyncMock(spec=ModelGateway),
        AsyncMock(spec=BudgetService),
        Settings(_env_file=None),
    )
    with pytest.raises(DomainError) as exc:
        await download_selected(paper, selection, context)
    assert exc.value.code == "PAPER_NOT_SELECTED"


async def test_selected_pdfs_produce_page_evidence_and_resume_without_model_repeats() -> None:
    settings = get_test_settings()
    engine = create_engine(settings)
    factory = session_factory(engine)
    try:
        async with factory.begin() as session:
            repo = ProjectRepository(session)
            project = await repo.create("全文证据测试", "原创合成资料")
            run = await repo.create_run(project.id, "run", "hash", {}, {})
            run_id, project_id = run.id, project.id
        directory = PROJECT_ROOT / "backend" / "fixtures" / "model"
        draft = PlanDraft.model_validate_json(
            (directory / "PlanDraft.json").read_text(encoding="utf-8")
        )
        plan = ResearchPlan(**draft.model_dump(), plan_id=uuid4(), project_id=project_id, version=1)
        budget = BudgetService(factory)
        context = AgentContext(
            run_id,
            plan.plan_id,
            ModelGateway(
                budget,
                MockModelTransport(directory),
                settings,
            ),
            budget,
            settings,
            RepositoryAccess(factory),
        )
        async with httpx.AsyncClient() as client:
            retrieved = await RetrievalAgent(build_sources(settings, client)).retrieve(
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
        screened = await screen_and_select(retrieved.records, plan, context)
        reader = ReadingService(context)
        first = await reader.read_selected(retrieved.records, screened.selection, plan)
        second = await reader.read_selected(retrieved.records, screened.selection, plan)
        assert len(first.cards) == 2
        assert first.artifact_ids == second.artifact_ids
        assert all(card.reading_scope == "full_text_targeted" for card in first.cards)
        assert all(card.fields.get("method") for card in first.cards)
        async with factory() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(ModelCall)
                .where(
                    ModelCall.run_id == run_id,
                )
            )
            assert count == 4  # two abstract screens plus two extraction batches
            for card in first.cards:
                evidence_id = card.fields["method"][0].evidence_ids[0]
                evidence = await session.get(Evidence, evidence_id)
                chunk = await session.get(Chunk, evidence.chunk_id)
                assert evidence.document_id == card.document_id
                assert evidence.page_number == chunk.page_number
                assert chunk.text[evidence.quote_start : evidence.quote_end] == evidence.quote
                assert "ToyCorpus" in evidence.quote
        review = await generate_review(first.artifact_ids, plan, context)
        resumed_review = await generate_review(first.artifact_ids, plan, context)
        assert review.review_artifact_id == resumed_review.review_artifact_id
        assert len(review.review.references) == 2
        assert review.validation.structural_valid
        assert not review.validation.human_verified
        assert "MOCK_SYNTHETIC_CORPUS" in export_markdown(review.review)
        async with factory.begin() as session:
            other = await ProjectRepository(session).create("其他项目", "cross project")
            other_run = await ProjectRepository(session).create_run(
                other.id, "other", "hash", {}, {}
            )
            other_id = other_run.id
        from dataclasses import replace

        with pytest.raises(DomainError) as denied:
            await load_evidence_bundle(first.artifact_ids, replace(context, run_id=other_id))
        assert denied.value.code == "EVIDENCE_FORBIDDEN"
    finally:
        await engine.dispose()


async def test_unavailable_fulltext_produces_only_abstract_background_with_real_source() -> None:
    settings = get_test_settings()
    engine = create_engine(settings)
    factory = session_factory(engine)
    try:
        async with factory.begin() as session:
            project = await ProjectRepository(session).create("缺全文测试", "synthetic")
            run = await ProjectRepository(session).create_run(project.id, "run", "hash", {}, {})
            source = await PaperRepository(session).upsert_source(
                "fixture",
                str(uuid4()),
                "v1",
                "Unavailable full text",
                None,
                "This abstract describes retrieval only.",
                {},
            )
            await PaperRepository(session).attach(project.id, source.paper_id)
            run_id, project_id = run.id, project.id
            paper = PaperRecord(
                paper_id=source.paper_id,
                title="Unavailable full text",
                source_id=source.id,
                abstract=source.abstract_text,
                abstract_status="provided",
                sources=[
                    SourceRecord(
                        source_id=source.id,
                        provider="fixture",
                        provider_id=source.provider_id,
                        version_label="v1",
                        abstract=source.abstract_text,
                    )
                ],
            )
        directory = PROJECT_ROOT / "backend" / "fixtures" / "model"
        draft = PlanDraft.model_validate_json(
            (directory / "PlanDraft.json").read_text(encoding="utf-8")
        )
        plan = ResearchPlan(**draft.model_dump(), plan_id=uuid4(), project_id=project_id, version=1)
        gateway = AsyncMock(spec=ModelGateway)
        gateway.generate.side_effect = AssertionError(
            "missing fulltext must not trigger extraction"
        )
        context = AgentContext(
            run_id,
            plan.plan_id,
            gateway,
            BudgetService(factory),
            settings,
            RepositoryAccess(factory),
        )
        selection = SelectionResult(
            selected_ids=[paper.paper_id],
            reasons_by_paper={},
            covered_question_ids=[],
            uncovered_question_ids=[],
            deferred_ids=[],
        )
        card, _ = await ReadingService(context).read_one(paper, selection, plan)
        assert card.reading_scope == "abstract_only"
        assert set(card.fields) == {"abstract_background"}
        assert "metric" in card.missing_fields
        async with factory() as session:
            evidence = await session.get(
                Evidence, card.fields["abstract_background"][0].evidence_ids[0]
            )
            assert evidence.basis == "abstract"
            assert evidence.source_id == paper.source_id
            assert evidence.document_id is None
            assert evidence.page_number is None
    finally:
        await engine.dispose()
