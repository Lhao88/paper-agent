import re
from typing import cast
from xml.etree.ElementTree import Element, ParseError, tostring

import httpx
from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring

from app.config import Settings
from app.errors import DomainError
from app.schemas.contracts import PaperRecord, SearchPage, SearchQuery, SourceRecord
from app.sources.http import check_source_response
from app.sources.normalize import normalize_doi
from app.sources.rate_limit import ARXIV_GATE

ATOM = "{http://www.w3.org/2005/Atom}"
OPEN_SEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"
ARXIV = "{http://arxiv.org/schemas/atom}"


class ArxivSource:
    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    async def search(
        self, query: SearchQuery, cursor: str | None = None, limit: int = 100
    ) -> SearchPage:
        if limit < 1 or (cursor is not None and not cursor.isdigit()):
            raise DomainError("INVALID_QUERY", "检索数量或分页位置无效。")
        tokens = re.findall(r"[A-Za-z0-9_-]+", query.terms)
        if not tokens:
            raise DomainError("INVALID_QUERY", "arXiv检索需要英文术语。")
        expression = " AND ".join(f'all:"{token}"' for token in tokens)
        if query.year_from is not None or query.year_to is not None:
            expression += (
                f" AND submittedDate:[{query.year_from or 1800}01010000 "
                f"TO {query.year_to or 2200}12312359]"
            )
        offset = int(cursor or "0")
        await ARXIV_GATE.wait()
        response = await self.client.get(
            str(self.settings.arxiv_base_url),
            params={
                "search_query": expression,
                "start": offset,
                "max_results": min(limit, 100),
                "sortBy": "relevance",
            },
            headers={"User-Agent": self.settings.http_user_agent},
            timeout=20,
        )
        check_source_response(response)
        try:
            root = cast(Element, fromstring(response.content))
        except (ParseError, DefusedXmlException) as exc:
            raise DomainError("SOURCE_PARSE_FAILED", "arXiv响应不是可安全解析的Atom。") from exc
        entries = root.findall(f"{ATOM}entry")
        records: list[PaperRecord] = []
        warnings: list[str] = []
        for entry in entries:
            identifier = entry.findtext(f"{ATOM}id", "")
            match = re.search(r"/abs/(.+?)(v\d+)?$", identifier)
            title = " ".join(entry.findtext(f"{ATOM}title", "").split())
            if match is None or not title:
                warnings.append("SOURCE_MALFORMED_RECORD")
                continue
            abstract = " ".join(entry.findtext(f"{ATOM}summary", "").split()) or None
            published = entry.findtext(f"{ATOM}published", "")
            pdf_link = next(
                (
                    link.get("href")
                    for link in entry.findall(f"{ATOM}link")
                    if link.get("type") == "application/pdf"
                ),
                None,
            )
            source = SourceRecord(
                provider="arxiv",
                provider_id=match.group(1),
                version_label=match.group(2) or "v1",
                abstract=abstract,
                landing_url=identifier,
                pdf_url=pdf_link,
                raw_payload={
                    "entry_xml": tostring(entry, encoding="unicode"),
                    "updated": entry.findtext(f"{ATOM}updated", ""),
                },
            )
            records.append(
                PaperRecord(
                    title=title,
                    authors=[
                        author.findtext(f"{ATOM}name", "")
                        for author in entry.findall(f"{ATOM}author")
                    ],
                    year=int(published[:4]) if published[:4].isdigit() else None,
                    doi=normalize_doi(entry.findtext(f"{ARXIV}doi")),
                    abstract=abstract,
                    abstract_status="provided" if abstract else "missing",
                    abstract_source_key=source.source_key,
                    sources=[source],
                )
            )
        total_text = root.findtext(f"{OPEN_SEARCH}totalResults", "")
        more = (
            int(total_text) > offset + len(entries)
            if total_text.isdigit()
            else len(entries) >= limit
        )
        return SearchPage(
            records=records,
            next_cursor=str(offset + len(entries)) if more else None,
            has_more=more,
            raw_count=len(entries),
            warnings=warnings,
        )
