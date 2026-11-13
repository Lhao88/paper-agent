import json
from collections.abc import Sequence

from app.agents.context import AgentContext
from app.agents.coordinator import CoordinatorAgent
from app.agents.prompts import prompt_messages
from app.llm.base import CallContext
from app.schemas.contracts import (
    CoverageReport,
    NotebookPage,
    PlanRequest,
    ResearchSpec,
    RoundPlan,
    SpecDraft,
)


async def draft_research_spec(request: PlanRequest, context: AgentContext) -> SpecDraft:
    return await CoordinatorAgent().draft_spec(request, context)


async def propose_round(
    spec: ResearchSpec,
    coverage: CoverageReport,
    round_index: int,
    context: AgentContext,
    notes: Sequence[NotebookPage] = (),
) -> RoundPlan:
    recent = list(notes)[-2:]
    notes_json = json.dumps(
        [page.model_dump(mode="json") for page in recent],
        ensure_ascii=False,
    )
    response = await context.model_gateway.generate(
        RoundPlan,
        prompt_messages(
            "planner_round.j2",
            fixture_key=f"round-{round_index}",
            round_index=round_index,
            spec_json=spec.model_dump_json(),
            coverage_json=coverage.model_dump_json(),
            notes_json=notes_json,
        ),
        "research",
        CallContext(context.run_id, f"planner:round:{round_index}"),
    )
    return RoundPlan(actions=list(response.parsed.actions)[:6])
