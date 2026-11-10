from uuid import UUID

from app.errors import DomainError
from app.schemas.contracts import ChunkRecord, EvidenceRecord, ExtractionCandidate


def validate_evidence(
    candidate: ExtractionCandidate, chunk: ChunkRecord, paper_id: UUID
) -> EvidenceRecord:
    if candidate.chunk_id != chunk.chunk_id:
        raise DomainError("EVIDENCE_INVALID", "引用了不属于当前片段的标识。")
    return evidence_from_quote(
        candidate.quote,
        chunk.text,
        paper_id,
        "full_text",
        document_id=chunk.document_id,
        chunk_id=chunk.chunk_id,
        page_number=chunk.page_number,
        statement_type=candidate.statement_type,
    )


def _normalize_whitespace(text: str) -> tuple[str, list[int]]:
    characters: list[str] = []
    offsets: list[int] = []
    for index, character in enumerate(text):
        if character.isspace():
            if characters and characters[-1] != " ":
                characters.append(" ")
                offsets.append(index)
        else:
            characters.append(character)
            offsets.append(index)
    if characters and characters[-1] == " ":
        characters.pop()
        offsets.pop()
    return "".join(characters), offsets


def evidence_from_quote(
    quote: str,
    original: str,
    paper_id: UUID,
    basis: str,
    *,
    source_id: UUID | None = None,
    document_id: UUID | None = None,
    chunk_id: UUID | None = None,
    page_number: int | None = None,
    statement_type: str = "reported_fact",
) -> EvidenceRecord:
    normalized, offsets = _normalize_whitespace(original)
    normalized_quote, _ = _normalize_whitespace(quote)
    start = normalized.find(normalized_quote) if normalized_quote else -1
    if start < 0 or normalized.find(normalized_quote, start + 1) >= 0:
        raise DomainError("EVIDENCE_INVALID", "引用原句不存在或无法唯一定位。")
    original_start = offsets[start]
    original_end = offsets[start + len(normalized_quote) - 1] + 1
    return EvidenceRecord.model_validate(
        {
            "paper_id": paper_id,
            "basis": basis,
            "source_id": source_id,
            "document_id": document_id,
            "chunk_id": chunk_id,
            "page_number": page_number,
            "quote": original[original_start:original_end],
            "quote_start": original_start,
            "quote_end": original_end,
            "statement_type": statement_type,
        }
    )
