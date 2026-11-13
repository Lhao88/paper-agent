from collections.abc import Mapping, Sequence
from typing import Literal
from uuid import UUID

from app.schemas.contracts import NotebookPage

EmbeddingMode = Literal["off", "mock", "live"]
IndexMode = Literal["hybrid", "bm25"]


def index_mode_for(embedding_mode: EmbeddingMode) -> IndexMode:
    if embedding_mode == "off":
        return "bm25"
    return "hybrid"


def record_round(
    pages: Sequence[NotebookPage],
    *,
    round_index: int,
    executed_action_ids: Sequence[str],
    rejected_actions: Sequence[Mapping[str, str]],
    unmet_question_ids: Sequence[str],
    embedding_mode: EmbeddingMode,
    new_paper_ids: Sequence[UUID] = (),
    filled_column_ids: Sequence[str] = (),
    queries: Sequence[str] = (),
) -> list[NotebookPage]:
    """追加一页笔记。同一轮再次记录时原页保持不变，这里不发起来源请求。"""
    if any(page.round_index == round_index for page in pages):
        return list(pages)
    page = NotebookPage(
        round_index=round_index,
        executed_action_ids=list(executed_action_ids),
        rejected_actions=[dict(item) for item in rejected_actions],
        new_paper_ids=list(new_paper_ids),
        filled_column_ids=list(filled_column_ids),
        open_gaps=list(unmet_question_ids),
        queries=list(queries),
        index_mode=index_mode_for(embedding_mode),
    )
    return [*pages, page]
