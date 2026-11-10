from pathlib import Path

from pydantic import TypeAdapter

from app.schemas.contracts import PaperRecord, SearchPage, SearchQuery


class MockPaperSource:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def search(self, query: SearchQuery, cursor: str | None, limit: int) -> SearchPage:
        records = TypeAdapter(list[PaperRecord]).validate_json(
            self.path.read_text(encoding="utf-8")
        )
        offset = int(cursor or "0")
        selected = records[offset : offset + limit]
        following = offset + len(selected)
        return SearchPage(
            records=selected,
            next_cursor=str(following) if following < len(records) else None,
            has_more=following < len(records),
            raw_count=len(selected),
            warnings=["MOCK_SYNTHETIC_CORPUS"],
        )


class FrozenPaperSource(MockPaperSource):
    async def search(self, query: SearchQuery, cursor: str | None, limit: int) -> SearchPage:
        records = [
            PaperRecord.model_validate_json(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        offset = int(cursor or "0")
        selected = records[offset : offset + limit]
        following = offset + len(selected)
        return SearchPage(
            records=selected,
            next_cursor=str(following) if following < len(records) else None,
            has_more=following < len(records),
            raw_count=len(selected),
            warnings=["FROZEN_CORPUS_OFFLINE"],
        )
