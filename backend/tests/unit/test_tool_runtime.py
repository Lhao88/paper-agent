from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.context import AgentContext
from app.llm.budget import BudgetService
from app.llm.gateway import ModelGateway
from app.planning.admit import AdmissionResult, RejectedAction
from app.schemas.contracts import (
    ChunkRecord,
    ExtractionOutput,
    PaperRecord,
    SearchPage,
    SourceRecord,
)
from app.tools import runtime
from app.tools.citations import CitationExpansion
from tests.unit.test_admit import action, research_spec
from tests.unit.test_planning import context_with


class RecordingSource:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, query, cursor: str | None, limit: int) -> SearchPage:
        self.queries.append(query.provider)
        source = SourceRecord(
            provider=query.provider,
            provider_id="paper",
            version_label="v1",
        )
        return SearchPage(
            records=[PaperRecord(title=query.terms, sources=[source])],
            raw_count=1,
        )


def _context() -> AgentContext:
    base = context_with(ExtractionOutput(candidates=[]))
    budget = AsyncMock(spec=BudgetService)
    return AgentContext(
        base.run_id,
        None,
        AsyncMock(spec=ModelGateway),
        budget,
        base.settings,
    )


async def test_runtime_runs_only_admitted_actions_and_charges_the_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper_id = uuid4()
    source = RecordingSource()
    citation_calls: list[str] = []

    async def expand_citations(*args, **kwargs) -> CitationExpansion:
        citation_calls.append(kwargs["provider_paper_id"])
        return CitationExpansion()

    monkeypatch.setattr(runtime, "expand_citations", expand_citations)
    context = _context()
    chunk = ChunkRecord(
        chunk_id=uuid4(),
        document_id=uuid4(),
        page_number=1,
        text="graph neural networks",
        text_sha256="a" * 64,
    )

    async def extract(chunks: list[ChunkRecord]) -> ExtractionOutput:
        assert chunks == [chunk]
        return ExtractionOutput(candidates=[])

    result = await runtime.execute_admitted(
        AdmissionResult(
            actions=[
                action("search_works", action_id="search-ok", providers=["arxiv"]),
                action(
                    "expand_citations",
                    action_id="cite-ok",
                    providers=["semantic_scholar"],
                    paper_ids=[paper_id],
                    direction="references",
                    query=None,
                ),
                action(
                    "search_in_paper",
                    action_id="read-ok",
                    paper_ids=[paper_id],
                    column_ids=["c1"],
                    providers=[],
                    query="graph",
                ),
                action("stop", action_id="stop-ok", providers=[], query=None),
            ],
            rejected=[
                RejectedAction(action_id="search-rejected", reason="source_not_enabled"),
            ],
        ),
        context=context,
        spec=research_spec(),
        round_index=1,
        sources={"arxiv": source},
        project_id=uuid4(),
        provider_ids={paper_id: "s2-seed"},
        chunks_by_paper={paper_id: [chunk]},
        extract=extract,
    )
    assert result.executed_action_ids == ["search-ok", "cite-ok", "read-ok", "stop-ok"]
    assert source.queries == ["arxiv"]
    assert citation_calls == ["s2-seed"]
    assert result.retrieval.records[0].title == "graph neural networks"
    assert context.budget.reserve_source_request.await_count == 2
    assert context.budget.reserve_call.await_count == 1
    assert "search-rejected" not in result.executed_action_ids
