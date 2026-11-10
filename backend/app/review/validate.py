from uuid import UUID

from app.errors import DomainError
from app.review.models import ReviewDocument, SelfCheckOutput, SynthesisOutput, ValidationReport


def validate_synthesis(output: SynthesisOutput, questions: set[str], evidence: set[UUID]) -> None:
    for item in output.questions:
        if item.question_id not in questions or not set(item.evidence_ids) <= evidence:
            raise DomainError("SYNTHESIS_INVALID", "综合分析含未知问题或证据。")
        if item.findings.strip() and not item.evidence_ids and not item.gaps:
            raise DomainError("SYNTHESIS_INVALID", "没有依据的结论必须明确资料缺口。")
    for section in output.outline:
        if not set(section.question_ids) <= questions or not set(section.evidence_ids) <= evidence:
            raise DomainError("SYNTHESIS_INVALID", "章节含未知问题或证据。")


def validate_review(
    review: ReviewDocument, check: SelfCheckOutput | None = None
) -> ValidationReport:
    evidence_ids = {item.evidence_id for item in review.evidence}
    refs = {ref.paper_id: ref.number for ref in review.references}
    blocks = [block for section in review.sections for block in section.blocks]
    for block in blocks:
        if not set(block.evidence_ids) <= evidence_ids:
            raise DomainError("EVIDENCE_INVALID", "综述引用含未知证据。")
        if block.kind in {"literature_claim", "synthesis"} and not block.evidence_ids:
            raise DomainError("CITATION_REQUIRED", "实质性结论缺少证据。")
        expected = list(
            dict.fromkeys(
                refs[item.paper_id]
                for item in review.evidence
                if item.evidence_id in block.evidence_ids
            )
        )
        if set(expected) != set(block.citation_numbers):
            raise DomainError("REFERENCE_INVALID", "文献编号与证据映射不一致。")
    issues = [] if check is None else check.issues
    block_ids = {block.block_id for block in blocks}
    if any(
        issue.block_id not in block_ids or not set(issue.evidence_ids) <= evidence_ids
        for issue in issues
    ):
        raise DomainError("SELF_CHECK_INVALID", "自检引用了未知段落或证据。")
    return ValidationReport(
        structural_valid=True,
        pending_block_ids=[block.block_id for block in blocks if block.kind != "transition"],
        issues=issues,
    )
