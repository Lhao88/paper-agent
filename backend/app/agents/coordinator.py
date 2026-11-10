from app.agents.context import AgentContext
from app.agents.prompts import json_text, prompt_messages
from app.errors import DomainError
from app.llm.base import CallContext
from app.planning.spec import allowed_sources_for
from app.schemas.contracts import PlanDraft, PlanRequest


class CoordinatorAgent:
    async def plan(self, request: PlanRequest, context: AgentContext) -> PlanDraft:
        context.check_cancelled()
        allowed = allowed_sources_for(context.settings)
        if not set(request.scope.enabled_sources) <= allowed:
            raise DomainError("SOURCE_NOT_ENABLED", "计划请求了未启用的数据来源。")
        response = await context.model_gateway.generate(
            PlanDraft,
            prompt_messages(
                "coordinator_plan.j2",
                topic=request.topic,
                scope_json=json_text(request.scope.model_dump()),
                source_capabilities_json=json_text(sorted(allowed)),
                budget_json=json_text(
                    {
                        "max_candidates": context.settings.max_candidates,
                        "max_deep_read_papers": context.settings.max_deep_read_papers,
                        "max_llm_calls": context.settings.max_llm_calls,
                    }
                ),
            ),
            "research",
            CallContext(context.run_id, "coordinator:plan"),
        )
        questions = [
            question.model_copy(update={"question_id": f"q{index}"})
            for index, question in enumerate(response.parsed.questions, 1)
        ]
        return response.parsed.model_copy(
            update={
                "topic": request.topic,
                "scope": request.scope,
                "questions": questions,
            }
        )
