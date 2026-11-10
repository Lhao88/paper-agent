import asyncio
import hashlib
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.agents.context import AgentContext
from app.agents.reading import ReadingAgent
from app.db import Artifact, Chunk, Document, Evidence
from app.documents.chunk import choose_chunks, chunk_document
from app.documents.download import resolve_storage_key
from app.documents.evidence import evidence_from_quote, validate_evidence
from app.documents.parse import parse_pdf_supervised
from app.documents.service import download_selected
from app.errors import DomainError
from app.repositories.artifacts import ArtifactRepository
from app.schemas.contracts import (
    ChunkRecord,
    DocumentResult,
    EvidenceRecord,
    PaperRecord,
    ReadingCard,
    ReadingFact,
    ResearchPlan,
    SelectionResult,
    WordBox,
)

FACT_FIELDS = (
    "research_question",
    "method",
    "dataset",
    "experimental_setup",
    "metric",
    "result",
    "limitation",
)


class ReadingBundle(BaseModel):
    cards: list[ReadingCard]
    artifact_ids: list[UUID]


async def _save_evidence(record: EvidenceRecord, context: AgentContext) -> EvidenceRecord:
    async with context.require_repositories().factory.begin() as session:
        existing = await session.scalar(
            select(Evidence).where(
                Evidence.paper_id == record.paper_id,
                Evidence.chunk_id == record.chunk_id,
                Evidence.source_id == record.source_id,
                Evidence.document_id == record.document_id,
                Evidence.quote_start == record.quote_start,
                Evidence.quote_end == record.quote_end,
                Evidence.statement_type == record.statement_type,
            )
        )
        if existing is not None:
            return record.model_copy(update={"evidence_id": existing.id})
        session.add(Evidence(id=record.evidence_id, **record.model_dump(exclude={"evidence_id"})))
    return record


async def _abstract_only(
    paper: PaperRecord, warnings: list[str], context: AgentContext
) -> ReadingCard:
    fields: dict[str, list[ReadingFact]] = {}
    if paper.abstract and paper.source_id:
        evidence = await _save_evidence(
            evidence_from_quote(
                paper.abstract,
                paper.abstract,
                paper.paper_id,
                "abstract",
                source_id=paper.source_id,
            ),
            context,
        )
        fields["abstract_background"] = [
            ReadingFact(
                value_zh="仅摘要背景：" + paper.abstract,
                evidence_ids=[evidence.evidence_id],
                statement_type="reported_fact",
            )
        ]
    return ReadingCard(
        paper_id=paper.paper_id,
        reading_scope="abstract_only",
        examined_chunk_ids=[],
        fields=fields,
        missing_fields={field: "full_text_not_examined" for field in FACT_FIELDS},
        warnings=warnings,
    )


