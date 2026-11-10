from uuid import UUID

from app.errors import DomainError
from app.schemas.contracts import PaperRecord, PreselectionResult, Question
from app.screening.text import bm25_scores


def preselect(
    papers: list[PaperRecord],
    questions: list[Question],
    limit: int,
    manual_ids: list[UUID] | None = None,
) -> PreselectionResult:
    if limit < 1:
        raise ValueError("limit must be positive")
    by_id = {paper.paper_id: paper for paper in papers}
    selected = list(dict.fromkeys(manual_ids or []))
    if not set(selected) <= by_id.keys():
        raise DomainError("PAPER_NOT_FOUND", "人工选择含有不属于候选集的论文。")
    if len(selected) > limit:
        raise DomainError("SELECTION_BUDGET_CONFLICT", "人工选择数量超过筛选预算。")
    materials = [f"{paper.title}\n{paper.abstract or ''}" for paper in papers]
    scores = [bm25_scores(materials, question.search_terms_en) for question in questions]
    rankings = [
        sorted(range(len(papers)), key=lambda index: (-ranking[index], str(papers[index].paper_id)))
        for ranking in scores
    ]
    missing = [paper.paper_id for paper in papers if not paper.abstract]
    reserve = min(5, len(missing), limit // 5)
    normal_limit = max(len(selected), limit - reserve)
    selected_set = set(selected)
    while len(selected) < normal_limit:
        changed = False
        for ranking in rankings:
            candidate = next(
                (
                    papers[index].paper_id
                    for index in ranking
                    if papers[index].paper_id not in selected_set and papers[index].abstract
                ),
                None,
            )
            if candidate is not None:
                selected.append(candidate)
                selected_set.add(candidate)
                changed = True
            if len(selected) >= normal_limit:
                break
        if not changed:
            break
    for identifier in sorted(missing, key=str):
        if len(selected) >= limit:
            break
        if identifier not in selected_set:
            selected.append(identifier)
            selected_set.add(identifier)
    best = [
        max((ranking[index] for ranking in scores), default=0.0) for index in range(len(papers))
    ]
    for index in sorted(range(len(papers)), key=lambda i: (-best[i], str(papers[i].paper_id))):
        if len(selected) >= limit:
            break
        if papers[index].paper_id not in selected_set:
            selected.append(papers[index].paper_id)
            selected_set.add(papers[index].paper_id)
    return PreselectionResult(
        selected_ids=selected,
        deferred_ids=[p.paper_id for p in papers if p.paper_id not in selected_set],
        missing_abstract_ids=[p for p in selected if p in missing],
        limit=limit,
        ranking_details={
            str(paper.paper_id): {
                question.question_id: scores[q_index][p_index]
                for q_index, question in enumerate(questions)
            }
            for p_index, paper in enumerate(papers)
        },
    )
