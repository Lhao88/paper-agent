from langgraph.checkpoint.memory import MemorySaver

from app.workflow.coverage_flow import coverage_stop_reason, frozen_research_rounds
from app.workflow.graph import build_coverage_graph, build_graph, route_after_note
from app.workflow.state import initial_state


def test_required_columns_without_new_relevant_papers_stop_for_writing() -> None:
    assert (
        coverage_stop_reason(
            existing="",
            round_index=0,
            unmet_question_ids=[],
            new_relevant_papers=0,
            consecutive_saturated_rounds=0,
            remaining_source_requests=4,
            remaining_llm_calls=4,
            frozen_max_rounds=4,
        )
        == "requirements_met"
    )


def test_required_columns_with_new_relevant_papers_do_not_stop_by_themselves() -> None:
    assert (
        coverage_stop_reason(
            existing="",
            round_index=0,
            unmet_question_ids=[],
            new_relevant_papers=1,
            consecutive_saturated_rounds=0,
            remaining_source_requests=4,
            remaining_llm_calls=4,
            frozen_max_rounds=4,
        )
        == ""
    )


def test_two_saturated_rounds_budget_or_frozen_limit_each_stop() -> None:
    assert (
        coverage_stop_reason(
            existing="",
            round_index=1,
            unmet_question_ids=["q1"],
            new_relevant_papers=0,
            consecutive_saturated_rounds=2,
            remaining_source_requests=4,
            remaining_llm_calls=4,
            frozen_max_rounds=4,
        )
        == "saturated"
    )
    assert (
        coverage_stop_reason(
            existing="",
            round_index=0,
            unmet_question_ids=["q1"],
            new_relevant_papers=1,
            consecutive_saturated_rounds=0,
            remaining_source_requests=0,
            remaining_llm_calls=0,
            frozen_max_rounds=4,
        )
        == "budget_exhausted"
    )
    assert (
        coverage_stop_reason(
            existing="",
            round_index=0,
            unmet_question_ids=["q1"],
            new_relevant_papers=1,
            consecutive_saturated_rounds=0,
            remaining_source_requests=3,
            remaining_llm_calls=3,
            frozen_max_rounds=4,
            time_exhausted=True,
        )
        == "budget_exhausted"
    )
    assert (
        coverage_stop_reason(
            existing="",
            round_index=0,
            unmet_question_ids=["q1"],
            new_relevant_papers=1,
            consecutive_saturated_rounds=0,
            remaining_source_requests=3,
            remaining_llm_calls=3,
            frozen_max_rounds=1,
        )
        == "rounds"
    )


def test_frozen_round_limit_ignores_later_process_settings() -> None:
    assert frozen_research_rounds({"max_research_rounds": 1}, {"max_research_rounds": 1}) == 1
    assert frozen_research_rounds({}, {"max_research_rounds": 2}) == 2
    assert frozen_research_rounds({"max_research_rounds": 8}, {"max_research_rounds": 1}) == 4


def test_coverage_graph_loops_then_uses_existing_writing_nodes() -> None:
    nodes = _nodes()
    coverage = build_coverage_graph(nodes, MemorySaver()).get_graph()
    edges = {(edge.source, edge.target) for edge in coverage.edges}
    assert ("note", "begin_round") in edges
    assert ("note", "write") in edges
    assert ("write", "validate") in edges
    assert ("validate", "finalize") in edges
    assert route_after_note(_state("")) == "begin_round"
    assert route_after_note(_state("rounds")) == "write"
    legacy = build_graph(nodes, MemorySaver()).get_graph()
    names = {node.id for node in legacy.nodes.values()}
    assert {
        "plan",
        "approve_plan",
        "retrieve",
        "screen",
        "select",
        "read",
        "analyze",
        "decide",
        "write",
        "validate",
        "finalize",
    } <= names
    assert "begin_round" not in names
    assert "draft_spec" not in names


class _Nodes:
    def __getattr__(self, name: str):
        async def _node(state: dict[str, object]) -> dict[str, object]:
            return {}

        return _node


def _nodes() -> _Nodes:
    return _Nodes()


def _state(stop_reason: str) -> dict[str, object]:
    state = initial_state("run")
    state["stop_reason"] = stop_reason
    return state
