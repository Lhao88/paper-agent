from uuid import uuid4

from app.memory.coverage import compile_coverage
from app.schemas.contracts import (
    ClaimRecord,
    CoverageTarget,
    ExtractionColumn,
    InclusionRule,
    Question,
    ResearchSpec,
    Scope,
)


def spec(languages: list[str] | None = None, minimum: int = 3) -> ResearchSpec:
    return ResearchSpec(
        topic="图神经网络",
        questions=[
            Question(question_id=f"q{index}", text_zh=f"问题{index}", search_terms_en=["graph"])
            for index in range(1, 4)
        ],
        scope=Scope(languages=languages or ["en"]),
        inclusion_rules=[InclusionRule(rule_id="r1", polarity="include", text_zh="纳入实验论文")],
        columns=[
            ExtractionColumn(
                column_id="c1",
                question_id="q1",
                field="method",
                required=True,
                description_zh="方法",
            ),
            ExtractionColumn(
                column_id="c2",
                question_id="q2",
                field="limitation",
                required=True,
                description_zh="局限",
            ),
            ExtractionColumn(
                column_id="c3",
                question_id="q3",
                field="dataset",
                required=False,
                description_zh="数据",
            ),
        ],
        coverage=[
            CoverageTarget(
                question_id="q1", min_included_papers=minimum, required_column_ids=["c1"]
            ),
            CoverageTarget(
                question_id="q2", min_included_papers=minimum, required_column_ids=["c2"]
            ),
        ],
    )


def claim(paper_id, evidence_id, column_id: str = "c1", question_id: str = "q1") -> ClaimRecord:
    return ClaimRecord(
        claim_id=uuid4(),
        paper_id=paper_id,
        question_id=question_id,
        column_id=column_id,
        evidence_id=evidence_id,
        polarity="support",
        value_zh="方法说明",
    )


def test_empty_ledger_leaves_required_questions_unmet() -> None:
    report = compile_coverage(spec(), [], round_index=0, new_relevant_papers=0)
    assert report.unmet_question_ids == ["q1", "q2"]
    assert report.questions == [
        {"included_papers": 0, "filled_required_cells": 0},
        {"included_papers": 0, "filled_required_cells": 0},
        {"included_papers": 0, "filled_required_cells": 0},
    ]


def test_duplicate_claim_counts_as_one_paper() -> None:
    paper_id = uuid4()
    evidence_id = uuid4()
    report = compile_coverage(
        spec(minimum=1),
        [claim(paper_id, evidence_id), claim(paper_id, evidence_id)],
        round_index=1,
        new_relevant_papers=1,
    )
    method = next(cell for cell in report.cells if cell.column_id == "c1")
    assert method.filled_papers == 1
    assert report.questions[0]["included_papers"] == 1
    assert report.questions[0]["filled_required_cells"] == 1
    assert "q1" not in report.unmet_question_ids


def test_second_saturated_round_increments_consecutive_count() -> None:
    report = compile_coverage(
        spec(),
        [],
        round_index=2,
        new_relevant_papers=0,
        consecutive_saturated_rounds=1,
    )
    assert report.saturated is True
    assert report.consecutive_saturated_rounds == 2
    resumed = compile_coverage(
        spec(),
        [],
        round_index=3,
        new_relevant_papers=1,
        consecutive_saturated_rounds=2,
    )
    assert resumed.saturated is False
    assert resumed.consecutive_saturated_rounds == 0


def test_saturation_needs_no_new_relevant_papers_and_no_new_required_cells() -> None:
    paper_id = uuid4()
    evidence_id = uuid4()
    opened = compile_coverage(
        spec(minimum=1),
        [claim(paper_id, evidence_id)],
        round_index=1,
        new_relevant_papers=0,
        previously_filled_required_cells=set(),
    )
    assert opened.saturated is False
    settled = compile_coverage(
        spec(minimum=1),
        [claim(paper_id, evidence_id)],
        round_index=2,
        new_relevant_papers=0,
        previously_filled_required_cells={("q1", "c1")},
    )
    assert settled.saturated is True
    assert settled.new_relevant_papers_last_round == 0


def test_coverage_uses_only_the_ledger_and_does_not_take_a_model() -> None:
    import inspect

    parameters = inspect.signature(compile_coverage).parameters
    assert "model" not in parameters
    assert "gateway" not in parameters
    report = compile_coverage(spec(), [], round_index=0, new_relevant_papers=0)
    assert report.unmet_question_ids == ["q1", "q2"]


def test_chinese_scope_without_fulltext_is_disclosed() -> None:
    missing = compile_coverage(
        spec(languages=["zh"]),
        [],
        round_index=0,
        new_relevant_papers=0,
        chinese_fulltext_available=False,
    )
    available = compile_coverage(
        spec(languages=["zh", "en"]),
        [],
        round_index=0,
        new_relevant_papers=0,
        chinese_fulltext_available=True,
    )
    assert missing.corpus_limits == ["zh_fulltext_not_licensed"]
    assert available.corpus_limits == []
