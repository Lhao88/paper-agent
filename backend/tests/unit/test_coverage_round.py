from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.planning.admit import PaperAdmission, admit_actions
from app.schemas.contracts import PaperRecord, ResearchPlan, RetrievalResult, RoundAction, RoundPlan
from app.tools.citations import CitationExpansion
from app.tools.search_in_paper import SearchInPaperResult
from app.workflow import coverage_flow
from app.workflow.state import initial_state
from tests.unit.test_admit import action, coverage, research_spec
from tests.unit.test_planning import context_with
from tests.unit.test_round_planner import _page


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class _Nodes:
    def __init__(self) -> None:
        self.context = context_with(None)
        self.saved: dict[str, dict[str, object]] = {}

    def factory(self):
        return _Session()

    async def enter(self, stage: str) -> None:
        return None

    async def get_plan(self, state: dict[str, object]) -> ResearchPlan:
        spec = research_spec()
        return ResearchPlan(
            topic=spec.topic,
            questions=spec.questions,
            scope=spec.scope,
            plan_id=uuid4(),
            project_id=uuid4(),
            version=1,
        )

    async def load(self, identifier: str, schema: type):
        if schema.__name__ == "NotebookPage":
            return _PAGES[identifier]
        if schema.__name__ == "CoverageReport":
            return coverage()
        if schema.__name__ == "RetrievalResult":
            payload = self.saved[f"coverage-round:{self.context.run_id}:1"]
            return RetrievalResult.model_validate(payload)
        raise AssertionError(schema)

    async def save(self, key: str, kind: str, value) -> object:
        self.saved[key] = value.model_dump(mode="json")
        return uuid4()


_PAGES = {
    "n0": _page(0, "缺口-第一页"),
    "n1": _page(1, "缺口-第二页"),
    "n2": _page(2, "缺口-第三页"),
}


async def test_unfinished_round_keeps_the_completed_saturation_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def history(nodes, round_index):
        return set(), 1, 0

    async def spec_for(nodes, plan_id):
        return research_spec()

    async def no_claims(nodes, project_id):
        return []

    captured: dict[str, object] = {}

    async def store(nodes, state, report):
        captured["report"] = report
        return uuid4()

    monkeypatch.setattr(coverage_flow, "_coverage_history", history)
    monkeypatch.setattr(coverage_flow, "_spec", spec_for)
    monkeypatch.setattr(coverage_flow, "_claims", no_claims)
    monkeypatch.setattr(coverage_flow, "_remaining", _remaining)
    monkeypatch.setattr(coverage_flow, "_store_round_coverage", store)
    nodes = _Nodes()
    plan = await nodes.get_plan({})
    state = initial_state(str(nodes.context.run_id))
    state["plan_id"] = str(plan.plan_id)
    state["round_index"] = 1
    await coverage_flow.begin_round(nodes, state)
    report = captured["report"]
    assert report.consecutive_saturated_rounds == 1
    assert report.saturated is False
    decision = admit_actions(
        research_spec(),
        [action("stop", action_id="stop", providers=[], query=None)],
        report,
        [],
        remaining_source_requests=4,
        remaining_llm_calls=4,
        remaining_deep_reads=4,
    )
    assert decision.synthesized_from_gap is not None
    assert decision.rejected[0].reason == "unmet_coverage"


async def test_propose_passes_only_the_last_two_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, list[str]] = {}

    async def capture(spec, report, round_index, context, notes=()):
        seen["gaps"] = [page.open_gaps[0] for page in notes]
        return RoundPlan(
            actions=[
                RoundAction(
                    action_id="kept",
                    kind="search_works",
                    question_ids=["q1"],
                    rationale="补缺口",
                    query="graph kept",
                    providers=["openalex"],
                )
            ]
        )

    monkeypatch.setattr(coverage_flow, "propose_round", capture)
    monkeypatch.setattr(coverage_flow, "_artifact", _missing)
    monkeypatch.setattr(coverage_flow, "_spec", _spec)
    nodes = _Nodes()
    state = initial_state(str(nodes.context.run_id))
    state["round_index"] = 3
    state["coverage_artifact_id"] = "coverage"
    state["notebook_ids"] = ["n0", "n1", "n2"]
    await coverage_flow.propose(nodes, state)
    assert seen["gaps"] == ["缺口-第二页", "缺口-第三页"]


