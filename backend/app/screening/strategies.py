from uuid import UUID

from app.schemas.contracts import PaperRecord, ResearchPlan, ScreeningCard, SelectionResult


def select_top_k(
    cards: list[ScreeningCard],
    plan: ResearchPlan,
    papers: list[PaperRecord],
    limit: int,
    manual_ids: list[UUID] | None = None,
    fixed_order: bool = False,
) -> SelectionResult:
    selected = list(dict.fromkeys(manual_ids or []))
    if fixed_order:
        eligible = [paper.paper_id for paper in papers]
    else:
        eligible = [
            card.paper_id
            for card in sorted(cards, key=lambda c: (-(c.relevance or 0), str(c.paper_id)))
            if card.relevance is not None and card.relevance >= 3 and card.decision != "exclude"
        ]
    selected.extend(identifier for identifier in eligible if identifier not in selected)
    selected = selected[:limit]
    covered = {q for card in cards if card.paper_id in selected for q in card.matched_question_ids}
    return SelectionResult(
        selected_ids=selected,
        reasons_by_paper={
            str(identifier): "fixed_order" if fixed_order else "relevance_only"
            for identifier in selected
        },
        covered_question_ids=sorted(covered),
        uncovered_question_ids=[
            q.question_id for q in plan.questions if q.question_id not in covered
        ],
        deferred_ids=[paper.paper_id for paper in papers if paper.paper_id not in selected],
        selection_version="fixed-order-v1" if fixed_order else "topk-v1",
    )
