import hashlib
from uuid import UUID

from sqlalchemy import select

from app.agents.context import AgentContext
from app.agents.review import ReviewAgent
from app.db import Artifact, Run
from app.errors import DomainError
from app.repositories.artifacts import ArtifactRepository
from app.review.assemble import assemble_review
from app.review.models import ReviewBundle, ReviewDocument, ReviewSection
from app.review.repository import load_evidence_bundle
from app.review.validate import validate_review
from app.schemas.contracts import ResearchPlan


async def generate_review(
    artifact_ids: list[UUID], plan: ResearchPlan, context: AgentContext
) -> ReviewBundle:
    digest = hashlib.sha256(
        ("|".join(sorted(map(str, artifact_ids))) + plan.model_dump_json()).encode()
    ).hexdigest()
    key = f"review-bundle:{digest[:32]}"
    factory = context.require_repositories().factory
    async with factory() as session:
        existing = await session.scalar(
            select(Artifact).where(Artifact.run_id == context.run_id, Artifact.operation_key == key)
        )
        if existing:
            return ReviewBundle.model_validate(existing.payload_json)

    async def save(kind: str, payload: dict[str, object]) -> UUID:
        async with factory.begin() as session:
            saved = await ArtifactRepository(session).get_or_create(
                context.run_id, f"{key}:{kind}", kind, payload, digest
            )
            return saved.id

    bundle = await load_evidence_bundle(artifact_ids, context)
    agent = ReviewAgent()
    limits = [
        f"研究主题与范围按计划{plan.version}冻结。",
        "综述仅覆盖本次检索、预算内筛选及实际阅读材料；未检索到不代表领域不存在。",
        "定向全文阅读存在未读段落；仅摘要材料不用于实验数值比较。",
        "原文定位与引用存在性已由程序核对；模型自检不等同于人工语义验证。",
    ]
    limits.extend(sorted({warning for card in bundle.cards for warning in card.warnings}))
    async with factory() as session:
        run = await session.get(Run, context.run_id)
        if run is not None:
            warnings = run.progress_json.get("retrieval_warnings", [])
            if isinstance(warnings, list):
                limits.extend(f"检索覆盖警告：{warning}" for warning in warnings)
    synthesis_id = outline_id = None
    sections = []
    if bundle.evidence:
        synthesis = await agent.analyze(bundle, plan, context)
        synthesis_id = await save("synthesis", synthesis.model_dump(mode="json"))
        outline_id = await save(
            "outline",
            {"sections": [section.model_dump(mode="json") for section in synthesis.outline]},
        )
        for section in synthesis.outline:
            section_output = await agent.write_section(section, bundle, plan, context)
            sections.append(
                ReviewSection(**section_output.model_dump(), section_id=section.section_id)
            )
    else:
        sections.append(
            ReviewSection(
                section_id="insufficient",
                title="资料不足",
                blocks=[],
                unresolved_questions=[question.text_zh for question in plan.questions],
            )
        )
        limits.append("没有可用原文证据，未生成研究结论。")
    review = assemble_review(plan.topic, sections, bundle.evidence, bundle.references, limits)
    # Persist the usable draft before optional model checking, so a failed check loses no text.
    draft_id = await save("review_draft", review.model_dump(mode="json"))
    async with factory() as session:
        stored_draft = await session.get(Artifact, draft_id)
        if stored_draft is not None:
            review = ReviewDocument.model_validate(stored_draft.payload_json)
    report = validate_review(review)
    if bundle.evidence:
        try:
            check = await agent.self_check(review, plan, context)
            report = validate_review(review, check)
            if check.issues and context.settings.max_revision_rounds > 0:
                revised = []
                for original_section, section_plan in zip(sections, synthesis.outline, strict=True):
                    ids = {
                        block.block_id
                        for stored in review.sections
                        if stored.section_id == original_section.section_id
                        for block in stored.blocks
                    }
                    issues = [issue for issue in check.issues if issue.block_id in ids]
                    if issues:
                        output = await agent.write_section(
                            section_plan,
                            bundle,
                            plan,
                            context,
                            "\n".join(issue.suggestion for issue in issues),
                        )
                        revised.append(
                            ReviewSection(
                                **output.model_dump(), section_id=original_section.section_id
                            )
                        )
                    else:
                        revised.append(original_section)
                review = assemble_review(
                    plan.topic,
                    revised,
                    bundle.evidence,
                    bundle.references,
                    limits + ["已按一次模型自检建议修订，原问题仍需人工复核。"],
                )
                report = validate_review(review)
                report.issues = check.issues  # original block IDs deliberately retained for audit
                report.revision_round = 1
        except DomainError as exc:
            review.limitations.append(f"自检或有限修订未完成：{exc.code}，请人工检查已保存草稿。")
    review_id = await save("review", review.model_dump(mode="json"))
    validation_id = await save("validation", report.model_dump(mode="json"))
    result = ReviewBundle(
        synthesis_artifact_id=synthesis_id,
        outline_artifact_id=outline_id,
        review_artifact_id=review_id,
        validation_artifact_id=validation_id,
        review=review,
        validation=report,
    )
    async with factory.begin() as session:
        await ArtifactRepository(session).get_or_create(
            context.run_id, key, "review_bundle", result.model_dump(mode="json"), digest
        )
    return result