async def test_execute_runs_admitted_citation_and_in_paper_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper_id = uuid4()
    calls: dict[str, int] = {"cite": 0, "paper": 0}

    async def expand(*args, **kwargs) -> CitationExpansion:
        calls["cite"] += 1
        return CitationExpansion()

    async def in_paper(*args, **kwargs) -> SearchInPaperResult:
        calls["paper"] += 1
        return SearchInPaperResult(chunks=[])

    async def provider_map(nodes, paper_ids):
        return {paper_id: "s2-seed"}

    async def chunks_for(nodes, paper_ids):
        return {paper_id: []}

    monkeypatch.setattr(coverage_flow, "expand_citations", expand, raising=False)
    monkeypatch.setattr(coverage_flow, "search_in_paper", in_paper, raising=False)
    monkeypatch.setattr(coverage_flow, "_provider_map", provider_map, raising=False)
    monkeypatch.setattr(coverage_flow, "_chunks_for", chunks_for, raising=False)
    monkeypatch.setattr(coverage_flow, "_artifact", _stored)
    monkeypatch.setattr(coverage_flow, "_spec", _spec)
    monkeypatch.setattr(coverage_flow, "_admissions", _admissions)
    monkeypatch.setattr(coverage_flow, "_remaining", _remaining)
    monkeypatch.setattr(coverage_flow, "_persist", _persist)
    monkeypatch.setattr(coverage_flow, "_remember_queries", _noop)
    monkeypatch.setattr(coverage_flow, "_library_excluded", _excluded)
    monkeypatch.setattr(coverage_flow, "manual_materials", _materials)
    monkeypatch.setattr(coverage_flow, "search_works", _search)
    monkeypatch.setattr(coverage_flow, "build_sources", lambda settings, client: {})
    nodes = _Nodes()
    nodes.context.budget.reserve_source_request = _async_none
    plan = await nodes.get_plan({})
    state = initial_state(str(nodes.context.run_id))
    state["plan_id"] = str(plan.plan_id)
    state["round_index"] = 1
    state["coverage_artifact_id"] = "coverage"
    nodes.get_plan = _plan(plan)  # type: ignore[method-assign]
    nodes.saved[f"coverage-plan:{nodes.context.run_id}:1"] = RoundPlan(
        actions=[
            RoundAction(
                action_id="search-1",
                kind="search_works",
                question_ids=["q1"],
                rationale="检索",
                query="graph",
                providers=["openalex"],
            ),
            RoundAction(
                action_id="cite-1",
                kind="expand_citations",
                question_ids=["q1"],
                rationale="引文",
                paper_ids=[paper_id],
                direction="references",
                providers=["semantic_scholar"],
            ),
            RoundAction(
                action_id="paper-1",
                kind="search_in_paper",
                question_ids=["q1"],
                rationale="篇内",
                query="方法",
                paper_ids=[paper_id],
                column_ids=["c1"],
            ),
            RoundAction(
                action_id="fulltext-1",
                kind="read_fulltext",
                question_ids=["q1"],
                rationale="全文",
                paper_ids=[paper_id],
            ),
        ]
    ).model_dump(mode="json")
    monkeypatch.setattr(coverage_flow, "_paper_id", lambda: paper_id, raising=False)
    state.update(await coverage_flow.execute(nodes, state))
    page = await coverage_flow._page(nodes, state)
    assert calls == {"cite": 1, "paper": 1}
    assert page.executed_action_ids == ["search-1", "cite-1", "paper-1"]
    assert "fulltext-1" not in page.executed_action_ids


