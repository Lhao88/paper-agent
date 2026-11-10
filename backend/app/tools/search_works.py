from app.schemas.contracts import RetrievalResult, SearchQuery
from app.sources.base import PaperSource


async def search_works(
    queries: list[SearchQuery], sources: dict[str, PaperSource], *, limit: int = 20
) -> RetrievalResult:
    records = []
    warnings: list[str] = []
    for query in queries:
        source = sources.get(query.provider)
        if source is None:
            warnings.append(f"source_unavailable:{query.provider}")
            continue
        page = await source.search(query, None, limit)
        records.extend(page.records)
        warnings.extend(page.warnings)
    return RetrievalResult(records=records, warnings=warnings)
