import httpx

from app.config import PROJECT_ROOT, Settings
from app.errors import DomainError
from app.sources.arxiv import ArxivSource
from app.sources.base import PaperSource
from app.sources.mock import FrozenPaperSource, MockPaperSource
from app.sources.openalex import OpenAlexSource
from app.sources.semantic_scholar import SemanticScholarSource


def build_sources(settings: Settings, client: httpx.AsyncClient) -> dict[str, PaperSource]:
    if settings.mock_corpus_profile == "frozen":
        path = settings.frozen_corpus_path
        root = (PROJECT_ROOT / "evals").resolve()
        if path is None or not path.resolve().is_relative_to(root) or not path.is_file():
            raise DomainError("INVALID_CORPUS_PATH", "冻结语料必须位于evals目录。")
        frozen = FrozenPaperSource(path)
        return {"openalex": frozen, **_optional_sources(settings, frozen)}
    if settings.source_mode == "mock":
        filename = (
            "papers-extended.json" if settings.mock_corpus_profile == "extended" else "papers.json"
        )
        source = MockPaperSource(PROJECT_ROOT / "backend" / "fixtures" / filename)
        return {"openalex": source, **_optional_sources(settings, source)}
    return {
        "openalex": OpenAlexSource(client, settings),
        **_live_sources(settings, client),
    }


def _optional_sources(settings: Settings, shared: PaperSource) -> dict[str, PaperSource]:
    sources: dict[str, PaperSource] = {}
    if settings.enable_arxiv:
        sources["arxiv"] = shared
    if settings.enable_semantic_scholar:
        sources["semantic_scholar"] = shared
    return sources


def _live_sources(settings: Settings, client: httpx.AsyncClient) -> dict[str, PaperSource]:
    sources: dict[str, PaperSource] = {}
    if settings.enable_arxiv:
        sources["arxiv"] = ArxivSource(client, settings)
    if settings.enable_semantic_scholar:
        sources["semantic_scholar"] = SemanticScholarSource(client, settings)
    return sources
