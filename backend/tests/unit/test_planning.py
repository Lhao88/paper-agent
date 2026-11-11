from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.context import AgentContext
from app.agents.coordinator import CoordinatorAgent
from app.agents.retrieval import RetrievalAgent
from app.config import Settings
from app.errors import DomainError
from app.llm.base import ModelResult
from app.llm.budget import BudgetService
from app.llm.gateway import ModelGateway
from app.schemas.contracts import (
    CoverageTarget,
    ExtractionColumn,
    InclusionRule,
    PlanDraft,
    PlanRequest,
    QueryPlan,
    Question,
    ResearchPlan,
    Scope,
    SpecDraft,
)


def context_with(result) -> AgentContext:
    gateway = AsyncMock(spec=ModelGateway)
    gateway.generate.return_value = ModelResult(result, None, 20)
    return AgentContext(
        uuid4(), None, gateway, AsyncMock(spec=BudgetService), Settings(_env_file=None)
    )


def draft() -> PlanDraft:
    return PlanDraft(
        topic="model topic",
        questions=[
            Question(
                question_id="model-id",
                text_zh=f"问题{i}",
                search_terms_en=["graph"],
                priority=2,
            )
            for i in range(3)
        ],
        scope=Scope(year_from=2000),
    )


async def test_planning_preserves_user_scope_and_assigns_unique_question_ids() -> None:
    request = PlanRequest(topic="用户主题", scope=Scope(year_from=2022, exclude_terms=["medical"]))
    result = await CoordinatorAgent().plan(request, context_with(draft()))
    assert result.topic == "用户主题"
    assert result.scope.year_from == 2022
    assert result.scope.exclude_terms == ["medical"]
    assert [q.question_id for q in result.questions] == ["q1", "q2", "q3"]


def _spec_draft() -> SpecDraft:
    questions = [
        Question(
            question_id=f"model-{index}",
            text_zh=f"问题{index}",
            search_terms_en=["graph"],
            priority=2,
        )
        for index in range(1, 4)
    ]
    return SpecDraft(
        topic="model topic",
        questions=questions,
        scope=Scope(year_from=2000),
        inclusion_rules=[InclusionRule(rule_id="model-rule", polarity="include", text_zh="纳入")],
        columns=[
            ExtractionColumn(
                column_id="model-column",
                question_id="model-1",
                field="method",
                required=True,
                description_zh="方法",
            )
        ],
        coverage=[CoverageTarget(question_id="model-1", required_column_ids=["model-column"])],
    )


async def test_draft_spec_uses_spec_prompt_and_plan_path_stays_legacy() -> None:
    request = PlanRequest(topic="用户主题", scope=Scope(year_from=2022, languages=["zh"]))
    context = context_with(_spec_draft())
    result = await CoordinatorAgent().draft_spec(request, context)
    assert result.topic == "用户主题"
    assert result.scope.year_from == 2022
    assert result.scope.languages == ["zh"]
    spec_call = context.model_gateway.generate.await_args
    assert spec_call.args[3].operation_key == "coordinator:spec"
    assert "用户主题" in spec_call.args[1][1].content
    legacy = context_with(draft())
    await CoordinatorAgent().plan(request, legacy)
    assert legacy.model_gateway.generate.await_args.args[3].operation_key == "coordinator:plan"


async def test_query_planning_rejects_unapproved_source_or_unknown_question() -> None:
    plan = ResearchPlan(**draft().model_dump(), plan_id=uuid4(), project_id=uuid4(), version=1)
    queries = QueryPlan.model_validate(
        {
            "queries": [
                {
                    "query_id": "query",
                    "question_ids": ["invented"],
                    "provider": "arxiv",
                    "terms": "graph",
                }
            ]
        }
    )
    with pytest.raises(DomainError) as exc:
        await RetrievalAgent().formulate_queries(plan, context_with(queries))
    assert exc.value.code == "QUERY_PLAN_INVALID"
