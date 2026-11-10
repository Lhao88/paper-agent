from uuid import uuid4

from app.planning.admit import PaperAdmission, admit_actions
from app.schemas.contracts import (
    CoverageReport,
    CoverageTarget,
    ExtractionColumn,
    InclusionRule,
    Question,
    ResearchSpec,
    RoundAction,
    Scope,
)


def research_spec() -> ResearchSpec:
    return ResearchSpec(
        topic="图神经网络",
        questions=[
            Question(
                question_id=f"q{index}",
                text_zh=f"问题{index}",
                search_terms_en=["graph", "network"],
            )
            for index in range(1, 4)
        ],
        scope=Scope(enabled_sources=["openalex"]),
        inclusion_rules=[InclusionRule(rule_id="r1", polarity="include", text_zh="纳入实验")],
        columns=[
            ExtractionColumn(
                column_id="c1",
                question_id="q1",
                field="method",
                required=True,
                description_zh="方法",
            ),
            ExtractionColumn(
                column_id="c2",
                question_id="q2",
                field="limitation",
                required=True,
                description_zh="局限",
            ),
            ExtractionColumn(
                column_id="c3",
                question_id="q3",
                field="dataset",
                required=False,
                description_zh="数据",
            ),
        ],
        coverage=[
            CoverageTarget(question_id="q1", min_included_papers=1, required_column_ids=["c1"]),
            CoverageTarget(question_id="q2", min_included_papers=1, required_column_ids=["c2"]),
        ],
    )


def coverage(**updates: object) -> CoverageReport:
    payload: dict[str, object] = {
        "round_index": 1,
        "questions": [
            {"included_papers": 0, "filled_required_cells": 0},
            {"included_papers": 0, "filled_required_cells": 0},
            {"included_papers": 0, "filled_required_cells": 0},
        ],
        "cells": [],
        "unmet_question_ids": ["q1"],
        "remaining_source_requests": 5,
        "remaining_llm_calls": 5,
        "remaining_deep_reads": 5,
        "new_relevant_papers_last_round": 1,
        "consecutive_saturated_rounds": 0,
        "corpus_limits": [],
        "saturated": False,
    }
    payload.update(updates)
    return CoverageReport.model_validate(payload)


def paper(**updates: object) -> PaperAdmission:
    payload: dict[str, object] = {
        "paper_id": uuid4(),
        "status": "active",
        "relevance": 4,
        "has_document": True,
        "search_in_paper_calls": 0,
        "empty_required_column_ids": ["c1"],
    }
    payload.update(updates)
    return PaperAdmission.model_validate(payload)


def action(kind: str, **updates: object) -> RoundAction:
    payload: dict[str, object] = {
        "action_id": kind,
        "kind": kind,
        "question_ids": ["q1"],
        "rationale": "测试",
        "query": "graph neural networks",
        "providers": ["openalex"],
    }
    payload.update(updates)
    return RoundAction.model_validate(payload)


def test_unknown_question_column_or_source_is_rejected() -> None:
    result = admit_actions(
        research_spec(),
        [
            action("search_works", action_id="bad-question", question_ids=["missing"]),
            action("search_in_paper", action_id="bad-column", column_ids=["missing"]),
            action("search_works", action_id="bad-source", providers=["cnki"]),
            action("search_works", action_id="empty-query", query=""),
        ],
        coverage(),
        [],
        remaining_source_requests=5,
        remaining_llm_calls=5,
        remaining_deep_reads=5,
    )
    assert [item.action_id for item in result.rejected] == [
        "bad-question",
        "bad-column",
        "bad-source",
        "empty-query",
    ]
    assert {item.reason for item in result.rejected} >= {
        "unknown_question",
        "unknown_column",
        "source_not_enabled",
        "missing_query",
    }


def test_expand_citations_requires_library_direction_and_neighbor_cap() -> None:
    kept = paper()
    excluded = paper(status="excluded")
    result = admit_actions(
        research_spec(),
        [
            action(
                "expand_citations",
                action_id="kept",
                paper_ids=[kept.paper_id],
                direction="references",
                providers=[],
                query=None,
            ),
            action(
                "expand_citations",
                action_id="excluded",
                paper_ids=[excluded.paper_id],
                direction="cited_by",
                providers=[],
                query=None,
            ),
            action(
                "expand_citations",
                action_id="no-direction",
                paper_ids=[kept.paper_id],
                providers=[],
                query=None,
            ),
            action(
                "expand_citations",
                action_id="too-many",
                paper_ids=[kept.paper_id],
                direction="references",
                providers=[],
                query=None,
            ),
        ],
        coverage(unmet_question_ids=[]),
        [kept, excluded],
        remaining_source_requests=5,
        remaining_llm_calls=5,
        remaining_deep_reads=5,
        max_citation_neighbors=15,
        requested_citation_neighbors={"too-many": 40},
    )
    assert [item.action_id for item in result.actions] == ["kept"]
    reasons = {item.action_id: item.reason for item in result.rejected}
    assert reasons["excluded"] == "paper_excluded"
    assert reasons["no-direction"] == "missing_direction"
    assert reasons["too-many"] == "citation_cap"


