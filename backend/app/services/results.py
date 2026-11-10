from uuid import UUID

from sqlalchemy import select

from app.db import Artifact, Chunk, Claim, Document, Evidence, PaperSource, Run
from app.errors import DomainError
from app.repositories.artifacts import ArtifactRepository
from app.review.models import ReviewDocument
from app.review.validate import validate_review
from app.schemas.contracts import ReadingCard
from app.services.base import Services, hash_input, row_data


async def list_reviews(services: Services, project_id: UUID) -> list[dict[str, object]]:
    async with services.factory() as session:
        rows = await session.scalars(
            select(Artifact)
            .join(Run, Run.id == Artifact.run_id)
            .where(Run.project_id == project_id, Artifact.kind.in_(["review", "review_edit"]))
            .order_by(Artifact.created_at.desc())
            .limit(100)
        )
        return [
            {
                "id": str(row.id),
                "version": row.version,
                "origin": row.kind,
                "created_at": row.created_at.isoformat(),
                "supersedes_id": str(row.supersedes_id) if row.supersedes_id else None,
            }
            for row in rows
        ]


async def get_review(services: Services, project_id: UUID, artifact_id: UUID) -> dict[str, object]:
    async with services.factory() as session:
        row = await session.scalar(
            select(Artifact)
            .join(Run, Run.id == Artifact.run_id)
            .where(
                Run.project_id == project_id,
                Artifact.id == artifact_id,
                Artifact.kind.in_(["review", "review_edit", "review_draft"]),
            )
        )
        if row is None:
            raise DomainError("ARTIFACT_NOT_FOUND", "综述版本不存在。")
        review = ReviewDocument.model_validate(row.payload_json)
        return {
            "id": str(row.id),
            "version": row.version,
            "origin": row.kind,
            "review": review.model_dump(mode="json"),
            "validation": validate_review(review).model_dump(mode="json"),
        }


async def get_evidence(
    services: Services, project_id: UUID, evidence_id: UUID
) -> dict[str, object]:
    async with services.factory() as session:
        row = await session.get(Evidence, evidence_id)
        if row is None:
            raise DomainError("EVIDENCE_NOT_FOUND", "证据不存在。")
        cards = await session.scalars(
            select(Artifact)
            .join(Run, Run.id == Artifact.run_id)
            .where(
                Run.project_id == project_id,
                Artifact.kind == "reading",
                Artifact.paper_id == row.paper_id,
            )
        )
        permitted = False
        scope = "unknown"
        for artifact in cards:
            card = ReadingCard.model_validate(artifact.payload_json)
            if any(
                evidence_id in fact.evidence_ids for facts in card.fields.values() for fact in facts
            ):
                permitted, scope = True, card.reading_scope
                break
        if not permitted:
            raise DomainError("EVIDENCE_NOT_FOUND", "证据不存在。")
        text = None
        if row.basis == "full_text":
            doc, chunk = (
                await session.get(Document, row.document_id),
                await session.get(Chunk, row.chunk_id),
            )
            if (
                doc
                and chunk
                and doc.owner_project_id in {None, project_id}
                and doc.paper_id == row.paper_id
                and chunk.document_id == doc.id
            ):
                text = chunk.text
        else:
            source = await session.get(PaperSource, row.source_id)
            if (
                source
                and source.owner_project_id in {None, project_id}
                and source.paper_id == row.paper_id
            ):
                text = source.abstract_text
        if text is None or text[row.quote_start : row.quote_end] != row.quote:
            raise DomainError("EVIDENCE_NOT_FOUND", "证据不存在或版本不匹配。")
        claims = list(
            await session.scalars(
                select(Claim).where(
                    Claim.project_id == project_id, Claim.evidence_id == evidence_id
                )
            )
        )
        public = row_data(row)
        public.pop("id")
        public.pop("created_at")
        return {
            **public,
            "evidence_id": str(row.id),
            "reading_scope": scope,
            "human_verified": False,
            "claims": [
                {
                    "polarity": claim.polarity,
                    "question_id": claim.question_id,
                    "column_id": claim.column_id,
                    "value_zh": claim.value_zh,
                }
                for claim in claims
            ],
        }


async def edit_review(
    services: Services,
    project_id: UUID,
    artifact_id: UUID,
    expected_version: int,
    edits: dict[UUID, str],
) -> dict[str, object]:
    async with services.factory.begin() as session:
        base = await session.scalar(
            select(Artifact)
            .join(Run, Run.id == Artifact.run_id)
            .where(Run.project_id == project_id, Artifact.id == artifact_id)
            .with_for_update(of=Artifact)
        )
        if base is None or base.kind not in {"review", "review_edit"}:
            raise DomainError("ARTIFACT_NOT_FOUND", "综述不存在。")
        child = await session.scalar(
            select(Artifact).where(Artifact.supersedes_id == artifact_id).limit(1)
        )
        if base.version != expected_version or child:
            raise DomainError("VERSION_CONFLICT", "此版本已有后续编辑，请读取最新版本。")
        review = ReviewDocument.model_validate(base.payload_json)
        blocks = {block.block_id: block for section in review.sections for block in section.blocks}
        if (
            not edits
            or not set(edits) <= blocks.keys()
            or any(not text.strip() or len(text) > 20000 for text in edits.values())
        ):
            raise DomainError("INVALID_EDIT", "编辑段落标识或内容无效。")
        for identifier, text in edits.items():
            blocks[identifier].text = text
        review.limitations.append(
            "用户编辑版本：引用仅保留原关联，修改后的语义支持需要重新人工核验。"
        )
        digest = hash_input(
            {"base": str(base.id), "edits": {str(key): value for key, value in edits.items()}}
        )
        saved = await ArtifactRepository(session).get_or_create(
            base.run_id, f"edit:{digest}", "review_edit", review.model_dump(mode="json"), digest
        )
        saved.version, saved.supersedes_id = base.version + 1, base.id
        return {"id": str(saved.id), "version": saved.version, "origin": saved.kind}
