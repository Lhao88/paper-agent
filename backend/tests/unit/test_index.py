from uuid import UUID, uuid4

from app.memory.index import mock_embedding, rank_chunks
from app.planning.admit import admit_actions
from app.schemas.contracts import ChunkRecord, ExtractionCandidate, ExtractionOutput
from app.screening.text import bm25_scores
from app.tools.search_in_paper import search_in_paper
from tests.unit.test_admit import action, coverage, paper, research_spec


def chunk(text: str, chunk_id: UUID | None = None) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk_id or uuid4(),
        document_id=uuid4(),
        page_number=1,
        text=text,
        text_sha256="a" * 64,
    )


def test_mock_embedding_is_stable() -> None:
    first = mock_embedding("同一段文字")
    second = mock_embedding("同一段文字")
    assert first == second
    assert len(first) == 256
    assert first != mock_embedding("另一段文字")


def test_off_mode_follows_bm25_order() -> None:
    chunks = [
        chunk("unrelated minerals and geology"),
        chunk("graph neural networks improve retrieval"),
        chunk("graph models"),
    ]
    ranked = rank_chunks(chunks, "graph neural", "off")
    scores = bm25_scores([item.text for item in chunks], ["graph", "neural"])
    expected = [
        item
        for _, item in sorted(
            zip(scores, chunks, strict=True),
            key=lambda pair: (-pair[0], str(pair[1].chunk_id)),
        )
    ]
    assert [item.chunk_id for item in ranked] == [item.chunk_id for item in expected]
    assert "graph" in ranked[0].text


def test_chinese_query_ranks_the_matching_chunk_first() -> None:
    matched = chunk("本段讨论图神经网络的结构。")
    other = chunk("本段只报告实验设置。")
    ranked = rank_chunks([other, matched], "图神经网络", "off")
    assert ranked[0].chunk_id == matched.chunk_id


def test_hand_built_vectors_rank_the_closer_chunk_first() -> None:
    lexical = chunk("alpha beta gamma")
    semantic = chunk("delta epsilon zeta")
    ranked = rank_chunks(
        [lexical, semantic],
        "unrelated query",
        "mock",
        vectors={
            lexical.chunk_id: [1.0, 0.0],
            semantic.chunk_id: [0.0, 1.0],
        },
        query_vector=[0.0, 1.0],
    )
    assert ranked[0].chunk_id == semantic.chunk_id


async def test_extraction_outside_returned_chunks_does_not_record() -> None:
    kept = chunk("graph neural networks")
    recorded: list[ExtractionCandidate] = []

    async def extract(chunks: list[ChunkRecord]) -> ExtractionOutput:
        assert [item.chunk_id for item in chunks] == [kept.chunk_id]
        return ExtractionOutput(
            candidates=[
                ExtractionCandidate(
                    field_name="method",
                    value_zh="方法",
                    chunk_id=uuid4(),
                    quote="graph",
                    statement_type="reported_fact",
                )
            ]
        )

    async def record(candidate: ExtractionCandidate) -> None:
        recorded.append(candidate)

    result = await search_in_paper(
        [kept, chunk("unrelated geology")],
        "graph",
        "off",
        limit=1,
        extract=extract,
        record=record,
    )
    assert recorded == []
    assert result.failure == "chunk_not_returned"


def test_fourth_search_in_paper_is_rejected() -> None:
    target = paper(search_in_paper_calls=3)
    result = admit_actions(
        research_spec(),
        [
            action(
                "search_in_paper",
                action_id="fourth",
                paper_ids=[target.paper_id],
                column_ids=["c1"],
                providers=[],
                query=None,
            )
        ],
        coverage(unmet_question_ids=[]),
        [target],
        remaining_source_requests=5,
        remaining_llm_calls=5,
        remaining_deep_reads=5,
    )
    assert result.actions == []
    assert result.rejected[0].reason == "search_call_cap"
