from app.agents.context import AgentContext
from app.agents.prompts import prompt_messages
from app.llm.base import CallContext
from app.schemas.contracts import CoverageReport, PlanRequest, ResearchSpec, RoundPlan, SpecDraft


async def draft_research_spec(request: PlanRequest, context: AgentContext) -> SpecDraft:
    response = await context.model_gateway.generate(
        SpecDraft,
        prompt_messages(
            "coordinator_spec.j2",
            topic=request.topic,
            scope_json=request.scope.model_dump_json(),
        ),
        "research",
        CallContext(context.run_id, "planner:spec"),
    )
    return response.parsed


async def propose_round(
    spec: ResearchSpec,
    coverage: CoverageReport,
    round_index: int,
    context: AgentContext,
) -> RoundPlan:
    response = await context.model_gateway.generate(
        RoundPlan,
        prompt_messages(
            "planner_round.j2",
            fixture_key=f"round-{round_index}",
            round_index=round_index,
            spec_json=spec.model_dump_json(),
            coverage_json=coverage.model_dump_json(),
        ),
        "research",
        CallContext(context.run_id, f"planner:round:{round_index}"),
    )
    return response.parsed
