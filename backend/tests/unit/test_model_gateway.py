from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.config import Settings
from app.errors import DomainError
from app.llm.base import CallContext, Message, RawModelResponse
from app.llm.budget import BudgetService, Reservation
from app.llm.gateway import ModelGateway


class Answer(BaseModel):
    answer: int


class ScriptedTransport:
    def __init__(self, responses: list[RawModelResponse | Exception]) -> None:
        self.responses = iter(responses)
        self.requests = 0

    async def generate(self, schema, messages, profile, max_output_tokens):
        self.requests += 1
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def make_budget() -> BudgetService:
    budget = AsyncMock(spec=BudgetService)
    budget.reserve_call.side_effect = [Reservation(uuid4(), index, 100) for index in (1, 2)]
    return cast(BudgetService, budget)


async def test_schema_repair_is_bounded_and_returns_validated_typed_output() -> None:
    transport = ScriptedTransport(
        [
            RawModelResponse({"answer": "not-an-integer"}, 10, 5),
            RawModelResponse({"answer": 42}, 12, 7),
        ]
    )
    gateway = ModelGateway(make_budget(), transport, Settings(_env_file=None))
    result = await gateway.generate(
        Answer, [Message("user", "question")], "screen", CallContext(uuid4(), "screen-paper")
    )
    assert result.parsed.answer == 42
    assert result.total_tokens == 19
    assert transport.requests == 2


async def test_invalid_output_does_not_become_a_default_answer_after_retry_limit() -> None:
    transport = ScriptedTransport([RawModelResponse({}, 1, 1), RawModelResponse({}, 1, 1)])
    gateway = ModelGateway(make_budget(), transport, Settings(_env_file=None))
    with pytest.raises(DomainError) as exc:
        await gateway.generate(Answer, [], "screen", CallContext(uuid4(), "op"))
    assert exc.value.code == "MODEL_SCHEMA_INVALID"
    assert transport.requests == 2


async def test_timeout_does_not_automatically_repeat_a_possibly_charged_request() -> None:
    transport = ScriptedTransport([TimeoutError("response lost")])
    gateway = ModelGateway(make_budget(), transport, Settings(_env_file=None))
    with pytest.raises(DomainError) as exc:
        await gateway.generate(Answer, [], "screen", CallContext(uuid4(), "op"))
    assert exc.value.code == "MODEL_TIMEOUT_UNKNOWN"
    assert transport.requests == 1


async def test_budget_rejection_prevents_provider_request() -> None:
    budget = AsyncMock(spec=BudgetService)
    budget.reserve_call.side_effect = DomainError("BUDGET_EXHAUSTED", "no allowance")
    transport = ScriptedTransport([])
    gateway = ModelGateway(budget, transport, Settings(_env_file=None))
    with pytest.raises(DomainError):
        await gateway.generate(Answer, [], "screen", CallContext(uuid4(), "op"))
    assert transport.requests == 0


async def test_cached_result_is_reused_without_contacting_provider() -> None:
    budget = AsyncMock(spec=BudgetService)
    budget.reserve_call.return_value = Reservation(uuid4(), 1, 100, {"answer": 9}, 12)
    transport = ScriptedTransport([])
    gateway = ModelGateway(budget, transport, Settings(_env_file=None))
    result = await gateway.generate(Answer, [], "screen", CallContext(uuid4(), "op"))
    assert result.parsed.answer == 9
    assert result.cached is True
    assert transport.requests == 0


async def test_refusal_is_visible_and_is_not_retried_as_json_repair() -> None:
    transport = ScriptedTransport([RawModelResponse({}, 2, 1, refused=True)])
    gateway = ModelGateway(make_budget(), transport, Settings(_env_file=None))
    with pytest.raises(DomainError) as exc:
        await gateway.generate(Answer, [], "research", CallContext(uuid4(), "op"))
    assert exc.value.code == "MODEL_REFUSED"
    assert transport.requests == 1


async def test_oversized_input_is_rejected_before_budget_or_provider():
    budget = make_budget()
    transport = ScriptedTransport([])
    gateway = ModelGateway(budget, transport, Settings(_env_file=None))
    with pytest.raises(DomainError) as exc:
        await gateway.generate(
            Answer, [Message("user", "x" * 150000)], "research", CallContext(uuid4(), "large")
        )
    assert exc.value.code == "MODEL_CONTEXT_LIMIT"
    assert transport.requests == 0
    budget.reserve_call.assert_not_called()
