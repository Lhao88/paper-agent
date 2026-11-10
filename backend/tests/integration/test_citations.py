from uuid import UUID

import httpx
import respx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import Paper, PaperNeighbor
from app.repositories.papers import PaperRepository
from app.repositories.projects import ProjectRepository
from app.sources.semantic_scholar import SCHOLAR_GATE
from app.tools.citations import expand_citations


@respx.mock
async def test_existing_doi_adds_a_neighbor_without_a_new_paper(db_session: AsyncSession) -> None:
    project = await ProjectRepository(db_session).create("引文", "图神经网络")
    papers = PaperRepository(db_session)
    seed = await papers.upsert_source("openalex", "W-seed", "v1", "种子", None, "摘要", {})
    known = await papers.upsert_source(
        "openalex", "W-known", "v1", "已收录", "10.5555/known", "摘要", {}
    )
    before = await db_session.scalar(select(func.count()).select_from(Paper))
    respx.get("https://scholar.example/graph/v1/paper/seed/references").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "citedPaper": {
                            "paperId": "new-id",
                            "title": "已收录",
                            "externalIds": {"DOI": "10.5555/known"},
                            "citationCount": 4,
                            "openAccessPdf": {"url": "https://pdf.example/known.pdf"},
                        }
                    }
                ]
            },
        )
    )
    settings = Settings(_env_file=None, semantic_scholar_base_url="https://scholar.example/graph/v1")
    SCHOLAR_GATE.interval = 0
    async with httpx.AsyncClient() as client:
        result = await expand_citations(
            db_session,
            project_id=project.id,
            from_paper_id=seed.paper_id,
            provider_paper_id="seed",
            provider="semantic_scholar",
            direction="references",
            limit=15,
            client=client,
            settings=settings,
        )
    after = await db_session.scalar(select(func.count()).select_from(Paper))
    neighbors = list(await db_session.scalars(select(PaperNeighbor)))
    assert before == after
    assert result.neighbor_paper_ids == [known.paper_id]
    assert len(neighbors) == 1
    assert neighbors[0].from_paper_id == seed.paper_id
    assert neighbors[0].to_paper_id == known.paper_id
    assert neighbors[0].direction == "references"
    assert isinstance(known.paper_id, UUID)
