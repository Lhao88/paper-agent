from types import SimpleNamespace
from uuid import uuid4

from app.schemas.contracts import CoverageReport, NotebookPage, RetrievalResult
from app.workflow import coverage_flow
from app.workflow.state import initial_state
from tests.unit.test_admit import coverage
from tests.unit.test_planning import context_with


class _Nodes:
    def __init__(self) -> None:
        self.context = context_with(None)
        self.saved: dict[str, dict[str, object]] = {}

    async def enter(self, stage: str) -> None:
        return None

    async def load(self, identifier: str, schema: type):
        if schema is RetrievalResult:
            return RetrievalResult(records=[], warnings=["source_unavailable:openalex"])
        if schema is CoverageReport:
            return coverage()
        raise AssertionError(schema)

    async def save(self, key: str, kind: str, value) -> object:
        self.saved[key] = value.model_dump(mode="json")
        return uuid4()


async def test_total_source_failure_is_written_to_the_note_and_coverage(monkeypatch) -> None:
    nodes = _Nodes()
    state = initial_state(str(nodes.context.run_id))
    state["round_index"] = 1
    state["retrieval_artifact_id"] = "retrieval"
    state["coverage_artifact_id"] = "coverage"

    async def missing(nodes_arg, key: str):
        payload = nodes_arg.saved.get(key)
        if payload is None:
            return None
        return SimpleNamespace(payload_json=payload, id=uuid4())

    async def fresh(nodes_arg, state_arg, new_relevant: int) -> CoverageReport:
        return coverage(corpus_limits=[])

    monkeypatch.setattr(coverage_flow, "_artifact", missing)
    monkeypatch.setattr(coverage_flow, "_fresh_coverage", fresh)
    monkeypatch.setattr(coverage_flow, "_new_relevant", _zero)
    monkeypatch.setattr(coverage_flow, "_frozen_rounds", _rounds)
    monkeypatch.setattr(coverage_flow, "_time_exhausted", _not_exhausted)
    await coverage_flow.note(nodes, state)
    page = NotebookPage.model_validate(
        nodes.saved[f"coverage-note:{nodes.context.run_id}:1"]
    )
    report = CoverageReport.model_validate(
        nodes.saved[f"coverage:{nodes.context.run_id}:1"]
    )
    assert page.source_failures == ["source_failed:openalex"]
    assert "source_failed:openalex" in report.corpus_limits


async def _zero(nodes, state) -> int:
    return 0


async def _rounds(nodes) -> int:
    return 4


async def _not_exhausted(nodes) -> bool:
    return False
