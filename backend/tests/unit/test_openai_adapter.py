import json

import httpx2
from pydantic import BaseModel

from app.config import Settings
from app.llm.base import Message
from app.llm.openai_compatible import OpenAICompatibleTransport


class Answer(BaseModel):
    answer: int


async def test_live_adapter_sends_selected_profile_and_preserves_reported_usage() -> None:
    settings = Settings(
        _env_file=None,
        llm_mode="live",
        llm_api_key="fixture-only-key",
        llm_base_url="https://provider.example/v1",
        llm_screen_model="screen-model",
        llm_research_model="research-model",
    )
    sent_requests: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        sent_requests.append(request)
        return httpx2.Response(
            200,
            json={
                "id": "chatcmpl-fixture",
                "object": "chat.completion",
                "created": 0,
                "model": "screen-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": '{"answer": 42}',
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
            },
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
        response = await OpenAICompatibleTransport(settings, client).generate(
            Answer,
            [Message("user", "question")],
            "screen",
            100,
        )
    assert response.payload == {"answer": 42}
    assert response.total_tokens == 14
    assert len(sent_requests) == 1
    request = json.loads(sent_requests[0].content)
    assert request["model"] == "screen-model"
    assert request["max_completion_tokens"] == 100
