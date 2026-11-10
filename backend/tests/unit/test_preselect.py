import pytest

from app.errors import DomainError
from app.schemas.contracts import PaperRecord, Question
from app.screening.preselect import preselect


def test_preselection_limits_calls_and_preserves_question_coverage() -> None:
    dominant = [
        PaperRecord(title=f"graph retrieval {i}", abstract="graph retrieval", sources=[])
        for i in range(20)
    ]
    minority = PaperRecord(
        title="citation support", abstract="citation evidence support", sources=[]
    )
    questions = [
        Question(question_id=key, text_zh=key, search_terms_en=terms)
        for key, terms in (("q1", ["graph", "retrieval"]), ("q2", ["citation", "support"]))
    ]
    result = preselect([*dominant, minority], questions, limit=3)
    assert len(result.selected_ids) == 3
    assert minority.paper_id in result.selected_ids
    assert len(result.deferred_ids) == 18


def test_missing_abstract_remains_metadata_candidate_instead_of_irrelevant() -> None:
    paper = PaperRecord(title="graph retrieval", abstract=None, sources=[])
    result = preselect(
        [paper], [Question(question_id="q1", text_zh="问题", search_terms_en=["graph"])], limit=5
    )
    assert paper.paper_id in result.selected_ids
    assert result.missing_abstract_ids == [paper.paper_id]


def test_manual_selection_conflict_is_reported_without_silently_increasing_budget() -> None:
    papers = [PaperRecord(title=str(i), sources=[]) for i in range(2)]
    with pytest.raises(DomainError) as exc:
        preselect(papers, [], limit=1, manual_ids=[p.paper_id for p in papers])
    assert exc.value.code == "SELECTION_BUDGET_CONFLICT"
