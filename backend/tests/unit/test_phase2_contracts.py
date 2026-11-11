import pytest
from pydantic import ValidationError

from app.schemas.contracts import (
    ClaimRecord,
    CoverageTarget,
    ExtractionColumn,
    FollowupDecision,
    InclusionRule,
    PlanDraft,
    ResearchSpec,
    RoundAction,
    RoundPlan,
)


def _question(index: int) -> dict[str, object]:
    return {
        "question_id": f"q{index}",
        "text_zh": f"问题{index}",
        "search_terms_en": ["graph"],
        "priority": 2,
    }


def _column(index: int) -> dict[str, object]:
    return {
        "column_id": f"c{index}",
        "question_id": "q1",
        "field": "method",
        "required": True,
        "description_zh": "方法",
    }


def _rule() -> dict[str, str]:
    return {"rule_id": "r1", "polarity": "include", "text_zh": "纳入实验论文"}


def _spec(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "topic": "图神经网络",
        "questions": [_question(index) for index in range(1, 4)],
        "scope": {"enabled_sources": ["openalex"]},
        "inclusion_rules": [_rule()],
        "columns": [_column(1)],
        "coverage": [{"question_id": "q1", "required_column_ids": ["c1"]}],
    }
    payload.update(updates)
    return payload


def test_legacy_plan_and_followup_types_remain_importable() -> None:
    assert PlanDraft.__name__ == "PlanDraft"
    assert FollowupDecision.__name__ == "FollowupDecision"


def test_research_spec_rejects_unknown_fields_and_out_of_range_counts() -> None:
    with pytest.raises(ValidationError):
        ResearchSpec.model_validate({**_spec(), "extra_note": "nope"})
    with pytest.raises(ValidationError):
        ResearchSpec.model_validate(_spec(questions=[_question(1), _question(2)]))
    with pytest.raises(ValidationError):
        ResearchSpec.model_validate(_spec(questions=[_question(index) for index in range(1, 7)]))
    with pytest.raises(ValidationError):
        ResearchSpec.model_validate(_spec(inclusion_rules=[]))
    with pytest.raises(ValidationError):
        ResearchSpec.model_validate(_spec(inclusion_rules=[_rule() for _ in range(13)]))
    with pytest.raises(ValidationError):
        ResearchSpec.model_validate(_spec(columns=[]))
    with pytest.raises(ValidationError):
        ResearchSpec.model_validate(_spec(columns=[_column(index) for index in range(1, 14)]))


def test_column_field_and_text_lengths_are_closed() -> None:
    with pytest.raises(ValidationError):
        ExtractionColumn.model_validate({**_column(1), "field": "abstract"})
    with pytest.raises(ValidationError):
        ExtractionColumn.model_validate({**_column(1), "description_zh": ""})
    with pytest.raises(ValidationError):
        ExtractionColumn.model_validate({**_column(1), "description_zh": "字" * 301})
    with pytest.raises(ValidationError):
        InclusionRule.model_validate({**_rule(), "text_zh": ""})
    with pytest.raises(ValidationError):
        InclusionRule.model_validate({**_rule(), "text_zh": "字" * 301})
    with pytest.raises(ValidationError):
        InclusionRule.model_validate({**_rule(), "polarity": "maybe"})


def test_coverage_target_defaults_to_three_and_rejects_out_of_range() -> None:
    target = CoverageTarget.model_validate({"question_id": "q1", "required_column_ids": ["c1"]})
    assert target.min_included_papers == 3
    with pytest.raises(ValidationError):
        CoverageTarget.model_validate(
            {"question_id": "q1", "min_included_papers": 0, "required_column_ids": ["c1"]}
        )
    with pytest.raises(ValidationError):
        CoverageTarget.model_validate(
            {"question_id": "q1", "min_included_papers": 16, "required_column_ids": ["c1"]}
        )


def _action(index: int) -> dict[str, object]:
    return {
        "action_id": f"a{index}",
        "kind": "search_works",
        "question_ids": ["q1"],
        "rationale": "补缺口",
        "query": "limitation",
    }


def test_round_plan_allows_only_registered_actions_up_to_six() -> None:
    with pytest.raises(ValidationError):
        RoundAction.model_validate({**_action(1), "kind": "browse_web"})
    with pytest.raises(ValidationError):
        RoundPlan.model_validate({"actions": []})
    with pytest.raises(ValidationError):
        RoundPlan.model_validate({"actions": [_action(index) for index in range(1, 8)]})
    plan = RoundPlan.model_validate({"actions": [_action(index) for index in range(1, 7)]})
    assert len(plan.actions) == 6


def test_claim_polarity_is_only_support_or_contradict() -> None:
    payload = {
        "claim_id": "00000000-0000-4000-8000-000000000001",
        "paper_id": "00000000-0000-4000-8000-000000000002",
        "question_id": "q1",
        "column_id": "c1",
        "evidence_id": "00000000-0000-4000-8000-000000000003",
        "polarity": "support",
        "value_zh": "支持",
    }
    assert ClaimRecord.model_validate(payload).polarity == "support"
    with pytest.raises(ValidationError):
        ClaimRecord.model_validate({**payload, "polarity": "neutral"})
    with pytest.raises(ValidationError):
        ClaimRecord.model_validate({**payload, "extra": True})