def test_read_fulltext_rejects_unpinned_low_relevance() -> None:
    low = paper(relevance=2, status="active")
    pinned = paper(relevance=2, status="pinned")
    result = admit_actions(
        research_spec(),
        [
            action(
                "read_fulltext",
                action_id="low",
                paper_ids=[low.paper_id],
                providers=[],
                query=None,
            ),
            action(
                "read_fulltext",
                action_id="pinned",
                paper_ids=[pinned.paper_id],
                providers=[],
                query=None,
            ),
        ],
        coverage(unmet_question_ids=[]),
        [low, pinned],
        remaining_source_requests=5,
        remaining_llm_calls=5,
        remaining_deep_reads=5,
    )
    assert [item.action_id for item in result.actions] == ["pinned"]
    assert result.rejected[0].action_id == "low"
    assert result.rejected[0].reason == "relevance_too_low"


def test_search_in_paper_requires_document_empty_column_and_call_room() -> None:
    ready = paper()
    missing = paper(has_document=False)
    exhausted = paper(search_in_paper_calls=3)
    filled = paper(empty_required_column_ids=[])
    result = admit_actions(
        research_spec(),
        [
            action(
                "search_in_paper",
                action_id="ready",
                paper_ids=[ready.paper_id],
                column_ids=["c1"],
                providers=[],
                query=None,
            ),
            action(
                "search_in_paper",
                action_id="missing-doc",
                paper_ids=[missing.paper_id],
                column_ids=["c1"],
                providers=[],
                query=None,
            ),
            action(
                "search_in_paper",
                action_id="call-cap",
                paper_ids=[exhausted.paper_id],
                column_ids=["c1"],
                providers=[],
                query=None,
            ),
            action(
                "search_in_paper",
                action_id="filled",
                paper_ids=[filled.paper_id],
                column_ids=["c1"],
                providers=[],
                query=None,
            ),
        ],
        coverage(unmet_question_ids=[]),
        [ready, missing, exhausted, filled],
        remaining_source_requests=5,
        remaining_llm_calls=5,
        remaining_deep_reads=5,
        max_search_in_paper_calls_per_paper=3,
    )
    assert [item.action_id for item in result.actions] == ["ready"]
    reasons = {item.action_id: item.reason for item in result.rejected}
    assert reasons == {
        "missing-doc": "missing_document",
        "call-cap": "search_call_cap",
        "filled": "column_not_empty",
    }


def test_source_budget_drops_search_and_reports_exhaustion() -> None:
    result = admit_actions(
        research_spec(),
        [action("search_works", action_id="search")],
        coverage(),
        [],
        remaining_source_requests=0,
        remaining_llm_calls=5,
        remaining_deep_reads=5,
    )
    assert result.actions == []
    assert result.rejected[0].reason == "budget_exhausted"
    assert result.stop_reason == "budget_exhausted"


def test_unmet_stop_is_replaced_by_gap_search() -> None:
    result = admit_actions(
        research_spec(),
        [action("stop", action_id="stop", providers=[], query=None)],
        coverage(unmet_question_ids=["q1"], saturated=False),
        [],
        remaining_source_requests=4,
        remaining_llm_calls=4,
        remaining_deep_reads=4,
    )
    assert result.synthesized_from_gap is not None
    assert result.actions == [result.synthesized_from_gap]
    assert result.synthesized_from_gap.kind == "search_works"
    assert result.synthesized_from_gap.providers == ["openalex"]
    query = result.synthesized_from_gap.query or ""
    assert "方法" in query
    assert "graph" in query
    assert "network" in query
    assert result.rejected[0].reason == "unmet_coverage"
    assert result.synthesized_from_gap.action_id not in {item.action_id for item in result.rejected}


def test_saturated_rounds_accept_stop_without_synthesis() -> None:
    result = admit_actions(
        research_spec(),
        [action("stop", action_id="stop", providers=[], query=None)],
        coverage(saturated=True, consecutive_saturated_rounds=2, unmet_question_ids=["q1"]),
        [],
        remaining_source_requests=4,
        remaining_llm_calls=4,
        remaining_deep_reads=4,
    )
    assert [item.action_id for item in result.actions] == ["stop"]
    assert result.synthesized_from_gap is None
    assert result.rejected == []


def test_round_keeps_only_the_action_cap() -> None:
    result = admit_actions(
        research_spec(),
        [
            action("search_works", action_id="one", query="one"),
            action("search_works", action_id="two", query="two"),
            action("search_works", action_id="three", query="three"),
        ],
        coverage(unmet_question_ids=[]),
        [],
        remaining_source_requests=5,
        remaining_llm_calls=5,
        remaining_deep_reads=5,
        max_actions_per_round=2,
    )
    assert [item.action_id for item in result.actions] == ["one", "two"]
    assert result.rejected[0].action_id == "three"
    assert result.rejected[0].reason == "action_cap"
