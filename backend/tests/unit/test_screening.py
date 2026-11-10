from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.context import AgentContext
from app.agents.reading import ReadingAgent
from app.config import Settings
from app.errors import DomainError
from app.llm.base import ModelResult
from app.llm.budget import BudgetService
from app.llm.gateway import ModelGateway
from app.schemas.contracts import PaperRecord, Question, ResearchPlan, Scope, ScreenOutput


def plan() -> ResearchPlan:
    return ResearchPlan(
        topic="topic",
        questions=[
            Question(
                question_id=f"q{i}",
                text_zh=str(i),
                search_terms_en=["graph"],
            )
            for i in range(1, 4)
        ],
        scope=Scope(),
        plan_id=uuid4(),
        project_id=uuid4(),
        version=1,
    )


async def test_missing_abstract_uses_no_model_and_is_not_marked_irrelevant() -> None:
    gateway = AsyncMock(spec=ModelGateway)
    gateway.generate.side_effect = AssertionError("missing abstract must not call a model")
    context = AgentContext(
        uuid4(), None, gateway, AsyncMock(spec=BudgetService), Settings(_env_file=None)
    )
    result = await ReadingAgent().screen(PaperRecord(title="graph", sources=[]), plan(), context)
    assert result.relevance is None
    assert result.decision == "insufficient_info"
    assert result.material_basis == "metadata_only"


async def test_unknown_question_ids_are_rejected_instead_of_entering_selection() -> None:
    gateway = AsyncMock(spec=ModelGateway)
    gateway.generate.return_value = ModelResult(
        ScreenOutput(
            summary_zh="概括",
            matched_question_ids=["invented"],
            relevance=4,
            decision="priority",
            reason="reason",
            missing_information=[],
        ),
        None,
        10,
    )
    context = AgentContext(
        uuid4(), None, gateway, AsyncMock(spec=BudgetService), Settings(_env_file=None)
    )
    with pytest.raises(DomainError) as exc:
        await ReadingAgent().screen(
            PaperRecord(title="graph", abstract="original", sources=[]), plan(), context
        )
    assert exc.value.code == "SCREENING_INVALID"
