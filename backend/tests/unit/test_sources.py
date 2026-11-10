import httpx
import pytest
import respx

from app.config import Settings
from app.errors import DomainError
from app.schemas.contracts import SearchQuery
from app.sources.arxiv import ArxivSource
from app.sources.openalex import OpenAlexSource


@respx.mock
async def test_openalex_restores_original_abstract_and_discloses_cursor_limit_without_key() -> None:
    route = respx.get("https://api.openalex.org/works").mock(
        return_value=httpx.Response(
            200,
            json={
                "meta": {"count": 201},
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "display_name": "Graph learning",
                        "doi": "https://doi.org/10.1234/ABC",
                        "publication_year": 2024,
                        "abstract_inverted_index": {"study": [1], "We": [0]},
                        "authorships": [{"author": {"display_name": "Ada"}}],
                    }
                ],
            },
        )
    )
    async with httpx.AsyncClient() as client:
        page = await OpenAlexSource(client, Settings(_env_file=None)).search(
            SearchQuery(query_id="q", question_ids=["q1"], provider="openalex", terms="graph"),
            limit=200,
        )
    assert page.records[0].abstract == "We study"
    assert page.records[0].doi == "10.1234/abc"
    assert page.has_more is True
    assert page.next_cursor is None
    assert "OPENALEX_KEY_REQUIRED_FOR_CURSOR" in page.warnings
    assert route.calls[0].request.url.params["per_page"] == "100"


@respx.mock
async def test_missing_abstract_is_preserved_and_cursor_requires_key_before_http() -> None:
    respx.get("https://api.openalex.org/works").mock(
        return_value=httpx.Response(
            200,
            json={
                "meta": {"count": 1},
                "results": [{"id": "https://openalex.org/W2", "title": "Title"}],
            },
        )
    )
    async with httpx.AsyncClient() as client:
        source = OpenAlexSource(client, Settings(_env_file=None))
        query = SearchQuery(query_id="q", question_ids=["q1"], provider="openalex", terms="graph")
        page = await source.search(query)
        assert page.records[0].abstract is None
        assert page.records[0].abstract_status == "missing"
        with pytest.raises(DomainError) as exc:
            await source.search(query, cursor="next")
        assert exc.value.code == "OPENALEX_KEY_REQUIRED_FOR_CURSOR"


@respx.mock
async def test_openalex_rate_limit_is_a_source_error_not_empty_research() -> None:
    respx.get("https://api.openalex.org/works").mock(
        return_value=httpx.Response(
            429,
            headers={"Retry-After": "5"},
        )
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(DomainError) as exc:
            await OpenAlexSource(client, Settings(_env_file=None)).search(
                SearchQuery(query_id="q", question_ids=["q1"], provider="openalex", terms="graph")
            )
    assert exc.value.code == "SOURCE_RATE_LIMITED"


@respx.mock
async def test_arxiv_retains_version_pdf_link_and_original_summary() -> None:
    atom = """<feed xmlns="http://www.w3.org/2005/Atom"
        xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
      <opensearch:totalResults>1</opensearch:totalResults>
      <entry><id>http://arxiv.org/abs/2401.00001v2</id><title> Graph research </title>
      <published>2024-01-01T00:00:00Z</published><updated>2024-02-01T00:00:00Z</updated>
      <summary>Original abstract.</summary><author><name>Ada</name></author>
      <link title="pdf" type="application/pdf" href="https://arxiv.org/pdf/2401.00001v2"/>
      </entry></feed>"""
    respx.get("https://export.arxiv.org/api/query").mock(
        return_value=httpx.Response(200, text=atom)
    )
    async with httpx.AsyncClient() as client:
        page = await ArxivSource(client, Settings(_env_file=None)).search(
            SearchQuery(query_id="q", question_ids=["q1"], provider="arxiv", terms="graph research")
        )
    assert page.records[0].abstract == "Original abstract."
    assert page.records[0].sources[0].version_label == "v2"
    assert page.records[0].sources[0].provider_id == "2401.00001"
    assert page.records[0].sources[0].pdf_url == "https://arxiv.org/pdf/2401.00001v2"
    assert page.records[0].year == 2024
