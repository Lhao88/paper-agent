from app.llm.base import ModelResult
from app.planning.planner import propose_round
from app.schemas.contracts import NotebookPage, RoundAction, RoundPlan
from tests.unit.test_admit import coverage, research_spec
from tests.unit.test_planning import context_with


def _page(round_index: int, gap: str) -> NotebookPage:
    return NotebookPage(
        round_index=round_index,
        executed_action_ids=[f"done-{round_index}"],
        rejected_actions=[],
        new_paper_ids=[],
        filled_column_ids=[],
        open_gaps=[gap],
        index_mode="bm25",
    )


def _action(action_id: str) -> RoundAction:
    return RoundAction(
        action_id=action_id,
        kind="search_works",
        question_ids=["q1"],
        rationale="补缺口",
        query=f"graph {action_id}",
        providers=["openalex"],
    )


async def test_planner_uses_only_spec_coverage_and_the_last_two_notes() -> None:
    spec = research_spec()
    report = coverage(unmet_question_ids=["q2"])
    notes = [
        _page(0, "缺口-第一页"),
        _page(1, "缺口-第二页"),
        _page(2, "缺口-第三页"),
    ]
    context = context_with(RoundPlan(actions=[_action("kept")]))
    await propose_round(spec, report, 3, context, notes=notes)
    content = context.model_gateway.generate.await_args.args[1][1].content
    assert spec.topic in content
    assert "q2" in content
    assert "缺口-第二页" in content
    assert "缺口-第三页" in content
    assert "缺口-第一页" not in content
    assert "done-0" not in content


async def test_planner_keeps_at_most_six_round_actions() -> None:
    actions = [_action(f"a{index}") for index in range(7)]

    class Parsed:
        def __init__(self) -> None:
            self.actions = actions

    context = context_with(Parsed())
    context.model_gateway.generate.return_value = ModelResult(Parsed(), None, 20)
    plan = await propose_round(research_spec(), coverage(), 1, context, notes=[])
    assert [item.action_id for item in plan.actions] == [f"a{index}" for index in range(6)]
