from typing import Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import PaperNeighbor
from app.repositories.papers import PaperRepository
from app.schemas.contracts import PaperRecord
from app.sources.semantic_scholar import NEIGHBOR_CAP, SemanticScholarSource


class CitationExpansion(BaseModel):
    records: list[PaperRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    neighbor_paper_ids: list[UUID] = Field(default_factory=list)


async def expand_citations(
    session: AsyncSession,
    *,
    project_id: UUID,
    from_paper_id: UUID,
    provider_paper_id: str,
    provider: str,
    direction: Literal["references", "cited_by"],
    limit: int,
    client: httpx.AsyncClient,
    settings: Settings,
) -> CitationExpansion:
    if provider != "semantic_scholar":
        return CitationExpansion(warnings=["citation_provider_unsupported"])
    page = await SemanticScholarSource(client, settings).neighbors(
        provider_paper_id, direction, min(limit, NEIGHBOR_CAP)
    )
    papers = PaperRepository(session)
    neighbor_ids: list[UUID] = []
    for record in page.records:
        source = record.sources[0]
        saved = await papers.upsert_source(
            source.provider,
            source.provider_id,
            source.version_label,
            record.title,
            record.doi,
            record.abstract,
            source.raw_payload,
            year=record.year,
            authors=record.authors,
        )
        await papers.attach(project_id, saved.paper_id, added_by="citation")
        await session.execute(
            insert(PaperNeighbor)
            .values(
                project_id=project_id,
                from_paper_id=from_paper_id,
                to_paper_id=saved.paper_id,
                direction=direction,
                provider=provider,
            )
            .on_conflict_do_nothing()
        )
        neighbor_ids.append(saved.paper_id)
    await session.flush()
    return CitationExpansion(
        records=page.records, warnings=list(page.warnings), neighbor_paper_ids=neighbor_ids
    )
