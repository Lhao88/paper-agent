import pytest

from app.config import Settings
from app.errors import DomainError
from app.planning.spec import allowed_sources_for, normalize_spec
from app.schemas.contracts import PlanRequest, Scope, SpecDraft


def settings(**updates: object) -> Settings:
    return Settings(_env_file=None, **updates)


def draft_with(**updates: object) -> SpecDraft:
    payload: dict[str, object] = {
        "topic": "模型主题",
        "questions": [
            {
                "question_id": f"model-q-{index}",
                "text_zh": f"问题{index}",
                "search_terms_en": ["graph"],
                "priority": 2,
            }
            for index in range(1, 4)
        ],
        "scope": {"year_from": 1990, "enabled_sources": ["openalex"]},
        "inclusion_rules": [
            {"rule_id": "model-rule", "polarity": "exclude", "text_zh": "排除综述"}
        ],
        "columns": [
            {
                "column_id": "model-c-1",
                "question_id": "model-q-1",
                "field": "method",
                "required": True,
                "description_zh": "方法",
            },
            {
                "column_id": "model-c-2",
                "question_id": "model-q-2",
                "field": "limitation",
                "required": False,
                "description_zh": "局限",
            },
        ],
        "coverage": [
            {
                "question_id": "model-q-1",
                "min_included_papers": 3,
                "required_column_ids": ["model-c-1"],
            }
        ],
        "assumptions": ["只看英文"],
    }
    payload.update(updates)
    return SpecDraft.model_validate(payload)


def test_default_planner_mode_is_legacy() -> None:
    assert settings().planner_mode == "legacy"


def test_allowlist_follows_source_switches() -> None:
    assert allowed_sources_for(settings()) == {"openalex"}
    assert allowed_sources_for(settings(enable_arxiv=True, enable_semantic_scholar=True)) == {
        "openalex",
        "arxiv",
        "semantic_scholar",
    }


def test_model_source_outside_allowlist_is_rejected() -> None:
    draft = draft_with(scope={"enabled_sources": ["cnki"]})
    request = PlanRequest(topic="用户主题", scope=Scope())
    with pytest.raises(DomainError) as exc:
        normalize_spec(draft, request, allowed_sources_for(settings()))
    assert exc.value.code == "SOURCE_NOT_ENABLED"


def test_column_for_unknown_question_is_rejected() -> None:
    draft = draft_with(
        columns=[
            {
                "column_id": "model-c-1",
                "question_id": "missing",
                "field": "method",
                "required": True,
                "description_zh": "方法",
            }
        ]
    )
    with pytest.raises(DomainError) as exc:
        normalize_spec(draft, PlanRequest(topic="用户主题"), {"openalex"})
    assert exc.value.code == "SPEC_INVALID"


def test_normalize_rewrites_ids_and_keeps_user_scope() -> None:
    request = PlanRequest(
        topic="用户主题",
        scope=Scope(year_from=2022, exclude_terms=["medical"]),
    )
    result = normalize_spec(draft_with(), request, {"openalex"})
    assert result.topic == "用户主题"
    assert result.scope.year_from == 2022
    assert result.scope.exclude_terms == ["medical"]
    assert [question.question_id for question in result.questions] == ["q1", "q2", "q3"]
    assert [column.column_id for column in result.columns] == ["c1", "c2"]
    assert result.columns[0].question_id == "q1"
    assert result.inclusion_rules[0].rule_id == "r1"
    assert result.coverage[0].question_id == "q1"
    assert result.coverage[0].required_column_ids == ["c1"]
