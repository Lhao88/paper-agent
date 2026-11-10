from uuid import uuid4

import pytest

from app.errors import DomainError
from app.review.assemble import assemble_review
from app.review.export import export_markdown
from app.review.models import Reference, ReviewSection
from app.review.validate import validate_review
from app.schemas.contracts import ClaimBlock, EvidenceRecord


def sample():
    paper, source, first, second = uuid4(), uuid4(), uuid4(), uuid4()
    evidence = [
        EvidenceRecord(
            evidence_id=identifier,
            paper_id=paper,
            basis="abstract",
            source_id=source,
            quote="retrieval",
            quote_start=0,
            quote_end=9,
            statement_type="reported_fact",
        )
        for identifier in (first, second)
    ]
    reference = Reference(
        paper_id=paper,
        title="Synthetic example",
        authors=["Example"],
        year=2026,
        doi=None,
        source_urls=["https://example.org/paper"],
    )
    section = ReviewSection(
        section_id="s1",
        title="方法",
        blocks=[
            ClaimBlock(text="该研究涉及检索。", evidence_ids=[second], kind="literature_claim"),
            ClaimBlock(text="同一研究的另一段讨论。", evidence_ids=[first], kind="synthesis"),
        ],
        unresolved_questions=[],
    )
    return evidence, reference, section


def test_fake_evidence_and_missing_claim_citation_rejected():
    evidence, reference, section = sample()
    section.blocks[0].evidence_ids = [uuid4()]
    with pytest.raises(DomainError) as invalid:
        assemble_review("topic", [section], evidence, [reference], ["scope"])
    assert invalid.value.code == "EVIDENCE_INVALID"
    section.blocks[0].evidence_ids = []
    with pytest.raises(DomainError) as missing:
        assemble_review("topic", [section], evidence, [reference], ["scope"])
    assert missing.value.code == "CITATION_REQUIRED"


def test_one_paper_has_one_number_after_reference_order_changes():
    evidence, reference, section = sample()
    review = assemble_review("topic", [section], evidence, [reference], ["scope"])
    assert len(review.references) == 1
    assert [block.citation_numbers for block in review.sections[0].blocks] == [[1], [1]]
    assert review.sections[0].blocks[0].block_id != review.sections[0].blocks[1].block_id


def test_structural_validity_does_not_claim_semantic_support():
    evidence, reference, section = sample()
    section.blocks[0].text = "没有被证据支持的夸张因果结论。"
    review = assemble_review("topic", [section], evidence, [reference], ["scope"])
    report = validate_review(review)
    assert report.structural_valid
    assert not report.human_verified
    assert report.semantic_status == "needs_human_check"
    assert review.sections[0].blocks[0].block_id in report.pending_block_ids


def test_export_contains_original_source_and_limits():
    evidence, reference, section = sample()
    review = assemble_review("topic", [section], evidence, [reference], ["mock synthetic"])
    text = export_markdown(review)
    assert "Synthetic example" in text and "https://example.org/paper" in text
    assert "mock synthetic" in text and "检索截止" in text
    assert "仅摘要" in text and "人工" in text and "[1]" in text