async def test_failed_citation_and_in_paper_keep_the_saved_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper_id = uuid4()
    saved = PaperRecord(paper_id=paper_id, title="已保存论文", sources=[])
    reserves = {"count": 0}

    async def expand(*args, **kwargs) -> CitationExpansion:
        raise RuntimeError("citation down")

    async def in_paper(*args, **kwargs) -> SearchInPaperResult:
        raise RuntimeError("in-paper down")

    async def provider_map(nodes, paper_ids):
        return {paper_id: "s2-seed"}

    async def chunks_for(nodes, paper_ids):
        return {paper_id: []}

    async def persist(nodes, records, project_id):
        return list(records)

    async def search(*args, **kwargs) -> RetrievalResult:
        return RetrievalResult(records=[saved], warnings=[])

    async def reserve(*args, **kwargs) -> None:
        reserves["count"] += 1

    monkeypatch.setattr(coverage_flow, "expand_citations", expand, raising=False)
    monkeypatch.setattr(coverage_flow, "search_in_paper", in_paper, raising=False)
    monkeypatch.setattr(coverage_flow, "_provider_map", provider_map, raising=False)
    monkeypatch.setattr(coverage_flow, "_chunks_for", chunks_for, raising=False)
    monkeypatch.setattr(coverage_flow, "_artifact", _stored)
    monkeypatch.setattr(coverage_flow, "_spec", _spec)
    monkeypatch.setattr(coverage_flow, "_admissions", _admissions)
    monkeypatch.setattr(coverage_flow, "_remaining", _remaining)
    monkeypatch.setattr(coverage_flow, "_persist", persist)
    monkeypatch.setattr(coverage_flow, "_remember_queries", _noop)
    monkeypatch.setattr(coverage_flow, "_library_excluded", _excluded)
    monkeypatch.setattr(coverage_flow, "manual_materials", _materials)
    monkeypatch.setattr(coverage_flow, "search_works", search)
    monkeypatch.setattr(coverage_flow, "build_sources", lambda settings, client: {})
    monkeypatch.setattr(coverage_flow, "_paper_id", lambda: paper_id, raising=False)
    nodes = _Nodes()
    nodes.context.budget.reserve_source_request = reserve
    nodes.context.budget.reserve_call = _async_none
    plan = await nodes.get_plan({})
    state = initial_state(str(nodes.context.run_id))
    state["plan_id"] = str(plan.plan_id)
    state["round_index"] = 1
    state["coverage_artifact_id"] = "coverage"
    nodes.get_plan = _plan(plan)  # type: ignore[method-assign]
    nodes.saved[f"coverage-plan:{nodes.context.run_id}:1"] = RoundPlan(
        actions=[
            RoundAction(
                action_id="search-1",
                kind="search_works",
                question_ids=["q1"],
                rationale="检索",
                query="graph",
                providers=["openalex"],
            ),
            RoundAction(
                action_id="cite-1",
                kind="expand_citations",
                question_ids=["q1"],
                rationale="引文",
                paper_ids=[paper_id],
                direction="references",
                providers=["semantic_scholar"],
            ),
            RoundAction(
                action_id="paper-1",
                kind="search_in_paper",
                question_ids=["q1"],
                rationale="篇内",
                query="方法",
                paper_ids=[paper_id],
                column_ids=["c1"],
            ),
        ]
    ).model_dump(mode="json")
    state.update(await coverage_flow.execute(nodes, state))
    stored = RetrievalResult.model_validate(
        nodes.saved[f"coverage-round:{nodes.context.run_id}:1"]
    )
    page = await coverage_flow._page(nodes, state)
    assert [item.paper_id for item in stored.records] == [paper_id]
    assert "cite-1" not in page.executed_action_ids
    assert "paper-1" not in page.executed_action_ids
    assert "action_failed:cite-1" in page.source_failures
    assert "action_failed:paper-1" in page.source_failures
    charged = reserves["count"]
    await coverage_flow.execute(nodes, state)
    assert reserves["count"] == charged


def _plan(plan: ResearchPlan):
    async def get_plan(state: dict[str, object]) -> ResearchPlan:
        return plan

    return get_plan


async def _missing(nodes, key: str):
    return None


async def _stored(nodes: _Nodes, key: str):
    payload = nodes.saved.get(key)
    if payload is None:
        return None
    return SimpleNamespace(payload_json=payload, id=uuid4())


async def _spec(nodes, plan_id):
    spec = research_spec()
    scope = spec.scope.model_copy(
        update={"enabled_sources": ["openalex", "semantic_scholar"]}
    )
    return spec.model_copy(update={"scope": scope})


async def _admissions(nodes, project_id):
    paper_id = coverage_flow._paper_id()
    return [
        PaperAdmission(
            paper_id=paper_id,
            status="active",
            relevance=3,
            has_document=True,
            included=True,
            empty_required_column_ids=["c1"],
        )
    ]


async def _remaining(nodes, project_id):
    return 5, 5, 5


async def _persist(nodes, records, project_id):
    return []


async def _noop(*args, **kwargs):
    return None


async def _excluded(nodes, project_id):
    return set()


async def _materials(context, project_id):
    return [], [], set()


async def _search(*args, **kwargs) -> RetrievalResult:
    return RetrievalResult(records=[], warnings=[])


async def _async_none(*args, **kwargs):
    return None
