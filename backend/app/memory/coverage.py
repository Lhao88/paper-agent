from uuid import UUID

from app.schemas.contracts import ClaimRecord, CoverageCell, CoverageReport, ResearchSpec


def compile_coverage(
    spec: ResearchSpec,
    claims: list[ClaimRecord],
    *,
    round_index: int,
    new_relevant_papers: int,
    previously_filled_required_cells: set[tuple[str, str]] | None = None,
    consecutive_saturated_rounds: int = 0,
    chinese_fulltext_available: bool = False,
    remaining_source_requests: int = 0,
    remaining_llm_calls: int = 0,
    remaining_deep_reads: int = 0,
) -> CoverageReport:
    previous = previously_filled_required_cells or set()
    required_by_question = {
        target.question_id: (target.min_included_papers, set(target.required_column_ids))
        for target in spec.coverage
    }
    papers_by_cell: dict[tuple[str, str], set[UUID]] = {}
    papers_by_question: dict[str, set[UUID]] = {
        question.question_id: set() for question in spec.questions
    }
    for item in claims:
        papers_by_cell.setdefault((item.question_id, item.column_id), set()).add(item.paper_id)
        if item.question_id in papers_by_question:
            papers_by_question[item.question_id].add(item.paper_id)
    cells: list[CoverageCell] = []
    filled_required: set[tuple[str, str]] = set()
    for column in spec.columns:
        key = (column.question_id, column.column_id)
        target = required_by_question.get(column.question_id)
        required = column.required or (target is not None and column.column_id in target[1])
        filled = len(papers_by_cell.get(key, set()))
        if required and filled > 0:
            filled_required.add(key)
        cells.append(
            CoverageCell(
                question_id=column.question_id,
                column_id=column.column_id,
                filled_papers=filled,
                required=required,
            )
        )
    questions: list[dict[str, int]] = []
    unmet: list[str] = []
    for question in spec.questions:
        target = required_by_question.get(question.question_id)
        required_ids = target[1] if target else set()
        filled_cells = sum(
            1 for column_id in required_ids if papers_by_cell.get((question.question_id, column_id))
        )
        questions.append(
            {
                "included_papers": len(papers_by_question[question.question_id]),
                "filled_required_cells": filled_cells,
            }
        )
        if target and any(
            len(papers_by_cell.get((question.question_id, column_id), set())) < target[0]
            for column_id in required_ids
        ):
            unmet.append(question.question_id)
    saturated = new_relevant_papers == 0 and not (filled_required - previous)
    limits = (
        ["zh_fulltext_not_licensed"]
        if "zh" in spec.scope.languages and not chinese_fulltext_available
        else []
    )
    return CoverageReport(
        round_index=round_index,
        questions=questions,
        cells=cells,
        unmet_question_ids=unmet,
        remaining_source_requests=remaining_source_requests,
        remaining_llm_calls=remaining_llm_calls,
        remaining_deep_reads=remaining_deep_reads,
        new_relevant_papers_last_round=new_relevant_papers,
        consecutive_saturated_rounds=consecutive_saturated_rounds + 1 if saturated else 0,
        corpus_limits=limits,
        saturated=saturated,
    )
