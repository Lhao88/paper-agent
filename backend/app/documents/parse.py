import multiprocessing
import time
from pathlib import Path
from typing import Protocol
from uuid import UUID

import pdfplumber
from pydantic import BaseModel

from app.errors import DomainError
from app.schemas.contracts import ParsedDocument, ParsedPage, WordBox


def parse_pdf(path: Path, document_id: UUID, max_pages: int = 120) -> ParsedDocument:
    if max_pages < 1:
        raise ValueError("max_pages must be positive")
    try:
        with pdfplumber.open(path) as pdf:
            if len(pdf.pages) > max_pages:
                raise DomainError("PDF_PAGE_LIMIT", "PDF页数超过本次解析上限。")
            pages = [
                ParsedPage(
                    page_number=page.page_number,
                    text=page.extract_text() or "",
                    words=[
                        WordBox.model_validate(
                            {key: word[key] for key in ("text", "x0", "top", "x1", "bottom")}
                        )
                        for word in page.extract_words()
                    ],
                )
                for page in pdf.pages
            ]
        if not any(page.text.strip() for page in pages):
            raise DomainError("PDF_NO_TEXT", "PDF没有可用文字层，首版不自动OCR。")
        warnings = ["READING_ORDER_NOT_VERIFIED"]
        if any(not page.text.strip() for page in pages):
            warnings.append("PDF_CONTAINS_EMPTY_PAGES")
        return ParsedDocument(
            document_id=document_id,
            parser_version=f"pdfplumber-{pdfplumber.__version__}",
            pages=pages,
            warnings=warnings,
        )
    except DomainError:
        raise
    except Exception as exc:
        raise DomainError("PDF_PARSE_FAILED", "PDF解析失败，保留已有资料。") from exc


class Sender(Protocol):
    def send(self, value: object) -> None: ...
    def close(self) -> None: ...


class ParseFailure(BaseModel):
    code: str
    message: str


class ParseOutcome(BaseModel):
    result: ParsedDocument | None = None
    error: ParseFailure | None = None


def _parse_child(path: str, document_id: str, max_pages: int, sender: Sender) -> None:
    try:
        sender.send(
            {"result": parse_pdf(Path(path), UUID(document_id), max_pages).model_dump(mode="json")}
        )
    except DomainError as exc:
        sender.send({"error": {"code": exc.code, "message": exc.message}})
    finally:
        sender.close()


def parse_pdf_supervised(
    path: Path,
    document_id: UUID,
    max_pages: int = 120,
    timeout_seconds: float = 60,
) -> ParsedDocument:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_parse_child, args=(str(path), str(document_id), max_pages, sender)
    )
    process.start()
    sender.close()
    deadline = time.monotonic() + timeout_seconds
    try:
        while time.monotonic() < deadline:
            if receiver.poll(min(0.1, max(0, deadline - time.monotonic()))):
                payload = ParseOutcome.model_validate(receiver.recv())
                process.join(timeout=2)
                if payload.error is not None:
                    raise DomainError(payload.error.code, payload.error.message)
                if payload.result is None:
                    raise DomainError("PDF_PARSE_FAILED", "PDF解析进程返回空结果。")
                return payload.result
            if not process.is_alive():
                raise DomainError("PDF_PARSE_FAILED", "PDF解析进程提前退出。")
        raise DomainError("PDF_PARSE_TIMEOUT", "PDF解析超时，已停止对应解析进程。")
    except EOFError as exc:
        raise DomainError("PDF_PARSE_FAILED", "PDF解析进程没有返回有效结果。") from exc
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
            process.join(timeout=2)
        if process.is_alive():
            process.kill()
            process.join(timeout=2)
        if process.is_alive():
            raise DomainError("PDF_PROCESS_NOT_STOPPED", "解析进程尚未确认退出，请检查该任务。")
        process.close()
