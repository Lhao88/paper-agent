import os

import httpx
import pytest

from app.config import Settings
from app.schemas.contracts import SearchQuery
from app.sources.openalex import OpenAlexSource

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.getenv("RUN_LIVE_TESTS") != "1", reason="explicit live opt-in required"),
]


async def test_one_openalex_page_has_verifiable_source_identity():
    settings = Settings()
    if settings.source_mode != "live":
        pytest.skip("SOURCE_MODE=live is required")
    async with httpx.AsyncClient(trust_env=False, timeout=30) as client:
        page = await OpenAlexSource(client, settings).search(
            SearchQuery(
                query_id="probe",
                question_ids=["q1"],
                provider="openalex",
                terms="academic literature retrieval",
            ),
            None,
            3,
        )
    assert page.records
    assert all(paper.sources[0].provider_id for paper in page.records)


async def test_semantic_scholar_search_requires_live_opt_in():
    settings = Settings()
    if settings.source_mode != "live" or not settings.enable_semantic_scholar:
        pytest.skip("SOURCE_MODE=live and ENABLE_SEMANTIC_SCHOLAR=true are required")
    async with httpx.AsyncClient(trust_env=False, timeout=30) as client:
        from app.sources.semantic_scholar import SemanticScholarSource

        page = await SemanticScholarSource(client, settings).search(
            SearchQuery(
                query_id="probe",
                question_ids=["q1"],
                provider="semantic_scholar",
                terms="academic literature retrieval",
            ),
            None,
            3,
        )
    assert page.records
    assert page.records[0].sources[0].raw_payload.get("paperId")
