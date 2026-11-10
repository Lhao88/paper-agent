import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import Settings
from app.errors import DomainError
from app.schemas.contracts import PaperRecord, SearchPage, SearchQuery, SourceRecord
from app.sources.http import check_source_response
from app.sources.normalize import normalize_doi, rebuild_abstract
from app.sources.rate_limit import OPENALEX_GATE


class Location(BaseModel):
    pdf_url: str | None = None
    landing_page_url: str | None = None
    license: str | None = None


class Author(BaseModel):
    display_name: str | None = None


class Authorship(BaseModel):
    author: Author


class OpenAlexWork(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    display_name: str | None = None
    title: str | None = None
    doi: str | None = None
    publication_year: int | None = None
    abstract_inverted_index: dict[str, list[int]] | None = None
    authorships: list[Authorship] = Field(default_factory=list)
    best_oa_location: Location | None = None
    primary_location: Location | None = None
    updated_date: str | None = None


class OpenAlexMeta(BaseModel):
    count: int = 0
    next_cursor: str | None = None


class OpenAlexPage(BaseModel):
    meta: OpenAlexMeta
    results: list[dict[str, object]]


class OpenAlexSource:
    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    async def search(
        self, query: SearchQuery, cursor: str | None = None, limit: int = 100
    ) -> SearchPage:
        key = self.settings.openalex_api_key.get_secret_value()
        if cursor and not key:
            raise DomainError("OPENALEX_KEY_REQUIRED_FOR_CURSOR", "来源续页需要配置OpenAlex密钥。")
        if limit < 1:
            raise ValueError("limit must be positive")
        params: dict[str, str | int] = {"search": query.terms, "per_page": min(limit, 100)}
        if key:
            params["cursor"] = cursor or "*"
        filters = []
        if query.year_from is not None:
            filters.append(f"from_publication_date:{query.year_from}-01-01")
        if query.year_to is not None:
            filters.append(f"to_publication_date:{query.year_to}-12-31")
        if query.languages:
            filters.append("language:" + "|".join(query.languages))
        if filters:
            params["filter"] = ",".join(filters)
        headers = {"User-Agent": self.settings.http_user_agent}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        await OPENALEX_GATE.wait()
        response = await self.client.get(
            str(self.settings.openalex_base_url).rstrip("/") + "/works",
            params=params,
            headers=headers,
            timeout=20,
        )
        check_source_response(response)
        try:
            page = OpenAlexPage.model_validate(response.json())
        except (ValidationError, ValueError) as exc:
            raise DomainError("SOURCE_PARSE_FAILED", "OpenAlex响应格式无效。") from exc
        records: list[PaperRecord] = []
        warnings: list[str] = []
        for payload in page.results:
            try:
                work = OpenAlexWork.model_validate(payload)
                title = (work.display_name or work.title or "").strip()
                if not title:
                    warnings.append("SOURCE_RECORD_WITHOUT_TITLE")
                    continue
            except ValidationError:
                warnings.append("SOURCE_MALFORMED_RECORD")
                continue
            try:
                abstract = rebuild_abstract(work.abstract_inverted_index)
            except ValueError:
                abstract = None
                warnings.append("SOURCE_ABSTRACT_INVALID")
            location = work.best_oa_location or work.primary_location
            source = SourceRecord(
                provider="openalex",
                provider_id=work.id,
                version_label=work.updated_date or "unknown",
                abstract=abstract,
                landing_url=location.landing_page_url if location else work.id,
                pdf_url=location.pdf_url if location else None,
                license=location.license if location else None,
                raw_payload=payload,
            )
            positions = sorted(
                {
                    position
                    for values in (work.abstract_inverted_index or {}).values()
                    for position in values
                }
            )
            gaps = bool(positions and len(positions) != positions[-1] + 1)
            records.append(
                PaperRecord(
                    title=title,
                    authors=[
                        a.author.display_name for a in work.authorships if a.author.display_name
                    ],
                    year=work.publication_year,
                    doi=normalize_doi(work.doi),
                    abstract=abstract,
                    abstract_status="reconstruction_incomplete"
                    if gaps
                    else ("provided" if abstract else "missing"),
                    abstract_source_key=source.source_key,
                    sources=[source],
                )
            )
        more = bool(page.meta.next_cursor) if key else page.meta.count > len(page.results)
        if more and not key:
            warnings.append("OPENALEX_KEY_REQUIRED_FOR_CURSOR")
        return SearchPage(
            records=records,
            next_cursor=page.meta.next_cursor if key else None,
            has_more=more,
            raw_count=len(page.results),
            warnings=warnings,
        )
