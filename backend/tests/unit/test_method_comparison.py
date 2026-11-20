from uuid import uuid4

from app.review.assemble import assemble_review
from app.review.models import MethodComparisonRow


def test_opposite_polarity_stays_two_rows_in_the_visible_comparison() -> None:
    paper_id = uuid4()
    rows = [
        MethodComparisonRow(
            paper_id=paper_id,
            column_id="c1",
            polarity="support",
            quote="原文支持句",
            evidence_id=uuid4(),
        ),
        MethodComparisonRow(
            paper_id=paper_id,
            column_id="c1",
            polarity="contradict",
            quote="原文反驳句",
            evidence_id=uuid4(),
        ),
    ]
    review = assemble_review("图神经网络", [], [], [], ["范围已冻结"], comparison=rows)
    visible = [row for row in review.comparison if row.column_id == "c1"]
    assert [(row.polarity, row.quote) for row in visible] == [
        ("support", "原文支持句"),
        ("contradict", "原文反驳句"),
    ]
    assert len(visible) == 2
