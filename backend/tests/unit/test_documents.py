from pathlib import Path
from uuid import uuid4

import pytest
from reportlab.pdfgen import canvas

from app.documents.chunk import chunk_document
from app.documents.parse import parse_pdf, parse_pdf_supervised
from app.errors import DomainError


def make_pdf(path: Path, pages: int = 2) -> None:
    pdf = canvas.Canvas(str(path))
    for page in range(pages):
        pdf.drawString(50, 750, f"Methods on page {page + 1}")
        pdf.drawString(50, 720, "This synthetic study evaluates graph retrieval on ToyCorpus.")
        pdf.showPage()
    pdf.save()


def test_text_pdf_chunks_keep_real_page_numbers_and_document_identity(tmp_path: Path) -> None:
    path = tmp_path / "original.pdf"
    make_pdf(path)
    document_id = uuid4()
    parsed = parse_pdf(path, document_id)
    chunks = chunk_document(parsed)
    assert {chunk.page_number for chunk in chunks} == {1, 2}
    assert {chunk.document_id for chunk in chunks} == {document_id}
    assert all("ToyCorpus" in chunk.text for chunk in chunks)
    assert chunks[0].words


def test_page_cap_stops_parsing_instead_of_silently_reading_more(tmp_path: Path) -> None:
    path = tmp_path / "too-many-pages.pdf"
    make_pdf(path, pages=3)
    with pytest.raises(DomainError) as exc:
        parse_pdf(path, uuid4(), max_pages=2)
    assert exc.value.code == "PDF_PAGE_LIMIT"


def test_corrupted_pdf_has_explicit_failure_without_synthetic_text(tmp_path: Path) -> None:
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.7 corrupted")
    with pytest.raises(DomainError) as exc:
        parse_pdf(path, uuid4())
    assert exc.value.code == "PDF_PARSE_FAILED"


def test_empty_text_pdf_reports_no_ocr_instead_of_generating_content(tmp_path: Path) -> None:
    path = tmp_path / "empty.pdf"
    document = canvas.Canvas(str(path))
    document.showPage()
    document.save()
    with pytest.raises(DomainError) as exc:
        parse_pdf(path, uuid4())
    assert exc.value.code == "PDF_NO_TEXT"


def test_parse_timeout_confirms_spawned_child_has_exited(tmp_path: Path) -> None:
    import multiprocessing

    path = tmp_path / "timeout.pdf"
    make_pdf(path)
    before = {child.pid for child in multiprocessing.active_children()}
    with pytest.raises(DomainError) as exc:
        parse_pdf_supervised(path, uuid4(), timeout_seconds=0.001)
    assert exc.value.code == "PDF_PARSE_TIMEOUT"
    assert {child.pid for child in multiprocessing.active_children()} <= before
