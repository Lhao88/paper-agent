import hashlib
from collections.abc import AsyncIterator
from pathlib import Path, PurePath
from uuid import UUID, uuid4

from sqlalchemy import or_, select

from app.db import Document, Paper, PaperSource, Project, ProjectPaper
from app.documents.download import resolve_storage_key
from app.errors import DomainError
from app.services.base import Services, row_data


async def upload_pdf(
    services: Services,
    project_id: UUID,
    filename: str,
    mime: str,
    chunks: AsyncIterator[bytes],
    title: str,
    paper_id: UUID | None,
) -> dict[str, object]:
    if (
        PurePath(filename).name != filename
        or "/" in filename
        or "\\" in filename
        or ":" in filename
        or mime not in {"application/pdf", "application/octet-stream"}
        or not title.strip()
        or len(title) > 300
    ):
        raise DomainError("INVALID_UPLOAD", "文件名称、类型或显示标题无效。")
    async with services.factory() as session:
        if await session.get(Project, project_id) is None:
            raise DomainError("PROJECT_NOT_FOUND", "项目不存在。")
        if paper_id and await session.get(ProjectPaper, (project_id, paper_id)) is None:
            raise DomainError("PAPER_NOT_FOUND", "文献不属于此项目。")
    directory = services.settings.storage_root / "documents"
    directory.mkdir(parents=True, exist_ok=True)
    temp = directory / f"{uuid4()}.part"
    digest, size, header = hashlib.sha256(), 0, b""
    try:
        with temp.open("wb") as output:
            async for block in chunks:
                size += len(block)
                if size > services.settings.max_download_mb * 1024 * 1024:
                    raise DomainError("PDF_SIZE_LIMIT", "上传超过文件大小上限。")
                header = (header + block)[:5]
                digest.update(block)
                output.write(block)
        if header != b"%PDF-":
            raise DomainError("PDF_HEADER_INVALID", "文件不是有效PDF文件头。")
        hexdigest = digest.hexdigest()
        key = f"documents/{hexdigest}.pdf"
        temp.replace(resolve_storage_key(services.settings.storage_root, key))
    finally:
        if temp.exists():
            temp.unlink()
    async with services.factory.begin() as session:
        if paper_id is None:
            paper = Paper(
                title=title.strip(), normalized_title=title.strip().casefold(), authors_json=[]
            )
            session.add(paper)
            await session.flush()
            paper_id = paper.id
            session.add(ProjectPaper(project_id=project_id, paper_id=paper_id, added_by="upload"))
        source = PaperSource(
            paper_id=paper_id,
            owner_project_id=project_id,
            provider="upload",
            provider_id=str(uuid4()),
            version_label=hexdigest,
            metadata_json={"display_title": title},
            raw_payload={"user_uploaded": True},
        )
        session.add(source)
        await session.flush()
        document = Document(
            paper_id=paper_id,
            source_id=source.id,
            owner_project_id=project_id,
            sha256=hexdigest,
            storage_key=key,
            license_info={"user_uploaded": True},
        )
        session.add(document)
        await session.flush()
        return {**row_data(document), "model_processing": "未发送给模型；明确选择精读后才处理。"}


async def document_file(services: Services, project_id: UUID, document_id: UUID) -> Path:
    async with services.factory() as session:
        document = await session.scalar(
            select(Document)
            .join(ProjectPaper, ProjectPaper.paper_id == Document.paper_id)
            .where(
                Document.id == document_id,
                ProjectPaper.project_id == project_id,
                or_(Document.owner_project_id.is_(None), Document.owner_project_id == project_id),
            )
        )
        if document is None:
            raise DomainError("DOCUMENT_NOT_FOUND", "文档不存在。")
        path = resolve_storage_key(services.settings.storage_root, document.storage_key)
        if not path.is_file():
            raise DomainError("DOCUMENT_NOT_FOUND", "文档文件不可用。")
        return path
