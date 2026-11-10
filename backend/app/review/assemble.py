from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from app.errors import DomainError
from app.review.models import Reference, ReviewDocument, ReviewSection, StoredClaim, StoredSection
from app.schemas.contracts import EvidenceRecord


def assemble_review(
    topic: str,
    sections: list[ReviewSection],
    evidence: list[EvidenceRecord],
    references: list[Reference],
    limitations: list[str],
) -> ReviewDocument:
    by_id = {item.evidence_id: item for item in evidence}
    refs = {item.paper_id: item for item in references}
    numbers: dict[UUID, int] = {}
    stored = []
    for section in sections:
        blocks = []
        for index, block in enumerate(section.blocks):
            if block.kind in {"literature_claim", "synthesis"} and not block.evidence_ids:
                raise DomainError("CITATION_REQUIRED", "文献事实或综合判断必须提供原文证据。")
            citations = []
            for identifier in block.evidence_ids:
                item = by_id.get(identifier)
                if item is None or item.paper_id not in refs:
                    raise DomainError("EVIDENCE_INVALID", "引用不属于本次允许的文献证据。")
                number = numbers.setdefault(item.paper_id, len(numbers) + 1)
                if number not in citations:
                    citations.append(number)
            blocks.append(
                StoredClaim(
                    **block.model_dump(),
                    block_id=uuid5(
                        NAMESPACE_URL, f"{section.section_id}:{index}:{block.model_dump_json()}"
                    ),
                    citation_numbers=citations,
                )
            )
        stored.append(
            StoredSection(
                section_id=section.section_id,
                title=section.title,
                blocks=blocks,
                unresolved_questions=section.unresolved_questions,
            )
        )
    return ReviewDocument(
        topic=topic,
        generated_at=datetime.now(UTC),
        sections=stored,
        evidence=evidence,
        references=[
            refs[key].model_copy(update={"number": value}) for key, value in numbers.items()
        ],
        limitations=limitations,
    )
