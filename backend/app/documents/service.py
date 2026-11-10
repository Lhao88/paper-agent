import asyncio
import hashlib
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import select

from app.agents.context import AgentContext
from app.config import PROJECT_ROOT
from app.db import Document
from app.documents.download import DownloadedFile, PDFDownloader, resolve_storage_key
from app.errors import DomainError
from app.repositories.locking import lock_operation
from app.schemas.contracts import DocumentResult, PaperRecord, SelectionResult, SourceRecord


def _copy_mock_pdf(source: SourceRecord, context: AgentContext) -> DownloadedFile:
    frozen = source.provider == "frozen" and context.settings.mock_corpus_profile == "frozen"
    filename = source.raw_payload.get("local_pdf_key" if frozen else "fixture_pdf")
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise DomainError("MOCK_PDF_INVALID", "模拟PDF必须来自受控fixture目录。")
    source_root = (
        PROJECT_ROOT / "evals" / "documents"
        if frozen
        else PROJECT_ROOT / "backend" / "fixtures" / "documents"
    )
    path = resolve_storage_key(source_root, filename)
    if not path.is_file():
        raise DomainError("MOCK_PDF_MISSING", "模拟PDF尚未生成。")
    if path.stat().st_size > context.settings.max_download_mb * 1024 * 1024:
        raise DomainError("PDF_SIZE_LIMIT", "模拟PDF超过读取上限。")
    content = path.read_bytes()
    if not content.startswith(b"%PDF-"):
        raise DomainError("PDF_HEADER_INVALID", "模拟PDF文件头无效。")
    digest = hashlib.sha256(content).hexdigest()
    key = f"documents/{digest}.pdf"
    target = resolve_storage_key(context.settings.storage_root, key)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{uuid4()}.part")
    try:
        temporary.write_bytes(content)
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return DownloadedFile(digest, key)


async def download_selected(
    paper: PaperRecord,
    selection: SelectionResult,
    context: AgentContext,
    downloader: PDFDownloader | None = None,
) -> DocumentResult:
    context.check_cancelled()
    if paper.paper_id not in selection.selected_ids:
        raise DomainError("PAPER_NOT_SELECTED", "只有已入选论文允许获取全文。")
    factory = context.require_repositories().factory
    source_ids = {source.source_id for source in paper.sources if source.source_id is not None}
    if paper.source_id is not None:
        source_ids.add(paper.source_id)
    async with factory() as session:
        existing = await session.scalar(
            select(Document)
            .where(
                Document.paper_id == paper.paper_id,
                Document.source_id.in_(source_ids),
                Document.status.in_(("downloaded", "parsed")),
            )
            .order_by(Document.created_at.desc())
            .limit(1)
        )
        if existing is not None:
            path = resolve_storage_key(context.settings.storage_root, existing.storage_key)
            if path.is_file() and await asyncio.to_thread(_file_sha256, path) == existing.sha256:
                return DocumentResult(
                    paper_id=paper.paper_id,
                    document_id=existing.id,
                    storage_key=existing.storage_key,
                    source_id=existing.source_id,
                    status="downloaded",
                )
    warnings: list[str] = []
    candidates = [
        source
        for source in paper.sources
        if source.pdf_url
        or (source.provider == "mock" and "fixture_pdf" in source.raw_payload)
        or (
            source.provider == "frozen"
            and context.settings.mock_corpus_profile == "frozen"
            and "local_pdf_key" in source.raw_payload
        )
    ]
    for source in candidates[:3]:
        context.check_cancelled()
        try:
            if (source.provider == "mock" and context.settings.source_mode == "mock") or (
                source.provider == "frozen" and context.settings.mock_corpus_profile == "frozen"
            ):
                downloaded = await asyncio.to_thread(_copy_mock_pdf, source, context)
            elif source.pdf_url:
                downloaded = await (downloader or PDFDownloader(context.settings)).download(
                    source.pdf_url
                )
            else:
                continue
        except (DomainError, httpx.HTTPError, OSError, TimeoutError) as exc:
            warnings.append(exc.code if isinstance(exc, DomainError) else "PDF_DOWNLOAD_FAILED")
            continue
        source_id = source.source_id or (
            paper.source_id if source.source_key == paper.abstract_source_key else None
        )
        async with factory.begin() as session:
            await lock_operation(
                session, f"document:{paper.paper_id}:{source_id}:{downloaded.sha256}"
            )
            document = await session.scalar(
                select(Document).where(
                    Document.paper_id == paper.paper_id,
                    Document.sha256 == downloaded.sha256,
                    Document.source_id == source_id,
                )
            )
            if document is None:
                document = Document(
                    paper_id=paper.paper_id,
                    source_id=source_id,
                    sha256=downloaded.sha256,
                    storage_key=downloaded.storage_key,
                    license_info={"license": source.license, "source_key": source.source_key},
                )
                session.add(document)
                await session.flush()
            document_id = document.id
        return DocumentResult(
            paper_id=paper.paper_id,
            document_id=document_id,
            storage_key=downloaded.storage_key,
            source_id=source_id,
            status="downloaded",
            warnings=warnings,
        )
    return DocumentResult(
        paper_id=paper.paper_id,
        status="full_text_unavailable",
        warnings=warnings + ["FULL_TEXT_UNAVAILABLE"],
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(65536):
            digest.update(block)
    return digest.hexdigest()
