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
from app.schemas.contracts import PlanDraft, PlanRequest, QueryPlan, Question, ResearchPlan, Scope


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
