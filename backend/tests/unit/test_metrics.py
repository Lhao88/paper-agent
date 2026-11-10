from app.evaluation.metrics import calculate_metrics


def test_zero_denominators_are_null_and_failure_cost_is_not_dropped():
    result = calculate_metrics(
        [],
        [],
        [],
        [],
        [],
        {"status": "partial", "used_tokens": 12, "unknown_calls": 1, "reserved_tokens": 100},
    )
    assert result["precision_at_k"] is None
    assert result["citation_support_rate"] is None
    assert result["seed_paper_recall"] is None
    assert result["required_column_fill_rate"] is None
    assert result["sentence_evidence_existence_rate"] is None
    assert result["status"] == "partial"
    assert result["unknown_calls"] == 1 and result["reserved_tokens"] == 100


def test_existing_citations_do_not_imply_semantic_support():
    gold = [
        {"paper_key": "p1", "relevance": 4, "key_paper": True},
        {"paper_key": "p2", "relevance": 0, "key_paper": False},
    ]
    human = [
        {"block_id": "b1", "support": "unsupported", "rater_id": "human"},
        {"block_id": "b2", "support": "supported", "rater_id": "human"},
    ]
    result = calculate_metrics(
        gold,
        ["p1", "p2"],
        ["p1"],
        ["p1", "p2"],
        human,
        {"status": "completed", "citation_count": 2, "existing_citations": 2},
    )
    assert result["precision_at_k"] == 0.5
    assert result["citation_existence_rate"] == 1
    assert result["citation_support_rate"] == 0.5
    assert result["known_key_paper_coverage"] == 1


def test_human_fields_question_support_and_blind_ratings_are_separate():
    human = [
        {
            "block_id": "b1",
            "support": "supported",
            "rater_id": "r1",
            "question_ids": "q1",
            "field_status": "supported",
            "accuracy": "4",
        },
        {
            "block_id": "b2",
            "support": "unsupported",
            "rater_id": "r1",
            "question_ids": "q2",
            "field_status": "omitted",
        },
    ]
    result = calculate_metrics([], [], [], [], human, {"question_ids": ["q1", "q2"]})
    assert result["question_evidence_coverage"] == 0.5
    assert result["extraction_correctness"] == 1
    assert result["missing_field_rate"] == 0.5
    assert result["review_quality"]["accuracy"] == 4


def test_seed_recall_column_fill_and_sentence_evidence_stay_separate_from_support():
    gold = [
        {"paper_key": "p1", "relevance": 4, "key_paper": True},
        {"paper_key": "p2", "relevance": 4, "key_paper": True},
    ]
    result = calculate_metrics(
        gold,
        ["p1"],
        ["p1", "p2"],
        ["p1"],
        [],
        {
            "required_cells": 2,
            "filled_required_cells": 1,
            "sentence_count": 2,
            "sentences_with_existing_evidence": 1,
        },
    )
    assert result["seed_paper_recall"] == 1
    assert result["known_key_paper_coverage"] == 0.5
    assert result["required_column_fill_rate"] == 0.5
    assert result["sentence_evidence_existence_rate"] == 0.5
    assert result["citation_support_rate"] is None
