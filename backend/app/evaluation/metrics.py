from collections import defaultdict
from statistics import mean


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _count_ratio(
    usage: dict[str, object], numerator_key: str, denominator_key: str
) -> float | None:
    numerator, denominator = usage.get(numerator_key), usage.get(denominator_key)
    if isinstance(numerator, bool) or isinstance(denominator, bool):
        return None
    if not isinstance(numerator, int) or not isinstance(denominator, int):
        return None
    return ratio(numerator, denominator)


def calculate_metrics(
    gold: list[dict[str, object]],
    selected: list[str],
    preselected: list[str],
    screened: list[str],
    human: list[dict[str, str]],
    usage: dict[str, object],
) -> dict[str, object]:
    """Only deterministic accounting. Human support labels are never model-generated."""
    relevant = {
        str(row["paper_key"])
        for row in gold
        if isinstance(value := row.get("relevance"), int) and value >= 3
    }
    keys = {str(row["paper_key"]) for row in gold if row.get("key_paper") is True}
    selected_set, pre_set, screened_set = set(selected), set(preselected), set(screened)
    judged: dict[str, list[str]] = defaultdict(list)
    for row in human:
        if row.get("rater_id") and row.get("support") in {
            "supported",
            "partial",
            "unsupported",
            "unclear",
        }:
            judged[row["block_id"]].append(row["support"])
    fully_supported = sum(
        all(label == "supported" for label in labels) for labels in judged.values()
    )
    disagreements = sum(len(set(labels)) > 1 for labels in judged.values())
    citation_count = usage.get("citation_count", 0)
    existing = usage.get("existing_citations", 0)
    if not isinstance(citation_count, int) or not isinstance(existing, int):
        raise ValueError("citation counts must be integers")
    valid_questions = usage.get("question_ids", [])
    question_set = set(valid_questions) if isinstance(valid_questions, list) else set()
    supported_questions = {
        question
        for row in human
        if row.get("rater_id") and row.get("support") == "supported"
        for question in row.get("question_ids", "").split("|")
        if question
    }
    field_rows = [
        row
        for row in human
        if row.get("rater_id")
        and row.get("field_status") in {"supported", "unsupported", "omitted"}
    ]
    filled = [row for row in field_rows if row["field_status"] != "omitted"]
    quality: dict[str, float | None] = {}
    for dimension in ("coverage", "organization", "comparability", "accuracy", "limitations"):
        ratings = [
            int(row[dimension])
            for row in human
            if row.get("rater_id") and row.get(dimension) in {"1", "2", "3", "4", "5"}
        ]
        quality[dimension] = mean(ratings) if ratings else None
    return {
        **usage,
        "returned_count": len(selected_set),
        "gold_relevant_count": len(relevant),
        "precision_at_k": ratio(len(selected_set & relevant), len(selected_set)) if gold else None,
        "known_key_paper_coverage": ratio(len(selected_set & keys), len(keys)),
        "seed_paper_recall": ratio(len(pre_set & keys), len(keys)),
        "required_column_fill_rate": _count_ratio(
            usage, "filled_required_cells", "required_cells"
        ),
        "sentence_evidence_existence_rate": _count_ratio(
            usage, "sentences_with_existing_evidence", "sentence_count"
        ),
        "preselection_miss_rate": ratio(len(relevant - pre_set), len(relevant)),
        "deep_selection_miss_rate": ratio(
            len((screened_set & relevant) - selected_set), len(screened_set & relevant)
        ),
        "end_to_end_miss_rate": ratio(len(relevant - selected_set), len(relevant)),
        "citation_existence_rate": ratio(existing, citation_count),
        "citation_support_rate": ratio(fully_supported, len(judged)),
        "human_reviewed_blocks": len(judged),
        "rater_disagreements": disagreements,
        "question_evidence_coverage": ratio(
            len(supported_questions & question_set), len(question_set)
        )
        if any(row.get("rater_id") and row.get("question_ids") for row in human)
        else None,
        "extraction_correctness": ratio(
            sum(row["field_status"] == "supported" for row in filled), len(filled)
        ),
        "missing_field_rate": ratio(
            sum(row["field_status"] == "omitted" for row in field_rows), len(field_rows)
        ),
        "review_quality": quality,
        "human_metrics_note": "未导入对应人工标注的指标为null；引用存在率不代替支持率。",
    }
