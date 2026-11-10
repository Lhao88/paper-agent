import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.context import AgentContext
from app.agents.retrieval import RetrievalAgent
from app.db import Artifact, Document, Paper, PaperSource, ProjectPaper, Task
from app.errors import DomainError
from app.schemas.contracts import (
    PaperRecord,
    QueryPlan,
    ResearchPlan,
    RetrievalResult,
    SearchQuery,
    SourceRecord,
)
from app.services.literature import SearchRequest
from app.sources.base import PaperSource as SourceAdapter
from app.worker.claim import RunLease, lock_owned


def client_query(task_id: UUID, request: SearchRequest, plan: ResearchPlan) -> QueryPlan:
    return QueryPlan(
        scope=plan.scope,
        queries=[
            SearchQuery(
                query_id=f"client-{task_id}",
                question_ids=request.question_ids,
                provider=request.source,
                terms=request.query,
                year_from=plan.scope.year_from,
                year_to=plan.scope.year_to,
                languages=plan.scope.languages,
            )
        ],
    )


def search_outcome(result: RetrievalResult) -> tuple[str, dict[str, object] | None]:
    errors = {
        "BUDGET_EXHAUSTED",
        "SOURCE_UNAVAILABLE",
        "SOURCE_RATE_LIMITED",
        "SOURCE_PARSE_FAILED",
        "SOURCE_NOT_ENABLED",
        "OPENALEX_KEY_REQUIRED_FOR_CURSOR",
        "INVALID_QUERY",
    }
    codes = [warning.split(":", 1)[0] for warning in result.warnings]
    code = next((value for value in codes if value in errors), None)
    if code is None:
        return "completed", None
    status = (
        "partial"
        if result.records
        else "budget_exhausted"
        if code == "BUDGET_EXHAUSTED"
        else "failed"
    )
    return status, {"code": code, "message": "检索未完整执行，请检查来源警告及剩余预算。"}


async def drain_search_tasks(
    context: AgentContext,
    factory: async_sessionmaker[AsyncSession],
    lease: RunLease,
    plan: ResearchPlan,
    sources: dict[str, SourceAdapter],
) -> list[RetrievalResult]:
    results: list[RetrievalResult] = []
    task: Task | None
    # A completed tool task is durable business state, independent of the node checkpoint.
    # Rebuild all its results before processing newly accepted tasks, without network calls.
    async with factory() as session:
        finished = list(
            await session.scalars(
                select(Task)
                .where(
                    Task.run_id == context.run_id,
                    Task.operation == "source_search",
                    Task.client_request_key.is_not(None),
                    Task.status.not_in(["queued", "running"]),
                )
                .order_by(Task.created_at, Task.id)
            )
        )
        for task in finished:
            if task.output_artifact_id:
                artifact = await session.get(Artifact, task.output_artifact_id)
            else:
                query = client_query(task.id, SearchRequest.model_validate(task.input_json), plan)
                digest = hashlib.sha256(query.model_dump_json().encode()).hexdigest()
                artifact = await session.scalar(
                    select(Artifact).where(
                        Artifact.run_id == context.run_id,
                        Artifact.operation_key == f"retrieval:{digest}",
                    )
                )
            if artifact is not None and artifact.run_id == context.run_id:
                results.append(RetrievalResult.model_validate(artifact.payload_json))
            elif task.status in {"completed", "partial", "budget_exhausted"}:
                raise DomainError(
                    "SOURCE_RESULT_MISSING", "已完成追加检索的持久结果缺失，停止而不重复派发。"
                )
            elif task.error_json:
                results.append(
                    RetrievalResult(
                        records=[],
                        warnings=[str(task.error_json.get("code", "SOURCE_UNAVAILABLE"))],
                    )
                )
    while True:
        async with factory.begin() as session:
            run = await lock_owned(session, lease)
            task = await session.scalar(
                select(Task)
                .where(
                    Task.run_id == run.id,
                    Task.operation == "source_search",
                    Task.client_request_key.is_not(None),
                    Task.status.in_(["queued", "running"]),
                )
                .order_by(Task.created_at, Task.id)
                .limit(1)
                .with_for_update()
            )
            if task is None:
                run.retrieval_accepting = False
                break
            task.status, task.started_at = "running", datetime.now(UTC)
            task_id, request = task.id, SearchRequest.model_validate(task.input_json)
        try:
            limited = replace(
                context,
                settings=context.settings.model_copy(
                    update={"max_candidates": min(request.limit, context.settings.max_candidates)}
                ),
            )
            query = client_query(task_id, request, plan)
            result = await RetrievalAgent(sources).retrieve(query, limited)
            results.append(result)
            status, error = search_outcome(result)
            async with context.require_repositories().factory.begin() as session:
                stored = await session.get(Task, task_id)
                if stored:
                    digest = hashlib.sha256(query.model_dump_json().encode()).hexdigest()
                    artifact = await session.scalar(
                        select(Artifact).where(
                            Artifact.run_id == context.run_id,
                            Artifact.operation_key == f"retrieval:{digest}",
                        )
                    )
                    stored.status, stored.error_json = status, error
                    stored.output_artifact_id = artifact.id if artifact else None
                    stored.finished_at = datetime.now(UTC)
                    stored.output_json = {
                        "paper_ids": [str(paper.paper_id) for paper in result.records],
                        "count": len(result.records),
                        "warnings": result.warnings,
                    }
        except DomainError as exc:
            results.append(RetrievalResult(records=[], warnings=[exc.code]))
            async with context.require_repositories().factory.begin() as session:
                stored = await session.get(Task, task_id)
                if stored:
                    stored.status, stored.finished_at = "failed", datetime.now(UTC)
                    stored.error_json = {"code": exc.code, "message": exc.message}
    return results


async def manual_materials(
    context: AgentContext, project_id: UUID
) -> tuple[list[PaperRecord], list[UUID], set[UUID]]:
    async with context.require_repositories().factory() as session:
        members = list(
            await session.scalars(
                select(ProjectPaper).where(
                    ProjectPaper.project_id == project_id, ProjectPaper.user_decision.is_not(None)
                )
            )
        )
        includes = [member.paper_id for member in members if member.user_decision == "include"]
        excludes = {member.paper_id for member in members if member.user_decision == "exclude"}
        papers = []
        for paper_id in includes:
            paper = await session.get(Paper, paper_id)
            sources = list(
                await session.scalars(
                    select(PaperSource).where(
                        PaperSource.paper_id == paper_id, PaperSource.owner_project_id == project_id
                    )
                )
            )
            if paper is None or not sources:
                continue
            document = await session.scalar(
                select(Document)
                .where(Document.paper_id == paper_id, Document.owner_project_id == project_id)
                .limit(1)
            )
            if document is None:
                continue
            papers.append(
                PaperRecord(
                    paper_id=paper.id,
                    title=paper.title,
                    authors=paper.authors_json,
                    year=paper.year,
                    doi=paper.canonical_doi,
                    source_id=document.source_id,
                    sources=[
                        SourceRecord(
                            source_id=source.id,
                            provider=source.provider,
                            provider_id=source.provider_id,
                            version_label=source.version_label,
                            abstract=source.abstract_text,
                        )
                        for source in sources
                    ],
                )
            )
        return papers, includes, excludes
