from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import Settings
from app.errors import DomainError
from app.schemas.contracts import PaperRecord, SearchPage, SearchQuery, SourceRecord
from app.sources.http import check_source_response
from app.sources.normalize import normalize_doi
from app.sources.rate_limit import IntervalGate

SCHOLAR_GATE = IntervalGate(1.0)
FIELDS = "paperId,title,abstract,year,authors,externalIds,citationCount,openAccessPdf,url"
NEIGHBOR_CAP = 15


class Author(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str | None = None


class OpenPdf(BaseModel):
    model_config = ConfigDict(extra="allow")
    url: str | None = None


class ScholarPaper(BaseModel):
    model_config = ConfigDict(extra="allow")
    paperId: str
    title: str | None = None
    abstract: str | None = None
    year: int | None = None
    authors: list[Author] = Field(default_factory=list)
    externalIds: dict[str, object] | None = None
    citationCount: int | None = None
    openAccessPdf: OpenPdf | None = None
    url: str | None = None


class SemanticScholarSource:
    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    async def search(
        self, query: SearchQuery, cursor: str | None = None, limit: int = 100
    ) -> SearchPage:
        if limit < 1:
            raise ValueError("limit must be positive")
        params: dict[str, str | int] = {
            "query": query.terms,
            "limit": min(limit, 100),
            "fields": FIELDS,
        }
        if cursor:
            params["offset"] = cursor
        if query.year_from is not None or query.year_to is not None:
            start = query.year_from or ""
            end = query.year_to or ""
            params["year"] = f"{start}-{end}"
        payload = await self._get("/paper/search", params)
        data = payload.get("data")
        if not isinstance(data, list):
            raise DomainError("SOURCE_PARSE_FAILED", "Semantic Scholar响应格式无效。")
        records, warnings = _records(data)
        return SearchPage(records=records, warnings=warnings, raw_count=len(data))

    async def neighbors(self, paper_id: str, direction: str, limit: int) -> SearchPage:
        if direction not in {"references", "cited_by"}:
            raise DomainError("CITATION_DIRECTION_INVALID", "引文方向无效。")
        if limit < 1:
            raise ValueError("limit must be positive")
        applied = min(limit, NEIGHBOR_CAP)
        path = "/references" if direction == "references" else "/citations"
        payload = await self._get(
            f"/paper/{paper_id}{path}", {"limit": applied, "fields": FIELDS}
        )
        data = payload.get("data")
        if not isinstance(data, list):
            raise DomainError("SOURCE_PARSE_FAILED", "Semantic Scholar引文响应格式无效。")
        papers: list[Any] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            key = "citedPaper" if direction == "references" else "citingPaper"
            nested = item.get(key)
            if isinstance(nested, dict):
                papers.append(nested)
        records, warnings = _records(papers[:applied])
        if len(papers) > applied:
            warnings.append("citation_cap")
        return SearchPage(records=records, warnings=warnings, raw_count=len(papers))

    async def _get(self, path: str, params: dict[str, str | int]) -> dict[str, object]:
        await SCHOLAR_GATE.wait()
        headers = {"User-Agent": self.settings.http_user_agent}
        key = self.settings.semantic_scholar_api_key.get_secret_value().strip()
        if key:
            headers["x-api-key"] = key
        response = await self.client.get(
            str(self.settings.semantic_scholar_base_url).rstrip("/") + path,
            params=params,
            headers=headers,
            timeout=20,
        )
        check_source_response(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise DomainError("SOURCE_PARSE_FAILED", "Semantic Scholar响应格式无效。") from exc
        if not isinstance(payload, dict):
            raise DomainError("SOURCE_PARSE_FAILED", "Semantic Scholar响应格式无效。")
        return payload


def _records(items: Sequence[Any]) -> tuple[list[PaperRecord], list[str]]:
    records: list[PaperRecord] = []
    warnings: list[str] = []
    for item in items:
        try:
            work = ScholarPaper.model_validate(item)
        except ValidationError:
            warnings.append("SOURCE_MALFORMED_RECORD")
            continue
        title = (work.title or "").strip()
        if not title:
            warnings.append("SOURCE_RECORD_WITHOUT_TITLE")
            continue
        doi = work.externalIds.get("DOI") if work.externalIds else None
        source = SourceRecord(
            provider="semantic_scholar",
            provider_id=work.paperId,
            version_label="s2",
            abstract=work.abstract,
            landing_url=work.url,
            pdf_url=work.openAccessPdf.url if work.openAccessPdf else None,
            raw_payload={"paperId": work.paperId, "citationCount": work.citationCount},
        )
        records.append(
            PaperRecord(
                title=title,
                authors=[author.name for author in work.authors if author.name],
                year=work.year,
                doi=normalize_doi(doi if isinstance(doi, str) else None),
                abstract=work.abstract,
                abstract_status="provided" if work.abstract else "missing",
                abstract_source_key=source.source_key,
                sources=[source],
            )
        )
    return records, warnings
