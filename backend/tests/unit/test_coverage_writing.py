from uuid import uuid4

from app.agents.review import coverage_writing_context
from app.schemas.contracts import ClaimRecord


def _claim(question_id: str, column_id: str, polarity: str, evidence_id, quote: str) -> ClaimRecord:
    return ClaimRecord(
        claim_id=uuid4(),
        paper_id=uuid4(),
        question_id=question_id,
        column_id=column_id,
        evidence_id=evidence_id,
        polarity=polarity,
        value_zh=quote,
    )


def test_coverage_writing_uses_bound_excerpts_and_splits_opposite_polarity() -> None:
    support_id = uuid4()
    contradict_id = uuid4()
    missing_id = uuid4()
    paper_id = uuid4()
    support = _claim("q1", "c1", "support", support_id, "支持结论")
    contradict = support.model_copy(
        update={
            "claim_id": uuid4(),
            "evidence_id": contradict_id,
            "polarity": "contradict",
            "value_zh": "反驳结论",
        }
    )
    contradict.paper_id = paper_id
    support.paper_id = paper_id
    absent = _claim("q1", "c1", "support", missing_id, "没有原文")
    context = coverage_writing_context(
        ["q1", "q2"],
        [support, contradict, absent],
        {support_id: "原文支持句", contradict_id: "原文反驳句"},
    )
    rows = [row for row in context.rows if row.column_id == "c1"]
    assert [row.polarity for row in rows] == ["support", "contradict"]
    assert [row.quote for row in rows] == ["原文支持句", "原文反驳句"]
    assert missing_id not in {row.evidence_id for row in context.rows}
    assert context.uncovered_notes == ["子问题 q2 未覆盖。"]
    rendered = context.model_dump_json()
    assert "整篇原文不应进入写作" not in rendered
    assert "model_history" not in rendered
