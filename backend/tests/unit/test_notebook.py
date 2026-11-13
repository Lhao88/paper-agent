import inspect

from app.memory import notebook
from app.schemas.contracts import NotebookPage


def _record(pages: list[NotebookPage], *, executed: list[str], mode: str) -> list[NotebookPage]:
    return notebook.record_round(
        pages,
        round_index=1,
        executed_action_ids=executed,
        rejected_actions=[{"action_id": "stop-1", "reason": "unmet_coverage"}],
        unmet_question_ids=["q2"],
        embedding_mode=mode,
    )


def test_each_round_appends_one_page_with_actions_gaps_and_ranking() -> None:
    pages = _record([], executed=["search-1"], mode="off")
    assert len(pages) == 1
    page = pages[0]
    assert page.round_index == 1
    assert page.executed_action_ids == ["search-1"]
    assert page.rejected_actions == [{"action_id": "stop-1", "reason": "unmet_coverage"}]
    assert page.open_gaps == ["q2"]
    assert page.index_mode == "bm25"
    hybrid = _record([], executed=["search-1"], mode="mock")
    assert hybrid[0].index_mode == "hybrid"


def test_recording_the_same_round_does_not_add_a_page_or_source_request() -> None:
    pages = _record([], executed=["search-1"], mode="off")
    again = _record(pages, executed=["search-2"], mode="live")
    assert len(again) == 1
    assert again[0].executed_action_ids == ["search-1"]
    assert again[0].index_mode == "bm25"
    source = inspect.getsource(notebook)
    assert "reserve_source_request" not in source
    assert "search_works" not in source
