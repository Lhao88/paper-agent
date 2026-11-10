from uuid import uuid4

from app.schemas.contracts import PaperRecord, Question, ResearchPlan, Scope, ScreeningCard
from app.screening.select import select_deep_reads


def plan() -> ResearchPlan:
    return ResearchPlan(
        topic="topic",
        questions=[
            Question(
                question_id=f"q{i}",
                text_zh=f"问题{i}",
                search_terms_en=[f"term{i}"],
                priority=1,
            )
            for i in range(1, 4)
        ],
        scope=Scope(),
        plan_id=uuid4(),
        project_id=uuid4(),
        version=1,
    )


def card(paper: PaperRecord, score: int | None, matched: list[str]) -> ScreeningCard:
    return ScreeningCard(
        paper_id=paper.paper_id,
        summary_zh="摘要说明",
        matched_question_ids=matched,
        relevance=score,
        decision="candidate" if score else "insufficient_info",
        reason="reason",
        missing_information=[],
        material_basis="abstract",
    )


def test_selection_covers_questions_instead_of_only_taking_highest_relevance() -> None:
    papers = [
        PaperRecord(title=f"paper {i}", abstract=f"content {i}", sources=[]) for i in range(3)
    ]
    cards = [card(papers[0], 4, ["q1"]), card(papers[1], 4, ["q1"]), card(papers[2], 3, ["q2"])]
    result = select_deep_reads(cards, plan(), papers, limit=2)
    assert papers[2].paper_id in result.selected_ids
    assert set(result.covered_question_ids) == {"q1", "q2"}
    assert result.uncovered_question_ids == ["q3"]


def test_selection_does_not_fill_quota_with_weak_or_unknown_relevance() -> None:
    papers = [PaperRecord(title=str(i), sources=[]) for i in range(3)]
    result = select_deep_reads(
        [card(papers[0], 4, ["q1"]), card(papers[1], 1, []), card(papers[2], None, [])],
        plan(),
        papers,
        limit=20,
    )
    assert result.selected_ids == [papers[0].paper_id]


def test_manual_override_is_preserved_and_counted_in_limit() -> None:
    papers = [PaperRecord(title=str(i), sources=[]) for i in range(2)]
    result = select_deep_reads(
        [card(papers[0], 4, ["q1"]), card(papers[1], None, [])],
        plan(),
        papers,
        limit=1,
        manual_ids=[papers[1].paper_id],
    )
    assert result.selected_ids == [papers[1].paper_id]
