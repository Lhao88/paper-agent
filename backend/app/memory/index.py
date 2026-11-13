import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from typing import Literal
from uuid import UUID

from rank_bm25 import BM25Plus

from app.schemas.contracts import ChunkRecord
from app.screening.text import tokenize

EmbeddingMode = Literal["off", "mock", "live"]


def index_tokens(text: str) -> list[str]:
    runs = re.findall(r"[\u4e00-\u9fff]+", text)
    characters = [character for run in runs for character in run]
    return tokenize(text) + runs + characters


def mock_embedding(text: str, dimensions: int = 256) -> list[float]:
    if dimensions < 1:
        raise ValueError("dimensions must be positive")
    vector = [0.0] * dimensions
    for token in index_tokens(text) or [text]:
        digest = hashlib.sha256(token.encode()).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign
    return _normalize(vector)


def read_real_array(value: Sequence[float] | None) -> list[float]:
    """把 PostgreSQL REAL[] 读成进程内浮点列表，不在数据库里算距离。"""
    if value is None:
        return []
    return [float(item) for item in value]


def in_process_cosine(left: Sequence[float], right: Sequence[float]) -> float:
    return _cosine(read_real_array(left), read_real_array(right))


def rank_chunks(
    chunks: list[ChunkRecord],
    query: str,
    mode: EmbeddingMode,
    vectors: Mapping[UUID, Sequence[float]] | None = None,
    query_vector: Sequence[float] | None = None,
) -> list[ChunkRecord]:
    if not chunks:
        return []
    lexical = _bm25([chunk.text for chunk in chunks], query)
    if mode == "off":
        ordered = sorted(
            zip(lexical, chunks, strict=True),
            key=lambda item: (-item[0], str(item[1].chunk_id)),
        )
        return [chunk for _, chunk in ordered]
    peak = max(lexical) if lexical else 0.0
    normalized = [score / peak if peak else 0.0 for score in lexical]
    probe = read_real_array(query_vector) if query_vector is not None else mock_embedding(query)
    provided = vectors or {}
    scored: list[tuple[float, ChunkRecord]] = []
    for score, chunk in zip(normalized, chunks, strict=True):
        stored = provided.get(chunk.chunk_id)
        vector = (
            mock_embedding(chunk.text, dimensions=len(probe) or 256)
            if stored is None
            else read_real_array(stored)
        )
        hybrid = 0.65 * score + 0.35 * in_process_cosine(probe, vector)
        scored.append((hybrid, chunk))
    scored.sort(key=lambda item: (-item[0], str(item[1].chunk_id)))
    return [chunk for _, chunk in scored]


def _bm25(texts: list[str], query: str) -> list[float]:
    corpus = [index_tokens(text) for text in texts]
    tokens = index_tokens(query)
    if not tokens:
        return [0.0 for _ in texts]
    prepared = [row or ["__empty__"] for row in corpus]
    raw = BM25Plus(prepared).get_scores(tokens)
    query_terms = set(tokens)
    return [
        float(score) if query_terms.intersection(row) else 0.0
        for row, score in zip(corpus, raw, strict=True)
    ]


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    return sum(x * y for x, y in zip(_normalize(left), _normalize(right), strict=True))
