from collections.abc import Awaitable, Callable
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.memory.index import rank_chunks
from app.schemas.contracts import ChunkRecord, ExtractionCandidate, ExtractionOutput

EmbeddingMode = Literal["off", "mock", "live"]


class SearchInPaperResult(BaseModel):
    chunks: list[ChunkRecord]
    failure: str | None = None


async def search_in_paper(
    chunks: list[ChunkRecord],
    query: str,
    embedding_mode: EmbeddingMode,
    *,
    limit: int,
    vectors: dict[UUID, list[float]] | None = None,
    query_vector: list[float] | None = None,
    extract: Callable[[list[ChunkRecord]], Awaitable[ExtractionOutput]],
    record: Callable[[ExtractionCandidate], Awaitable[None]] | None = None,
) -> SearchInPaperResult:
    if limit < 1:
        raise ValueError("limit must be positive")
    selected = rank_chunks(chunks, query, embedding_mode, vectors, query_vector)[:limit]
    if not selected:
        return SearchInPaperResult(chunks=[])
    extracted = await extract(selected)
    allowed = {chunk.chunk_id for chunk in selected}
    if any(candidate.chunk_id not in allowed for candidate in extracted.candidates):
        return SearchInPaperResult(chunks=selected, failure="chunk_not_returned")
    if record is not None:
        for candidate in extracted.candidates:
            await record(candidate)
    return SearchInPaperResult(chunks=selected)
