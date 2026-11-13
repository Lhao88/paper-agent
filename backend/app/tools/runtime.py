import hashlib
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import cast
from uuid import UUID

import httpx
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context import AgentContext
from app.planning.admit import AdmissionResult
from app.schemas.contracts import (
    ChunkRecord,
    ExtractionOutput,
    ResearchSpec,
    RetrievalResult,
    RoundAction,
    SearchQuery,
    StrictModel,
)
from app.sources.base import PaperSource
from app.tools.citations import CitationExpansion, expand_citations
from app.tools.search_in_paper import search_in_paper
from app.tools.search_works import search_works


class RoundExecution(StrictModel):
    executed_action_ids: list[str]
    retrieval: RetrievalResult
    citation_warnings: list[str] = Field(default_factory=list)
    in_paper_failures: list[str] = Field(default_factory=list)


async def execute_admitted(
    admission: AdmissionResult,
    *,
    context: AgentContext,
    spec: ResearchSpec,
    round_index: int,
    sources: Mapping[str, PaperSource],
    project_id: UUID,
    provider_ids: Mapping[UUID, str],
    chunks_by_paper: Mapping[UUID, Sequence[ChunkRecord]],
    extract: Callable[[list[ChunkRecord]], Awaitable[ExtractionOutput]],
    session: AsyncSession | None = None,
    client: httpx.AsyncClient | None = None,
) -> RoundExecution:
    """只执行准入结果里的动作。被拒绝的动作不发起来源请求或模型调用。"""
    context.check_cancelled()
    rejected = {item.action_id for item in admission.rejected}
    queries: list[SearchQuery] = []
    executed: list[str] = []
    citation_warnings: list[str] = []
    in_paper_failures: list[str] = []
    for action in admission.actions:
        if action.action_id in rejected:
            continue
        if action.kind == "search_works":
            queries.extend(await _search_queries(action, context, spec, round_index))
            if action.query and action.providers:
                executed.append(action.action_id)
        elif action.kind == "expand_citations":
            warnings = await _expand(action, context, project_id, provider_ids, session, client)
            if warnings is not None:
                citation_warnings.extend(warnings)
                executed.append(action.action_id)
        elif action.kind == "search_in_paper":
            failure = await _search_paper(action, context, round_index, chunks_by_paper, extract)
            if failure is not None:
                in_paper_failures.append(failure)
            executed.append(action.action_id)
        elif action.kind == "stop":
            executed.append(action.action_id)
    retrieval = (
        await search_works(queries, dict(sources))
        if queries
        else RetrievalResult(records=[], warnings=[])
    )
    return RoundExecution(
        executed_action_ids=executed,
        retrieval=retrieval,
        citation_warnings=citation_warnings,
        in_paper_failures=in_paper_failures,
    )


async def _search_queries(
    action: RoundAction,
    context: AgentContext,
    spec: ResearchSpec,
    round_index: int,
) -> list[SearchQuery]:
    if not action.query or not action.providers:
        return []
    queries: list[SearchQuery] = []
    for provider in action.providers:
        await context.budget.reserve_source_request(
            context.run_id, context.settings.max_source_requests
        )
        queries.append(
            SearchQuery(
                query_id=f"round-{round_index}-{action.action_id}-{provider}",
                question_ids=action.question_ids,
                provider=provider,
                terms=action.query,
                year_from=spec.scope.year_from,
                year_to=spec.scope.year_to,
                languages=list(spec.scope.languages),
            )
        )
    return queries


async def _expand(
    action: RoundAction,
    context: AgentContext,
    project_id: UUID,
    provider_ids: Mapping[UUID, str],
    session: AsyncSession | None,
    client: httpx.AsyncClient | None,
) -> list[str] | None:
    if action.direction is None or not action.providers:
        return None
    calls = [
        (paper_id, provider_ids[paper_id])
        for paper_id in action.paper_ids
        if paper_id in provider_ids
    ]
    if not calls:
        return None
    await context.budget.reserve_source_request(
        context.run_id, context.settings.max_source_requests
    )
    warnings: list[str] = []
    for paper_id, provider_paper_id in calls:
        expansion: CitationExpansion = await expand_citations(
            cast(AsyncSession, session),
            project_id=project_id,
            from_paper_id=paper_id,
            provider_paper_id=provider_paper_id,
            provider=action.providers[0],
            direction=action.direction,
            limit=context.settings.max_citation_neighbors,
            client=cast(httpx.AsyncClient, client),
            settings=context.settings,
        )
        warnings.extend(expansion.warnings)
    return warnings


async def _search_paper(
    action: RoundAction,
    context: AgentContext,
    round_index: int,
    chunks_by_paper: Mapping[UUID, Sequence[ChunkRecord]],
    extract: Callable[[list[ChunkRecord]], Awaitable[ExtractionOutput]],
) -> str | None:
    await context.budget.reserve_call(
        context.run_id,
        f"tool:search_in_paper:{round_index}:{action.action_id}",
        _input_hash(action),
        512,
    )
    chunks = [
        chunk
        for paper_id in action.paper_ids
        for chunk in chunks_by_paper.get(paper_id, ())
    ]
    found = await search_in_paper(
        chunks,
        action.query or "",
        context.settings.embedding_mode,
        limit=5,
        extract=extract,
    )
    return found.failure


def _input_hash(action: RoundAction) -> str:
    return hashlib.sha256(action.model_dump_json().encode()).hexdigest()
