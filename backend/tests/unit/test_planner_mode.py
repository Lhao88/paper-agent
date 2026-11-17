from langgraph.checkpoint.memory import MemorySaver

from app.config import Settings
from app.worker.execute import frozen_planner_mode, mode_budget_caps
from app.workflow.graph import build_graph


class _Nodes:
    def __getattr__(self, name: str):
        async def _node(state: dict[str, object]) -> dict[str, object]:
            return {}

        return _node


def _legacy_stages() -> list[str]:
    following: dict[str, str] = {}
    for edge in build_graph(_Nodes(), MemorySaver()).get_graph().edges:
        if edge.source == "decide":
            if edge.target == "write":
                following["decide"] = "write"
            continue
        following[edge.source] = edge.target
    stages = ["plan"]
    while stages[-1] != "finalize":
        stages.append(following[stages[-1]])
    return stages


def test_development_default_is_coverage_and_legacy_snapshots_keep_their_graph_and_caps() -> None:
    assert Settings(_env_file=None).planner_mode == "coverage"
    legacy = {"planner_mode": "legacy", "max_source_requests": 20, "max_llm_calls": 150}
    assert frozen_planner_mode(legacy, dict(legacy)) == "legacy"
    assert mode_budget_caps(frozen_planner_mode(legacy, dict(legacy))) == (20, 150)
    assert _legacy_stages() == [
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
    ]


def test_matching_snapshots_select_coverage_without_process_config() -> None:
    mode = frozen_planner_mode(
        {"planner_mode": "coverage"},
        {"planner_mode": "coverage"},
    )
    assert mode == "coverage"


def test_matching_legacy_snapshots_ignore_a_later_coverage_process_value() -> None:
    mode = frozen_planner_mode(
        {"planner_mode": "legacy", "process_planner_mode": "coverage"},
        {"planner_mode": "legacy"},
    )
    assert mode == "legacy"


def test_disagreement_does_not_invent_coverage_from_process_config() -> None:
    assert (
        frozen_planner_mode(
            {"planner_mode": "coverage"},
            {"planner_mode": "legacy"},
        )
        == "legacy"
    )


def test_missing_snapshot_mode_stays_on_development_default() -> None:
    assert frozen_planner_mode({}, {}) == "legacy"


def test_one_frozen_snapshot_is_used_when_the_other_has_no_mode() -> None:
    assert frozen_planner_mode({}, {"planner_mode": "coverage"}) == "coverage"
    assert frozen_planner_mode({"planner_mode": "legacy"}, {}) == "legacy"


def test_mode_caps_keep_legacy_at_20_and_150_and_coverage_at_40_and_180() -> None:
    from app.worker.execute import mode_budget_caps

    assert mode_budget_caps("legacy") == (20, 150)
    assert mode_budget_caps("coverage") == (40, 180)
