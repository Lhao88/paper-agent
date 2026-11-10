import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Paper, PaperSource, ProjectPaper
from app.repositories.locking import lock_operation


class PaperRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_source(
        self,
        provider: str,
        provider_id: str,
        version_label: str,
        title: str,
        canonical_doi: str | None,
        abstract: str | None,
        payload: dict[str, object],
        year: int | None = None,
        authors: list[str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> PaperSource:
        content_hash = hashlib.sha256(
            json.dumps(
                {"abstract": abstract, "payload": payload}, sort_keys=True, ensure_ascii=False
            ).encode()
        ).hexdigest()
        snapshot_version = f"{version_label}:{content_hash[:16]}"
        await lock_operation(self.session, f"source:{provider}:{provider_id}")
        existing = await self.session.scalar(
            select(PaperSource).where(
                PaperSource.provider == provider,
                PaperSource.provider_id == provider_id,
                PaperSource.version_label == snapshot_version,
            )
        )
        if existing is not None:
            return existing
        prior = await self.session.scalar(
            select(PaperSource)
            .where(
                PaperSource.provider == provider,
                PaperSource.provider_id == provider_id,
            )
            .order_by(PaperSource.created_at.desc())
            .limit(1)
        )
        paper_id = prior.paper_id if prior is not None else uuid4()
        if prior is None:
            statement = (
                insert(Paper)
                .values(
                    id=paper_id,
                    title=title,
                    canonical_doi=canonical_doi,
                    normalized_title=" ".join(title.casefold().split()),
                    authors_json=authors or [],
                    year=year,
                )
                .on_conflict_do_nothing(index_elements=[Paper.canonical_doi])
                .returning(Paper.id)
            )
            inserted = await self.session.scalar(statement)
            if inserted is None:
                existing_paper = await self.session.scalar(
                    select(Paper).where(Paper.canonical_doi == canonical_doi)
                )
                if existing_paper is None:
                    raise RuntimeError("paper identity conflict could not be resolved")
                paper_id = existing_paper.id
        source = PaperSource(
            paper_id=paper_id,
            provider=provider,
            provider_id=provider_id,
            version_label=snapshot_version,
            abstract_text=abstract,
            raw_payload=payload,
            metadata_json={"version": version_label, **(metadata or {})},
        )
        self.session.add(source)
        await self.session.flush()
        return source

    async def attach(
        self, project_id: UUID, paper_id: UUID, added_by: str = "retrieval"
    ) -> None:
        await self.session.execute(
            insert(ProjectPaper)
            .values(
                project_id=project_id,
                paper_id=paper_id,
                added_by=added_by,
                version=1,
            )
            .on_conflict_do_nothing()
        )
