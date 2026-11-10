import asyncio
import hashlib
import json
import re
from uuid import UUID

import httpx
from sqlalchemy import select

from app.agents.context import AgentContext
from app.db import Artifact, Run, Task
from app.errors import DomainError
from app.repositories.artifacts import ArtifactRepository
from app.repositories.papers import PaperRepository
from app.schemas.contracts import (
    PaperRecord,
    QueryPlan,
    RetrievalResult,
    SearchPage,
    SearchQuery,
    SourceRecord,
)
from app.sources.base import PaperSource
from app.sources.normalize import normalize_doi


async def _search_page(
    query: SearchQuery,
    cursor: str | None,
    limit: int,
    source: PaperSource,
    context: AgentContext,
) -> SearchPage:
    factory = context.require_repositories().factory
    request_hash = hashlib.sha256(
        json.dumps(
            {
                "query": query.model_dump(),
                "cursor": cursor,
                "limit": limit,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    async with factory.begin() as session:
        completed = await session.scalar(
            select(Task)
            .where(
                Task.run_id == context.run_id,
                Task.operation == "source_search",
                Task.input_hash == request_hash,
                Task.status == "completed",
            )
            .order_by(Task.created_at.desc())
            .limit(1)
        )
        if completed is not None and completed.output_json is not None:
            return SearchPage.model_validate(completed.output_json)
        task = Task(
            run_id=context.run_id,
            role="retrieval",
            operation="source_search",
            status="running",
            input_hash=request_hash,
            input_json={
                "query": query.model_dump(),
                "cursor": cursor,
                "limit": limit,
            },
        )
        session.add(task)
        await session.flush()
        task_id = task.id
    try:
        await context.budget.reserve_source_request(
            context.run_id, context.settings.max_source_requests
        )
        context.check_cancelled()
        page = await source.search(query, cursor, limit)
    except (DomainError, httpx.HTTPError) as exc:
        code = exc.code if isinstance(exc, DomainError) else "SOURCE_UNAVAILABLE"
        async with factory.begin() as session:
            stored_task = await session.get(Task, task_id)
            if stored_task is not None:
                stored_task.status = "failed"
                stored_task.error_json = {"code": code}
        if isinstance(exc, DomainError):
            raise
        raise DomainError("SOURCE_UNAVAILABLE", "论文来源网络请求失败。", retryable=True) from exc
    async with factory.begin() as session:
        stored_task = await session.get(Task, task_id)
        if stored_task is not None:
            stored_task.status = "completed"
            stored_task.output_json = page.model_dump(mode="json")
    return page


async def retrieve_papers(
    query_plan: QueryPlan,
    sources: dict[str, PaperSource],
    context: AgentContext,
) -> RetrievalResult:
    factory = context.require_repositories().factory
    digest = hashlib.sha256(query_plan.model_dump_json().encode()).hexdigest()
    operation_key = f"retrieval:{digest}"
    async with factory() as session:
        cached = await session.scalar(
            select(Artifact).where(
                Artifact.run_id == context.run_id,
                Artifact.operation_key == operation_key,
            )
        )
        if cached is not None:
            return RetrievalResult.model_validate(cached.payload_json)
        run = await session.get(Run, context.run_id)
        if run is None:
            raise DomainError("RUN_NOT_FOUND", "研究不存在。")
        project_id = run.project_id
    by_id: dict[UUID, PaperRecord] = {}
    warnings: list[str] = []
    filtered_out: list[dict[str, str]] = []
    stop = False
    for query in query_plan.queries:
        context.check_cancelled()
        source = sources.get(query.provider)
        if source is None:
            warnings.append(f"SOURCE_NOT_ENABLED:{query.provider}")
            continue
        cursor: str | None = None
        visited: set[str] = set()
        retries = 0
        while not stop:
            context.check_cancelled()
            try:
                page = await _search_page(query, cursor, 100, source, context)
            except DomainError as exc:
                warnings.append(f"{exc.code}:{query.provider}")
                if exc.code in ("RUN_CANCELLED", "RUN_NOT_EXECUTABLE"):
                    raise
                if exc.retryable and retries < context.settings.max_source_retries:
                    retries += 1
                    retry_after = exc.details.get("retry_after")
                    delay = min(retry_after, 30) if isinstance(retry_after, int) else 1
                    await asyncio.sleep(max(0, delay))
                    continue
                stop = exc.code == "BUDGET_EXHAUSTED"
                break
            retries = 0
            warnings.extend(page.warnings)
            for record in page.records:
                year_from = query_plan.scope.year_from if query_plan.scope else query.year_from
                year_to = query_plan.scope.year_to if query_plan.scope else query.year_to
                reason: str | None = None
                if record.year is not None:
                    if year_from is not None and record.year < year_from:
                        reason = "YEAR_BEFORE_SCOPE"
                    if year_to is not None and record.year > year_to:
                        reason = "YEAR_AFTER_SCOPE"
                elif year_from is not None or year_to is not None:
                    warnings.append("SOURCE_YEAR_UNKNOWN")
                material = f"{record.title}\n{record.abstract or ''}"
                if query_plan.scope:
                    for term in query_plan.scope.exclude_terms:
                        if term.strip() and re.search(
                            r"(?<!\w)" + re.escape(term.strip()) + r"(?!\w)",
                            material,
                            re.IGNORECASE,
                        ):
                            reason = "EXCLUDED_TERM"
                            break
                if reason is not None:
                    filtered_out.append(
                        {
                            "title": record.title,
                            "reason": reason,
                            "source_key": record.sources[0].source_key
                            if record.sources
                            else "unknown",
                        }
                    )
                    continue
                async with factory.begin() as session:
                    repo = PaperRepository(session)
                    record_id: UUID | None = None
                    abstract_source_id: UUID | None = None
                    persisted_sources: list[SourceRecord] = []
                    for original_source in record.sources:
                        stored = await repo.upsert_source(
                            original_source.provider,
                            original_source.provider_id,
                            original_source.version_label,
                            record.title,
                            normalize_doi(record.doi),
                            original_source.abstract,
                            original_source.raw_payload,
                            year=record.year,
                            authors=record.authors,
                            metadata=original_source.model_dump(
                                mode="json", exclude={"raw_payload"}
                            ),
                        )
                        record_id = record_id or stored.paper_id
                        persisted_sources.append(
                            original_source.model_copy(update={"source_id": stored.id})
                        )
                        if original_source.source_key == record.abstract_source_key:
                            abstract_source_id = stored.id
                    if record_id is None:
                        warnings.append("SOURCE_RECORD_WITHOUT_IDENTITY")
                        continue
                    await repo.attach(project_id, record_id)
                normalized = record.model_copy(
                    update={
                        "paper_id": record_id,
                        "source_id": abstract_source_id,
                        "doi": normalize_doi(record.doi),
                        "sources": persisted_sources,
                    }
                )
                previous = by_id.get(record_id)
                if previous is not None:
                    merged = {s.source_key: s for s in previous.sources + normalized.sources}
                    chosen = (
                        normalized
                        if previous.abstract is None and normalized.abstract
                        else previous
                    )
                    normalized = chosen.model_copy(update={"sources": list(merged.values())})
                by_id[record_id] = normalized
                if len(by_id) >= context.settings.max_candidates:
                    stop = True
                    warnings.append("CANDIDATE_LIMIT_REACHED")
                    break
            if stop or not page.next_cursor:
                break
            if page.next_cursor in visited:
                warnings.append("SOURCE_REPEATED_CURSOR")
                break
            visited.add(page.next_cursor)
            cursor = page.next_cursor
        if stop:
            break
    result = RetrievalResult(
        records=list(by_id.values()),
        warnings=list(dict.fromkeys(warnings)),
        filtered_out=filtered_out,
    )
    async with factory.begin() as session:
        await ArtifactRepository(session).get_or_create(
            context.run_id,
            operation_key,
            "retrieval",
            result.model_dump(mode="json"),
            digest,
        )
    return result
