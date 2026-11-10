from app.agents.context import AgentContext
from app.agents.prompts import json_text, prompt_messages
from app.errors import DomainError
from app.llm.base import CallContext
from app.schemas.contracts import QueryPlan, ResearchPlan, RetrievalResult
from app.sources.base import PaperSource
from app.sources.retrieval_service import retrieve_papers


class RetrievalAgent:
    def __init__(self, sources: dict[str, PaperSource] | None = None) -> None:
        self.sources = sources or {}

    async def retrieve(self, query_plan: QueryPlan, context: AgentContext) -> RetrievalResult:
        return await retrieve_papers(query_plan, self.sources, context)

    async def formulate_queries(self, plan: ResearchPlan, context: AgentContext) -> QueryPlan:
        context.check_cancelled()
        response = await context.model_gateway.generate(
            QueryPlan,
            prompt_messages(
                "retrieval_queries.j2",
                plan_json=plan.model_dump_json(),
                source_syntax_json=json_text({"openalex": "plain terms", "arxiv": "English terms"}),
            ),
            "research",
            CallContext(context.run_id, "retrieval:queries"),
        )
        question_ids = {question.question_id for question in plan.questions}
        for query in response.parsed.queries:
            if (
                not set(query.question_ids) <= question_ids
                or query.provider not in plan.scope.enabled_sources
                or (query.provider == "arxiv" and not context.settings.enable_arxiv)
            ):
                raise DomainError("QUERY_PLAN_INVALID", "检索式引用了未知问题或未批准的来源。")
        return QueryPlan(
            scope=plan.scope,
            queries=[
                query.model_copy(
                    update={
                        "query_id": f"search-{index}",
                        "year_from": plan.scope.year_from,
                        "year_to": plan.scope.year_to,
                        "languages": plan.scope.languages,
                    }
                )
                for index, query in enumerate(response.parsed.queries, 1)
            ],
        )
