import httpx
import pytest
import respx

from app.config import Settings
from app.planning.admit import admit_actions
from app.planning.spec import allowed_sources_for
from app.schemas.contracts import CoverageReport, PaperRecord, SearchPage, SearchQuery, SourceRecord
from app.sources.base import PaperSource
from app.sources.semantic_scholar import SCHOLAR_GATE, SemanticScholarSource
from app.tools.search_works import search_works
from tests.unit.test_admit import action, coverage, research_spec


@pytest.fixture(autouse=True)
def fast_scholar_gate() -> None:
    previous = SCHOLAR_GATE.interval
    SCHOLAR_GATE.interval = 0
    yield
    SCHOLAR_GATE.interval = previous


def settings() -> Settings:
    return Settings(_env_file=None, semantic_scholar_base_url="https://scholar.example/graph/v1")


def paper_payload(index: int, doi: str | None = None) -> dict[str, object]:
    return {
        "paperId": f"paper-{index}",
        "title": f"Graph paper {index}",
        "abstract": "We study graphs.",
        "year": 2024,
        "authors": [{"name": "Ada"}],
        "externalIds": {"DOI": doi or f"10.5555/paper-{index}"},
        "citationCount": index,
        "openAccessPdf": {"url": "https://pdf.example/paper.pdf"},
        "url": f"https://www.semanticscholar.org/paper/paper-{index}",
    }


@respx.mock
async def test_search_stays_on_configured_host_and_does_not_fetch_pdf() -> None:
    pdf = respx.get("https://pdf.example/paper.pdf").mock(return_value=httpx.Response(200))
    route = respx.get("https://scholar.example/graph/v1/paper/search").mock(
        return_value=httpx.Response(200, json={"data": [paper_payload(1, "10.1234/ABC")]})
    )
    async with httpx.AsyncClient() as client:
        page = await SemanticScholarSource(client, settings()).search(
            SearchQuery(
                query_id="q", question_ids=["q1"], provider="semantic_scholar", terms="graph"
            )
        )
    assert route.calls[0].request.url.host == "scholar.example"
    assert "paperId" in route.calls[0].request.url.params["fields"]
    assert pdf.called is False
    assert page.records[0].doi == "10.1234/abc"
    assert page.records[0].sources[0].pdf_url == "https://pdf.example/paper.pdf"
    assert page.records[0].sources[0].raw_payload["paperId"] == "paper-1"
    assert page.records[0].sources[0].raw_payload["citationCount"] == 1


@respx.mock
async def test_citation_response_keeps_fifteen_and_reports_cap() -> None:
    route = respx.get("https://scholar.example/graph/v1/paper/seed/references").mock(
        return_value=httpx.Response(
            200, json={"data": [{"citedPaper": paper_payload(index)} for index in range(40)]}
        )
    )
    async with httpx.AsyncClient() as client:
        page = await SemanticScholarSource(client, settings()).neighbors("seed", "references", 15)
    assert route.calls[0].request.url.params["limit"] == "15"
    assert len(page.records) == 15
    assert "citation_cap" in page.warnings


@respx.mock
async def test_cited_by_hop_stays_on_the_api_and_does_not_download_pdf() -> None:
    pdf = respx.get("https://pdf.example/paper.pdf").mock(return_value=httpx.Response(200))
    route = respx.get("https://scholar.example/graph/v1/paper/seed/citations").mock(
        return_value=httpx.Response(200, json={"data": [{"citingPaper": paper_payload(2)}]})
    )
    async with httpx.AsyncClient() as client:
        page = await SemanticScholarSource(client, settings()).neighbors("seed", "cited_by", 15)
    assert route.called is True
    assert route.calls[0].request.url.host == "scholar.example"
    assert pdf.called is False
    assert page.records[0].sources[0].pdf_url == "https://pdf.example/paper.pdf"
    assert not hasattr(SemanticScholarSource, "download_pdf")


@respx.mock
async def test_rate_limit_is_not_an_empty_result() -> None:
    respx.get("https://scholar.example/graph/v1/paper/search").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "2"})
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(Exception, match="限流") as exc:
            await SemanticScholarSource(client, settings()).search(
                SearchQuery(
                    query_id="q", question_ids=["q1"], provider="semantic_scholar", terms="graph"
                )
            )
    assert exc.value.code == "SOURCE_RATE_LIMITED"


def test_disabled_semantic_scholar_is_outside_the_allowlist_and_admission() -> None:
    assert "semantic_scholar" not in allowed_sources_for(Settings(_env_file=None))
    report: CoverageReport = coverage(unmet_question_ids=[])
    result = admit_actions(
        research_spec(),
        [action("search_works", action_id="s2", providers=["semantic_scholar"])],
        report,
        [],
        remaining_source_requests=5,
        remaining_llm_calls=5,
        remaining_deep_reads=5,
    )
    assert result.actions == []
    assert result.rejected[0].reason == "source_not_enabled"


async def test_search_works_uses_registered_sources_without_downloading() -> None:
    class FakeSource:
        def __init__(self) -> None:
            self.calls = 0

        async def search(self, query: SearchQuery, cursor: str | None, limit: int) -> SearchPage:
            self.calls += 1
            source = SourceRecord(
                provider=query.provider,
                provider_id="id",
                version_label="v1",
                pdf_url="https://pdf.example/paper.pdf",
                raw_payload={"paperId": "id", "citationCount": 3},
            )
            return SearchPage(
                records=[PaperRecord(title=query.terms, sources=[source])],
                warnings=["kept"],
                raw_count=1,
            )

    fake: PaperSource = FakeSource()
    result = await search_works(
        [
            SearchQuery(
                query_id="q", question_ids=["q1"], provider="semantic_scholar", terms="graph"
            )
        ],
        {"semantic_scholar": fake},
    )
    assert fake.calls == 1
    assert result.records[0].title == "graph"
    assert result.warnings == ["kept"]
    missing = await search_works(
        [SearchQuery(query_id="q", question_ids=["q1"], provider="openalex", terms="graph")],
        {"semantic_scholar": fake},
    )
    assert missing.records == []
    assert missing.warnings == ["source_unavailable:openalex"]
