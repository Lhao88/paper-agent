import asyncio
import hashlib
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

from app.agents.context import AgentContext
from app.agents.reading import ReadingAgent
from app.db import Artifact
from app.errors import DomainError
from app.repositories.artifacts import ArtifactRepository
from app.schemas.contracts import (
    PaperRecord,
    PreselectionResult,
    ResearchPlan,
    ScreeningCard,
    SelectionResult,
)
from app.screening.preselect import preselect
from app.screening.select import select_deep_reads
from app.screening.strategies import select_top_k


class ScreeningBundle(BaseModel):
    preselection: PreselectionResult
    cards: list[ScreeningCard]
    selection: SelectionResult
    selection_artifact_id: UUID
    failures: list[dict[str, str]]


async def screen_and_select(
    papers: list[PaperRecord],
    plan: ResearchPlan,
    context: AgentContext,
    manual_ids: list[UUID] | None = None,
) -> ScreeningBundle:
    factory = context.require_repositories().factory
    if len(set(manual_ids or [])) > context.settings.max_deep_read_papers:
        raise DomainError("SELECTION_BUDGET_CONFLICT", "人工精读数量超过预算，尚未派发模型调用。")
    preselection = preselect(papers, plan.questions, context.settings.max_screen_papers, manual_ids)
    async with factory() as session:
        already = set(
            await session.scalars(
                select(Artifact.paper_id)
                .where(
                    Artifact.run_id == context.run_id,
                    Artifact.kind == "screening",
                    Artifact.paper_id.is_not(None),
                )
                .distinct()
            )
        )
    remaining = max(0, context.settings.max_screen_papers - len(already))
    allowed = []
    for identifier in preselection.selected_ids:
        if identifier in already or remaining > 0:
            allowed.append(identifier)
            if identifier not in already:
                remaining -= 1
    if not set(manual_ids or []) <= set(allowed):
        raise DomainError(
            "SELECTION_BUDGET_CONFLICT", "人工选择需要新增初读，但本次累计初读预算不足。"
        )
    preselection.deferred_ids.extend(
        identifier for identifier in preselection.selected_ids if identifier not in allowed
    )
    preselection.selected_ids = allowed
    by_id = {paper.paper_id: paper for paper in papers}
    semaphore = asyncio.Semaphore(context.settings.read_concurrency)
    failures: list[dict[str, str]] = []

    async def screen_one(paper_id: UUID) -> ScreeningCard | None:
        async with semaphore:
            context.check_cancelled()
            paper = by_id[paper_id]
            if context.settings.research_strategy == "A2":
                return ScreeningCard(
                    paper_id=paper_id,
                    summary_zh="消融实验：跳过摘要模型初读。",
                    matched_question_ids=[],
                    relevance=None,
                    decision="insufficient_info",
                    reason="固定顺序处理同一候选池，遵守相同全局预算。",
                    missing_information=["abstract_screening_skipped"],
                    material_basis="metadata_only",
                )
            digest = hashlib.sha256(
                (paper.model_dump_json() + plan.model_dump_json()).encode()
            ).hexdigest()
            operation = f"screen:{plan.plan_id}:{paper_id}:{digest[:16]}"
            async with factory() as session:
                cached = await session.scalar(
                    select(Artifact).where(
                        Artifact.run_id == context.run_id,
                        Artifact.operation_key == operation,
                    )
                )
                if cached is not None:
                    return ScreeningCard.model_validate(cached.payload_json)
            try:
                card = await ReadingAgent().screen(paper, plan, context)
            except DomainError as exc:
                failures.append(
                    {"paper_id": str(paper_id), "code": exc.code, "message": exc.message}
                )
                return None
            async with factory.begin() as session:
                artifact = await ArtifactRepository(session).get_or_create(
                    context.run_id,
                    operation,
                    "screening",
                    card.model_dump(mode="json"),
                    digest,
                )
                artifact.paper_id = paper_id
            return card

    results = await asyncio.gather(
        *(screen_one(identifier) for identifier in preselection.selected_ids)
    )
    context.check_cancelled()
    cards = [card for card in results if card is not None]
    if context.settings.research_strategy in {"B0", "B1", "A1", "A2"}:
        selection = select_top_k(
            cards,
            plan,
            papers,
            context.settings.max_deep_read_papers,
            manual_ids,
            fixed_order=context.settings.research_strategy == "A2",
        )
    else:
        selection = select_deep_reads(
            cards, plan, papers, context.settings.max_deep_read_papers, manual_ids
        )
    digest = hashlib.sha256(selection.model_dump_json().encode()).hexdigest()
    preselection_digest = hashlib.sha256(preselection.model_dump_json().encode()).hexdigest()
    async with factory.begin() as session:
        await ArtifactRepository(session).get_or_create(
            context.run_id,
            f"preselect:{plan.plan_id}:{preselection_digest}",
            "preselection",
            preselection.model_dump(mode="json"),
            preselection_digest,
        )
        saved = await ArtifactRepository(session).get_or_create(
            context.run_id,
            f"selection:{plan.plan_id}:{digest}",
            "selection",
            selection.model_dump(mode="json"),
            digest,
        )
        selection_id = saved.id
    return ScreeningBundle(
        preselection=preselection,
        cards=cards,
        selection=selection,
        selection_artifact_id=selection_id,
        failures=failures,
    )
