import hashlib

from app.agents.context import AgentContext
from app.agents.prompts import json_text, prompt_messages
from app.errors import DomainError
from app.llm.base import CallContext
from app.schemas.contracts import (
    ChunkRecord,
    ExtractionOutput,
    PaperRecord,
    ResearchPlan,
    ScreeningCard,
    ScreenOutput,
)


class ReadingAgent:
    async def extract(
        self,
        paper: PaperRecord,
        chunks: list[ChunkRecord],
        plan: ResearchPlan,
        context: AgentContext,
    ) -> ExtractionOutput:
        context.check_cancelled()
        chunk_ids = {chunk.chunk_id for chunk in chunks}
        digest = hashlib.sha256(
            "|".join(str(chunk.chunk_id) for chunk in chunks).encode()
        ).hexdigest()
        response = await context.model_gateway.generate(
            ExtractionOutput,
            prompt_messages(
                "reading_extract.j2",
                fixture_key=next(
                    (s.provider_id for s in paper.sources if s.provider == "mock"), None
                ),
                fixture_bindings={
                    f"chunk_{i}": str(chunk.chunk_id) for i, chunk in enumerate(chunks)
                },
                questions_json=json_text([q.model_dump() for q in plan.questions]),
                paper_context_json=json_text(
                    {
                        "paper_id": str(paper.paper_id),
                        "title": paper.title,
                        "reading_scope": "full_text_targeted",
                    }
                ),
                chunks_json=json_text(
                    [{"chunk_id": str(chunk.chunk_id), "text": chunk.text} for chunk in chunks]
                ),
            ),
            "research",
            CallContext(context.run_id, f"extract:{paper.paper_id}:{digest[:32]}"),
        )
        if any(candidate.chunk_id not in chunk_ids for candidate in response.parsed.candidates):
            raise DomainError("EXTRACTION_INVALID", "模型引用了未提供的正文片段。")
        return response.parsed

    async def screen(
        self,
        paper: PaperRecord,
        plan: ResearchPlan,
        context: AgentContext,
    ) -> ScreeningCard:
        context.check_cancelled()
        if not paper.abstract or not paper.abstract.strip():
            return ScreeningCard(
                paper_id=paper.paper_id,
                summary_zh="没有可用原始摘要，暂不能判断研究内容。",
                matched_question_ids=[],
                relevance=None,
                decision="insufficient_info",
                reason="仅有元数据，不能据此判定不相关。",
                missing_information=["abstract"],
                material_basis="metadata_only",
            )
        result = await context.model_gateway.generate(
            ScreenOutput,
            prompt_messages(
                "reading_screen.j2",
                fixture_key=next(
                    (s.provider_id for s in paper.sources if s.provider == "mock"), None
                ),
                questions_json=json_text([question.model_dump() for question in plan.questions]),
                scope_json=plan.scope.model_dump_json(),
                title=paper.title,
                abstract=paper.abstract,
                metadata_json=json_text(
                    {
                        "year": paper.year,
                        "abstract_status": paper.abstract_status,
                        "source_key": paper.abstract_source_key,
                    }
                ),
            ),
            "screen",
            CallContext(
                context.run_id,
                f"screen:{plan.plan_id}:{paper.paper_id}:"
                + hashlib.sha256(
                    (paper.model_dump_json() + plan.model_dump_json()).encode()
                ).hexdigest()[:24],
            ),
        )
        card = result.parsed
        allowed = {question.question_id for question in plan.questions}
        invalid = (
            not set(card.matched_question_ids) <= allowed
            or not card.reason.strip()
            or not card.summary_zh.strip()
            or (card.decision == "exclude" and (card.relevance != 0 or card.matched_question_ids))
            or (card.relevance is None and card.decision != "insufficient_info")
            or (
                card.relevance is not None and card.relevance >= 3 and not card.matched_question_ids
            )
        )
        if invalid:
            raise DomainError("SCREENING_INVALID", "摘要判断与研究问题或筛选规则冲突。")
        return ScreeningCard(
            **card.model_dump(), paper_id=paper.paper_id, material_basis="abstract"
        )
