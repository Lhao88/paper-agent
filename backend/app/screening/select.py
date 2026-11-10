from uuid import UUID

from app.errors import DomainError
from app.schemas.contracts import PaperRecord, ResearchPlan, ScreeningCard, SelectionResult
from app.screening.text import tokenize


def select_deep_reads(
    cards: list[ScreeningCard],
    plan: ResearchPlan,
    papers: list[PaperRecord],
    limit: int,
    manual_ids: list[UUID] | None = None,
) -> SelectionResult:
    if limit < 1:
        raise ValueError("limit must be positive")
    by_paper = {paper.paper_id: paper for paper in papers}
    by_card = {card.paper_id: card for card in cards}
    question_ids = {question.question_id for question in plan.questions}
    if not by_card.keys() <= by_paper.keys() or any(
        not set(card.matched_question_ids) <= question_ids for card in cards
    ):
        raise DomainError("SCREENING_INVALID", "筛选卡片不属于当前候选论文或研究问题。")
    selected: list[UUID] = list(dict.fromkeys(manual_ids or []))
    if not set(selected) <= by_paper.keys():
        raise DomainError("PAPER_NOT_FOUND", "人工选择不属于当前项目候选。")
    if len(selected) > limit:
        raise DomainError("SELECTION_BUDGET_CONFLICT", "人工精读数量超过预算。")
    reasons = {str(identifier): "user_selected" for identifier in selected}
    details: dict[str, dict[str, float]] = {}
    candidates = {
        card.paper_id
        for card in cards
        if card.relevance is not None and card.relevance >= 3 and card.decision != "exclude"
    }
    tokens = {
        paper.paper_id: set(tokenize(f"{paper.title} {paper.abstract or ''}")) for paper in papers
    }

    def coverage() -> set[str]:
        return {
            question
            for identifier in selected
            if identifier in by_card
            for question in by_card[identifier].matched_question_ids
        }

    def components(identifier: UUID) -> dict[str, float]:
        card = by_card[identifier]
        new_coverage = len(set(card.matched_question_ids) - coverage()) / max(len(question_ids), 1)
        token_set = tokens[identifier]
        similarities = [
            len(token_set & tokens[other]) / len(token_set | tokens[other])
            for other in selected
            if token_set | tokens[other]
        ]
        novelty = 1 - max(similarities, default=0.0) if token_set else 0.0
        return {
            "relevance": (card.relevance or 0) / 4,
            "new_question_coverage": new_coverage,
            "novelty": novelty,
        }

    def score(identifier: UUID) -> float:
        values = components(identifier)
        return (
            0.65 * values["relevance"]
            + 0.25 * values["new_question_coverage"]
            + 0.10 * values["novelty"]
        )

    ordered_questions = sorted(plan.questions, key=lambda q: (q.priority, q.question_id))
    for target in (1, 2):
        for question in ordered_questions:
            if len(selected) >= limit:
                break
            if target == 2 and question.priority != 1:
                continue
            count = sum(
                question.question_id in by_card[identifier].matched_question_ids
                for identifier in selected
                if identifier in by_card
            )
            if count >= target:
                continue
            options = [
                identifier
                for identifier in candidates - set(selected)
                if question.question_id in by_card[identifier].matched_question_ids
            ]
            if options:
                chosen = min(options, key=lambda i: (-score(i), str(i)))
                details[str(chosen)] = {**components(chosen), "weighted_score": score(chosen)}
                selected.append(chosen)
                reasons[str(chosen)] = f"question_coverage:{question.question_id}"
    while len(selected) < limit and candidates - set(selected):
        chosen = min(candidates - set(selected), key=lambda i: (-score(i), str(i)))
        details[str(chosen)] = {**components(chosen), "weighted_score": score(chosen)}
        selected.append(chosen)
        reasons[str(chosen)] = "relevance_coverage_novelty"
    covered = coverage()
    deferred_reasons: dict[str, str] = {}
    for paper in papers:
        if paper.paper_id in selected:
            continue
        card = by_card.get(paper.paper_id)
        reason = "budget_or_redundancy"
        if card is None:
            reason = "not_screened_due_to_budget"
        elif card.relevance is None:
            reason = "insufficient_information"
        elif card.decision == "exclude":
            reason = "excluded_by_screening"
        elif card.relevance < 3:
            reason = "below_priority_threshold"
        deferred_reasons[str(paper.paper_id)] = reason
    return SelectionResult(
        selected_ids=selected,
        reasons_by_paper=reasons,
        covered_question_ids=sorted(covered),
        uncovered_question_ids=sorted(question_ids - covered),
        deferred_ids=[p.paper_id for p in papers if p.paper_id not in selected],
        deferred_reasons=deferred_reasons,
        score_details=details,
    )
