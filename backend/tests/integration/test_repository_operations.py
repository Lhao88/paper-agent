from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Chunk, Document, Evidence
from app.errors import DomainError
from app.repositories.artifacts import ArtifactRepository
from app.repositories.papers import PaperRepository
from app.repositories.projects import ProjectRepository


async def test_run_creation_is_idempotent_and_conflicting_inputs_are_rejected(
    db_session: AsyncSession,
) -> None:
    repo = ProjectRepository(db_session)
    project = await repo.create("研究", "主题")
    first = await repo.create_run(project.id, "request-1", "hash-1", {}, {})
    repeat = await repo.create_run(project.id, "request-1", "hash-1", {}, {})
    assert first.id == repeat.id
    with pytest.raises(DomainError, match="不同请求"):
        await repo.create_run(project.id, "request-1", "hash-2", {}, {})
    with pytest.raises(DomainError) as exc:
        await repo.create_run(project.id, "request-2", "hash-1", {}, {})
    assert exc.value.code == "ACTIVE_RUN_EXISTS"


async def test_artifacts_reuse_completed_operation_and_preserve_payload(
    db_session: AsyncSession,
) -> None:
    project = await ProjectRepository(db_session).create("研究", "主题")
    run = await ProjectRepository(db_session).create_run(project.id, "run", "h", {}, {})
    repo = ArtifactRepository(db_session)
    first = await repo.get_or_create(run.id, "screen:1", "screening", {"score": 4}, "input")
    repeat = await repo.get_or_create(run.id, "screen:1", "screening", {"score": 0}, "input")
    assert repeat.id == first.id
    assert repeat.payload_json == {"score": 4}
    with pytest.raises(DomainError):
        await repo.get_or_create(run.id, "screen:1", "screening", {}, "changed-input")


async def test_duplicate_doi_merges_sources_but_changed_abstract_preserves_snapshot(
    db_session: AsyncSession,
) -> None:
    repo = PaperRepository(db_session)
    provider_id = str(uuid4())
    doi = f"10.9999/{uuid4()}"
    first = await repo.upsert_source("openalex", provider_id, "v1", "Title", doi, "old", {})
    repeated = await repo.upsert_source("openalex", provider_id, "v1", "Title", doi, "old", {})
    changed = await repo.upsert_source("openalex", provider_id, "v1", "Title", doi, "new", {})
    other = await repo.upsert_source("arxiv", str(uuid4()), "v1", "Title", doi, "other", {})
    assert first.id == repeated.id
    assert changed.id != first.id
    assert first.abstract_text == "old"
    assert {first.paper_id, changed.paper_id, other.paper_id} == {first.paper_id}


async def test_fulltext_evidence_cannot_omit_a_page_number(db_session: AsyncSession) -> None:
    source = await PaperRepository(db_session).upsert_source(
        "fixture", str(uuid4()), "v1", "Title", None, "abstract", {}
    )
    document = Document(
        paper_id=source.paper_id, source_id=source.id, sha256="a" * 64, storage_key="fixture.pdf"
    )
    db_session.add(document)
    await db_session.flush()
    chunk = Chunk(
        document_id=document.id, page_number=1, text="Evidence quote", text_sha256="b" * 64
    )
    db_session.add(chunk)
    await db_session.flush()
    with pytest.raises(IntegrityError) as exc:
        async with db_session.begin_nested():
            db_session.add(
                Evidence(
                    paper_id=source.paper_id,
                    basis="full_text",
                    document_id=document.id,
                    chunk_id=chunk.id,
                    quote="Evidence",
                    quote_start=0,
                    quote_end=8,
                    page_number=None,
                    statement_type="reported_fact",
                )
            )
            await db_session.flush()
    assert getattr(exc.value.orig, "sqlstate", None) == "23514"
