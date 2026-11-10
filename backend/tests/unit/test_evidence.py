from uuid import uuid4

import pytest

from app.documents.evidence import validate_evidence
from app.errors import DomainError
from app.schemas.contracts import ChunkRecord, ExtractionCandidate


def chunk(text: str) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=uuid4(), document_id=uuid4(), page_number=7, text=text, text_sha256="a" * 64
    )


def candidate(record: ChunkRecord, quote: str) -> ExtractionCandidate:
    return ExtractionCandidate(
        field_name="method",
        value_zh="方法说明",
        chunk_id=record.chunk_id,
        quote=quote,
        statement_type="reported_fact",
    )


def test_quote_match_maps_normalized_whitespace_back_to_original_characters() -> None:
    record = chunk("Intro. We\n  evaluate graph retrieval. End.")
    result = validate_evidence(candidate(record, "We evaluate graph retrieval."), record, uuid4())
    assert result.page_number == 7
    assert result.quote == "We\n  evaluate graph retrieval."
    assert record.text[result.quote_start : result.quote_end] == result.quote


@pytest.mark.parametrize(
    "text,quote", [("Original fact", "invented fact"), ("fact and fact", "fact")]
)
def test_missing_or_ambiguous_quotes_are_rejected(text: str, quote: str) -> None:
    record = chunk(text)
    with pytest.raises(DomainError) as exc:
        validate_evidence(candidate(record, quote), record, uuid4())
    assert exc.value.code == "EVIDENCE_INVALID"
