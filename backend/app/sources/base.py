from typing import Protocol

from app.schemas.contracts import SearchPage, SearchQuery


class PaperSource(Protocol):
    async def search(self, query: SearchQuery, cursor: str | None, limit: int) -> SearchPage: ...
