from uuid import UUID

from sqlalchemy import select

from app.agents.context import AgentContext
from app.db import Artifact, Chunk, Document, Evidence, Paper, PaperSource, ProjectPaper, Run
from app.errors import DomainError
from app.review.models import EvidenceBundle, Reference
from app.schemas.contracts import EvidenceRecord, ReadingCard


async def load_evidence_bundle(artifact_ids: list[UUID], context: AgentContext) -> EvidenceBundle:
    async with context.require_repositories().factory() as session:
        run = await session.get(Run, context.run_id)
        if run is None:
            raise DomainError("RUN_NOT_FOUND", "研究不存在。")
        cards = []
        for artifact_id in artifact_ids:
            artifact = await session.get(Artifact, artifact_id)
            if artifact is None or artifact.run_id != run.id or artifact.kind != "reading":
                raise DomainError("EVIDENCE_FORBIDDEN", "阅读成果不属于本次研究。")
            cards.append(ReadingCard.model_validate(artifact.payload_json))
        evidence_ids = {
            identifier
            for card in cards
            for facts in card.fields.values()
            for fact in facts
            for identifier in fact.evidence_ids
        }
        rows = list(await session.scalars(select(Evidence).where(Evidence.id.in_(evidence_ids))))
        if len(rows) != len(evidence_ids):
            raise DomainError("EVIDENCE_INVALID", "阅读成果中的证据不存在。")
        by_paper = {card.paper_id: card for card in cards}
        evidence = []
        for row in rows:
            card = by_paper.get(row.paper_id)
            membership = await session.get(ProjectPaper, (run.project_id, row.paper_id))
            if card is None or membership is None:
                raise DomainError("EVIDENCE_FORBIDDEN", "证据文献不属于项目资料。")
            if row.basis == "full_text":
                chunk = await session.get(Chunk, row.chunk_id)
                document = await session.get(Document, row.document_id)
                if (
                    document is None
                    or chunk is None
                    or document.paper_id != row.paper_id
                    or document.owner_project_id not in {None, run.project_id}
                    or chunk.document_id != row.document_id
                    or card.document_id != row.document_id
                    or row.chunk_id not in card.examined_chunk_ids
                    or chunk.page_number != row.page_number
                ):
                    raise DomainError("EVIDENCE_VERSION_CONFLICT", "证据与本次精读文档版本不一致。")
                text = chunk.text
            else:
                source = await session.get(PaperSource, row.source_id)
                if (
                    source is None
                    or source.paper_id != row.paper_id
                    or source.owner_project_id not in {None, run.project_id}
                ):
                    raise DomainError("EVIDENCE_VERSION_CONFLICT", "摘要来源与文献不一致。")
                text = source.abstract_text or ""
            if text[row.quote_start : row.quote_end] != row.quote:
                raise DomainError("EVIDENCE_INVALID", "原文证据定位不匹配。")
            evidence.append(
                EvidenceRecord(
                    evidence_id=row.id,
                    paper_id=row.paper_id,
                    basis=row.basis,
                    source_id=row.source_id,
                    document_id=row.document_id,
                    chunk_id=row.chunk_id,
                    quote=row.quote,
                    quote_start=row.quote_start,
                    quote_end=row.quote_end,
                    page_number=row.page_number,
                    statement_type=row.statement_type,
                )
            )
        references = []
        for paper_id in sorted(by_paper, key=str):
            paper = await session.get(Paper, paper_id)
            if paper is None:
                raise DomainError("PAPER_NOT_FOUND", "阅读文献不存在。")
            sources = list(
                await session.scalars(select(PaperSource).where(PaperSource.paper_id == paper_id))
            )
            urls = list(
                dict.fromkeys(
                    str(source.metadata_json["landing_url"])
                    for source in sources
                    if source.metadata_json.get("landing_url")
                )
            )
            references.append(
                Reference(
                    paper_id=paper_id,
                    title=paper.title,
                    authors=paper.authors_json,
                    year=paper.year,
                    doi=paper.canonical_doi,
                    source_urls=urls,
                )
            )
    return EvidenceBundle(
        evidence=sorted(evidence, key=lambda item: str(item.evidence_id)),
        references=references,
        cards=cards,
    )
