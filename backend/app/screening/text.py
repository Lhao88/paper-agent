import re

from rank_bm25 import BM25Plus

STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "for",
        "of",
        "on",
        "in",
        "to",
        "with",
        "by",
        "from",
        "we",
        "our",
        "this",
        "that",
        "is",
        "are",
        "be",
        "as",
        "at",
        "it",
        "its",
        "using",
    }
)


def tokenize(text: str) -> list[str]:
    return [
        word
        for word in re.findall(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", text.casefold())
        if word not in STOP_WORDS
    ]


def bm25_scores(texts: list[str], terms: list[str]) -> list[float]:
    if not texts:
        return []
    corpus = [tokenize(text) for text in texts]
    query = tokenize(" ".join(terms))
    scores = BM25Plus([tokens or ["__empty__"] for tokens in corpus]).get_scores(query)
    query_set = set(query)
    return [
        float(score) if query_set.intersection(tokens) else 0.0
        for tokens, score in zip(corpus, scores, strict=True)
    ]
