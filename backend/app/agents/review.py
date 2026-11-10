import hashlib

from app.agents.context import AgentContext
from app.agents.prompts import json_text, prompt_messages
from app.errors import DomainError
from app.llm.base import CallContext
from app.review.models import (
    ComparisonRow,
    EvidenceBundle,
    QuestionAnalysis,
    ReviewDocument,
    SectionPlan,
    SelfCheckOutput,
    SynthesisArtifact,
    SynthesisOutput,
)
from app.review.validate import validate_synthesis
from app.schemas.contracts import ResearchPlan, SectionOutput


class ReviewAgent:
    async def analyze(
        self, bundle: EvidenceBundle, plan: ResearchPlan, context: AgentContext
    ) -> SynthesisArtifact:
        context.check_cancelled()
        payload = bundle.model_dump_json()
        if (
            len(payload.encode()) > context.settings.llm_max_input_bytes // 2
            and len(bundle.cards) > 1
        ):
            middle = len(bundle.cards) // 2
            batches = []
            for cards in (bundle.cards[:middle], bundle.cards[middle:]):
                papers = {card.paper_id for card in cards}
                batches.append(
                    await self.analyze(
                        EvidenceBundle(
                            cards=cards,
                            evidence=[item for item in bundle.evidence if item.paper_id in papers],
                            references=[
                                item for item in bundle.references if item.paper_id in papers
                            ],
                        ),
                        plan,
                        context,
                    )
                )
            questions = []
            for question in plan.questions:
                parts = [
                    item
                    for batch in batches
                    for item in batch.questions
                    if item.question_id == question.question_id
                ]
                questions.append(
                    QuestionAnalysis(
                        question_id=question.question_id,
                        findings="分批归纳，跨批关系仍需核验："
                        + "；".join(item.findings for item in parts),
                        evidence_ids=list(
                            dict.fromkeys(
                                identifier for item in parts for identifier in item.evidence_ids
                            )
                        ),
                        agreements=list(
                            dict.fromkeys(text for item in parts for text in item.agreements)
                        ),
                        disagreements=list(
                            dict.fromkeys(text for item in parts for text in item.disagreements)
                        ),
                        gaps=list(dict.fromkeys(text for item in parts for text in item.gaps)),
                    )
                )
            outline = []
            for section in batches[0].outline:
                identifiers = {
                    identifier
                    for batch in batches
                    for other in batch.outline
                    if other.title == section.title
                    for identifier in other.evidence_ids
                }
                identifiers.update(
                    identifier
                    for question in questions
                    if question.question_id in section.question_ids
                    for identifier in question.evidence_ids
                )
                outline.append(
                    section.model_copy(update={"evidence_ids": sorted(identifiers, key=str)})
                )
            return SynthesisArtifact(
                questions=questions,
                outline=outline,
                comparison=[row for batch in batches for row in batch.comparison],
                warnings=["资料已分批归纳，跨批共识、分歧及条件可比性仍需人工核验。"],
            )
        digest = hashlib.sha256((payload + plan.model_dump_json()).encode()).hexdigest()
        result = await context.model_gateway.generate(
            SynthesisOutput,
            prompt_messages(
                "review_analyze.j2",
                plan_json=plan.model_dump_json(),
                reading_cards_json=json_text(
                    [card.model_dump(mode="json") for card in bundle.cards]
                ),
                evidence_index_json=json_text(
                    [item.model_dump(mode="json") for item in bundle.evidence]
                ),
                fixture_bindings={
                    f"evidence_{i}": str(item.evidence_id) for i, item in enumerate(bundle.evidence)
                },
            ),
            "research",
            CallContext(context.run_id, f"analyze:{digest[:32]}"),
        )
        validate_synthesis(
            result.parsed,
            {q.question_id for q in plan.questions},
            {item.evidence_id for item in bundle.evidence},
        )
        outline = [
            section.model_copy(update={"section_id": f"s{i + 1}"})
            for i, section in enumerate(result.parsed.outline)
        ]
        return SynthesisArtifact(
            questions=result.parsed.questions,
            outline=outline,
            comparison=[
                ComparisonRow(
                    paper_id=card.paper_id,
                    reading_scope=card.reading_scope,
                    fields={
                        key: [fact.value_zh for fact in facts] for key, facts in card.fields.items()
                    },
                    evidence_ids=list(
                        dict.fromkeys(
                            identifier
                            for facts in card.fields.values()
                            for fact in facts
                            for identifier in fact.evidence_ids
                        )
                    ),
                )
                for card in bundle.cards
            ],
            warnings=["条件可比性与语义支持需人工核验"],
        )

    async def write_section(
        self,
        section: SectionPlan,
        bundle: EvidenceBundle,
        plan: ResearchPlan,
        context: AgentContext,
        revision: str = "",
    ) -> SectionOutput:
        context.check_cancelled()
        allowed = set(section.evidence_ids)
        evidence = [item for item in bundle.evidence if item.evidence_id in allowed]
        if (
            len(json_text([item.model_dump(mode="json") for item in evidence]).encode())
            > context.settings.llm_max_input_bytes // 2
            and len(evidence) > 1
        ):
            middle = len(evidence) // 2
            outputs = []
            for group in (evidence[:middle], evidence[middle:]):
                part = section.model_copy(
                    update={"evidence_ids": [item.evidence_id for item in group]}
                )
                outputs.append(await self.write_section(part, bundle, plan, context, revision))
            return SectionOutput(
                title=section.title,
                blocks=[block for output in outputs for block in output.blocks],
                unresolved_questions=list(
                    dict.fromkeys(
                        ["本节分批撰写，跨批综合仍需人工检查。"]
                        + [text for output in outputs for text in output.unresolved_questions]
                    )
                ),
            )
        digest = hashlib.sha256(
            (
                section.model_dump_json()
                + json_text([item.model_dump(mode="json") for item in evidence])
                + revision
            ).encode()
        ).hexdigest()
        result = await context.model_gateway.generate(
            SectionOutput,
            prompt_messages(
                "review_section.j2",
                scope_json=plan.scope.model_dump_json(),
                section_plan_json=section.model_dump_json() + "\n修订建议：" + revision,
                evidence_bundle_json=json_text([item.model_dump(mode="json") for item in evidence]),
                terminology_json="{}",
                fixture_bindings={
                    f"evidence_{i}": str(item.evidence_id) for i, item in enumerate(evidence)
                },
            ),
            "research",
            CallContext(context.run_id, f"write:{section.section_id}:{digest[:32]}"),
        )
        if any(not set(block.evidence_ids) <= allowed for block in result.parsed.blocks):
            raise DomainError("EVIDENCE_INVALID", "章节引用了未提供的证据。")
        return result.parsed.model_copy(update={"title": section.title})

    async def self_check(
        self, review: ReviewDocument, plan: ResearchPlan, context: AgentContext
    ) -> SelfCheckOutput:
        digest = hashlib.sha256(review.model_dump_json().encode()).hexdigest()
        result = await context.model_gateway.generate(
            SelfCheckOutput,
            prompt_messages(
                "review_self_check.j2",
                review_json=review.model_dump_json(),
                evidence_json=json_text([item.model_dump(mode="json") for item in review.evidence]),
                scope_json=plan.scope.model_dump_json(),
            ),
            "research",
            CallContext(context.run_id, f"self-check:{digest[:32]}"),
        )
        return result.parsed