class ReadingService:
    def __init__(self, context: AgentContext) -> None:
        self.context = context
        self.parser_gate = asyncio.Semaphore(1)

    async def _chunks(self, document: DocumentResult) -> tuple[list[ChunkRecord], list[str]]:
        context = self.context
        if document.document_id is None or document.storage_key is None:
            raise DomainError("DOCUMENT_NOT_FOUND", "没有可用全文。")
        factory = context.require_repositories().factory
        async with factory() as session:
            stored_document = await session.get(Document, document.document_id)
            stored_chunks = list(
                await session.scalars(
                    select(Chunk)
                    .where(
                        Chunk.document_id == document.document_id,
                    )
                    .order_by(Chunk.page_number, Chunk.created_at, Chunk.id)
                )
            )
            if stored_document and stored_document.status == "parsed" and stored_chunks:
                return [
                    ChunkRecord(
                        chunk_id=chunk.id,
                        document_id=chunk.document_id,
                        page_number=chunk.page_number,
                        text=chunk.text,
                        text_sha256=chunk.text_sha256,
                        section_hint=chunk.section_hint,
                        words=[WordBox.model_validate(word) for word in chunk.word_boxes_json],
                    )
                    for chunk in stored_chunks
                ], list(stored_document.parse_warnings)
        path = resolve_storage_key(context.settings.storage_root, document.storage_key)
        async with self.parser_gate:
            parse_task = asyncio.create_task(
                asyncio.to_thread(
                    parse_pdf_supervised,
                    path,
                    document.document_id,
                    context.settings.max_pdf_pages,
                    context.settings.pdf_parse_timeout_seconds,
                )
            )
            try:
                parsed = await asyncio.shield(parse_task)
            except asyncio.CancelledError:
                # Await the supervisor so cancellation does not leave its child running.
                await parse_task
                raise
        chunks = chunk_document(parsed, context.settings.chunk_target_tokens)
        if not chunks:
            raise DomainError("PDF_NO_TEXT", "没有可供精读的正文片段。")
        async with factory.begin() as session:
            for chunk in chunks:
                await session.execute(
                    insert(Chunk)
                    .values(
                        id=chunk.chunk_id,
                        document_id=chunk.document_id,
                        page_number=chunk.page_number,
                        text=chunk.text,
                        text_sha256=chunk.text_sha256,
                        section_hint=chunk.section_hint,
                        word_boxes_json=[word.model_dump() for word in chunk.words],
                    )
                    .on_conflict_do_nothing()
                )
            stored_document = await session.get(Document, document.document_id)
            if stored_document is not None:
                stored_document.status = "parsed"
                stored_document.page_count = len(parsed.pages)
                stored_document.parser_version = parsed.parser_version
                stored_document.parse_warnings = parsed.warnings
        return chunks, parsed.warnings

    async def read_one(
        self,
        paper: PaperRecord,
        selection: SelectionResult,
        plan: ResearchPlan,
        force: bool = False,
    ) -> tuple[ReadingCard, UUID]:
        context = self.context
        context.check_cancelled()
        if paper.paper_id not in selection.selected_ids:
            raise DomainError("PAPER_NOT_SELECTED", "只有入选论文可以精读。")
        factory = context.require_repositories().factory
        digest = hashlib.sha256(
            (paper.model_dump_json() + plan.model_dump_json()).encode()
        ).hexdigest()
        prefix = f"reading:{plan.plan_id}:{paper.paper_id}:{digest[:16]}:"
        async with factory() as session:
            previous = await session.scalar(
                select(Artifact)
                .where(
                    Artifact.run_id == context.run_id,
                    Artifact.operation_key.startswith(prefix),
                )
                .order_by(Artifact.version.desc())
                .limit(1)
            )
            if previous is not None and not force:
                return ReadingCard.model_validate(previous.payload_json), previous.id
            version = previous.version + 1 if previous is not None else 1
            supersedes = previous.id if previous is not None else None
        document = await download_selected(paper, selection, context)
        warnings = list(document.warnings)
        if any(source.provider == "mock" for source in paper.sources):
            warnings.append("MOCK_SYNTHETIC_CORPUS")
        if document.status == "full_text_unavailable":
            card = await _abstract_only(paper, warnings, context)
        else:
            try:
                chunks, parser_warnings = await self._chunks(document)
                warnings.extend(parser_warnings)
            except DomainError as exc:
                warnings.append(exc.code)
                async with factory.begin() as session:
                    stored = await session.get(Document, document.document_id)
                    if stored is not None:
                        stored.status = "parse_failed"
                card = await _abstract_only(paper, warnings, context)
            else:
                choice = choose_chunks(
                    chunks, plan.questions, context.settings.max_chunks_per_paper, parser_warnings
                )
                chosen_ids = set(choice.chunk_ids)
                chosen = [chunk for chunk in chunks if chunk.chunk_id in chosen_ids]
                by_id = {chunk.chunk_id: chunk for chunk in chunks}
                fields: dict[str, list[ReadingFact]] = {}
                examined: list[UUID] = []
                batch_size = context.settings.chunks_per_extraction_call
                for index in range(0, len(chosen), batch_size):
                    context.check_cancelled()
                    batch = chosen[index : index + batch_size]
                    try:
                        extracted = await ReadingAgent().extract(paper, batch, plan, context)
                    except DomainError as exc:
                        warnings.append(exc.code)
                        continue
                    examined.extend(chunk.chunk_id for chunk in batch)
                    for candidate in extracted.candidates:
                        try:
                            evidence = await _save_evidence(
                                validate_evidence(
                                    candidate,
                                    by_id[candidate.chunk_id],
                                    paper.paper_id,
                                ),
                                context,
                            )
                        except DomainError as exc:
                            warnings.append(exc.code)
                            continue
                        fact = ReadingFact(
                            value_zh=candidate.value_zh,
                            evidence_ids=[evidence.evidence_id],
                            statement_type=candidate.statement_type,
                        )
                        fields.setdefault(candidate.field_name, []).append(fact)
                if not examined:
                    card = await _abstract_only(paper, warnings + ["NO_CHUNKS_ANALYZED"], context)
                else:
                    missing_status = (
                        "not_found_in_examined_text"
                        if len(examined) == len(chosen)
                        else ("not_fully_examined_due_to_failure")
                    )
                    card = ReadingCard(
                        paper_id=paper.paper_id,
                        document_id=document.document_id,
                        reading_scope=choice.reading_scope
                        if len(examined) == len(chunks)
                        else "full_text_targeted",
                        examined_chunk_ids=examined,
                        fields=fields,
                        missing_fields={
                            field: missing_status for field in FACT_FIELDS if field not in fields
                        },
                        warnings=list(dict.fromkeys(warnings)),
                    )
        async with factory.begin() as session:
            saved = await ArtifactRepository(session).get_or_create(
                context.run_id,
                f"{prefix}{version}",
                "reading",
                card.model_dump(mode="json"),
                digest,
            )
            saved.paper_id = paper.paper_id
            saved.version = version
            saved.supersedes_id = supersedes
            artifact_id = saved.id
        return card, artifact_id

    async def read_selected(
        self,
        papers: list[PaperRecord],
        selection: SelectionResult,
        plan: ResearchPlan,
    ) -> ReadingBundle:
        async with self.context.require_repositories().factory() as session:
            already_read = set(
                await session.scalars(
                    select(Artifact.paper_id)
                    .where(
                        Artifact.run_id == self.context.run_id,
                        Artifact.kind == "reading",
                        Artifact.paper_id.is_not(None),
                    )
                    .distinct()
                )
            )
        if (
            len(set(selection.selected_ids) | already_read)
            > self.context.settings.max_deep_read_papers
        ):
            raise DomainError("SELECTION_BUDGET_CONFLICT", "精读数量超过运行上限。")
        by_id = {paper.paper_id: paper for paper in papers}
        if not set(selection.selected_ids) <= by_id.keys():
            raise DomainError("PAPER_NOT_FOUND", "精读名单含未知论文。")
        gate = asyncio.Semaphore(self.context.settings.read_concurrency)

        async def read(identifier: UUID) -> tuple[ReadingCard, UUID]:
            async with gate:
                return await self.read_one(by_id[identifier], selection, plan)

        results = await asyncio.gather(*(read(identifier) for identifier in selection.selected_ids))
        return ReadingBundle(
            cards=[card for card, _ in results], artifact_ids=[key for _, key in results]
        )
