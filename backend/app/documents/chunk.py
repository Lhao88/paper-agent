import hashlib
import re
from uuid import NAMESPACE_URL, uuid5

from app.schemas.contracts import ChunkRecord, ChunkSelection, ParsedDocument, Question
from app.screening.text import bm25_scores


def chunk_document(document: ParsedDocument, target_tokens: int = 700) -> list[ChunkRecord]:
    if target_tokens < 1:
        raise ValueError("target_tokens must be positive")
    chunks: list[ChunkRecord] = []
    size = target_tokens * 4
    for page in document.pages:
        start = 0
        while start < len(page.text):
            end = min(start + size, len(page.text))
            if end < len(page.text):
                boundary = page.text.rfind(" ", start + size // 2, end)
                if boundary > start:
                    end = boundary
            text = page.text[start:end]
            if text.strip():
                digest = hashlib.sha256(text.encode()).hexdigest()
                heading = re.search(
                    r"(?im)^\s*(?:\d+[.\d]*\s+)?"
                    r"(methods?|experiments?|results?|limitations?|discussion|conclusion)",
                    text[:250],
                )
                chunks.append(
                    ChunkRecord(
                        chunk_id=uuid5(
                            NAMESPACE_URL,
                            f"{document.document_id}:{page.page_number}:{start}:{digest}",
                        ),
                        document_id=document.document_id,
                        page_number=page.page_number,
                        text=text,
                        text_sha256=digest,
                        section_hint=heading.group(1).casefold() if heading else None,
                        words=page.words,
                    )
                )
            start = end
    return chunks


def choose_chunks(
    chunks: list[ChunkRecord],
    questions: list[Question],
    limit: int,
    parser_warnings: list[str] | None = None,
) -> ChunkSelection:
    if not chunks or limit < 1:
        raise ValueError("nonempty chunks and a positive limit are required")
    selected: list[int] = []
    texts = [chunk.text for chunk in chunks]
    scores = [bm25_scores(texts, question.search_terms_en) for question in questions]
    for ranking in scores:
        best = min(range(len(chunks)), key=lambda i: (-ranking[i], str(chunks[i].chunk_id)))
        if best not in selected and len(selected) < limit:
            selected.append(best)
    for section in ("methods", "method", "experiments", "results", "limitations", "discussion"):
        candidate = next(
            (
                i
                for i, chunk in enumerate(chunks)
                if chunk.section_hint == section and i not in selected
            ),
            None,
        )
        if candidate is not None and len(selected) < limit:
            selected.append(candidate)
    best_scores = [max((ranking[i] for ranking in scores), default=0) for i in range(len(chunks))]
    for index in sorted(
        range(len(chunks)), key=lambda i: (-best_scores[i], str(chunks[i].chunk_id))
    ):
        if len(selected) >= limit:
            break
        if index not in selected:
            selected.append(index)
    covered = {chunks[i].section_hint or "unidentified" for i in selected}
    omitted = {
        chunk.section_hint or "unidentified" for i, chunk in enumerate(chunks) if i not in selected
    }
    return ChunkSelection(
        document_id=chunks[0].document_id,
        chunk_ids=[chunks[i].chunk_id for i in selected],
        covered_sections=sorted(covered),
        omitted_sections=sorted(omitted),
        reading_scope="full_text_complete"
        if len(selected) == len(chunks) and not parser_warnings
        else "full_text_targeted",
        total_chunks=len(chunks),
        omitted_chunk_count=len(chunks) - len(selected),
    )
