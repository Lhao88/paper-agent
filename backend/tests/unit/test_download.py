from io import BytesIO
from pathlib import Path

import httpx
import pytest
from reportlab.pdfgen import canvas

from app.config import Settings
from app.documents.download import PDFDownloader, resolve_storage_key
from app.errors import DomainError


def pdf_bytes() -> bytes:
    stream = BytesIO()
    document = canvas.Canvas(stream)
    document.drawString(50, 750, "Synthetic evidence")
    document.save()
    return stream.getvalue()


async def test_pdf_download_pins_validated_address_and_preserves_tls_hostname(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []
    content = pdf_bytes()

    async def addresses(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, headers={"Content-Type": "application/pdf"}, content=content)

    downloader = PDFDownloader(
        Settings(_env_file=None, storage_root=tmp_path),
        transport=httpx.MockTransport(respond),
        resolver=addresses,
    )
    result = await downloader.download("https://papers.example/paper.pdf")
    assert requests[0].url.host == "93.184.216.34"
    assert requests[0].headers["host"] == "papers.example"
    assert requests[0].extensions["sni_hostname"] == "papers.example"
    assert resolve_storage_key(tmp_path, result.storage_key).read_bytes() == content


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/private",
        "http://169.254.169.254/",
        "file:///private.pdf",
        "http://[::1]/private",
    ],
)
async def test_nonpublic_or_nonhttp_urls_are_blocked_before_network(
    url: str, tmp_path: Path
) -> None:
    def unexpected(request: httpx.Request) -> httpx.Response:
        raise AssertionError("unsafe URLs must not reach a transport")

    downloader = PDFDownloader(
        Settings(_env_file=None, storage_root=tmp_path), transport=httpx.MockTransport(unexpected)
    )
    with pytest.raises(DomainError) as exc:
        await downloader.download(url)
    assert exc.value.code == "UNSAFE_DOWNLOAD_URL"


async def test_redirect_to_private_address_is_revalidated(tmp_path: Path) -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})

    downloader = PDFDownloader(
        Settings(_env_file=None, storage_root=tmp_path), transport=httpx.MockTransport(respond)
    )
    with pytest.raises(DomainError) as exc:
        await downloader.download("https://93.184.216.34/paper.pdf")
    assert exc.value.code == "UNSAFE_DOWNLOAD_URL"
    assert calls == 1


async def test_download_size_limit_and_invalid_pdf_never_produce_complete_files(
    tmp_path: Path,
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/pdf", "Content-Length": str(2 * 1024 * 1024)},
            content=b"%PDF-",
        )

    downloader = PDFDownloader(
        Settings(_env_file=None, storage_root=tmp_path, max_download_mb=1),
        transport=httpx.MockTransport(respond),
    )
    with pytest.raises(DomainError) as exc:
        await downloader.download("https://93.184.216.34/paper.pdf")
    assert exc.value.code == "PDF_SIZE_LIMIT"
    assert list(tmp_path.rglob("*.pdf")) == []
    assert list(tmp_path.rglob("*.part")) == []


def test_storage_key_cannot_escape_the_owned_directory(tmp_path: Path) -> None:
    with pytest.raises(DomainError):
        resolve_storage_key(tmp_path, "../outside.pdf")


@pytest.mark.parametrize(
    "content,mime,code",
    [
        (b"<html>not pdf</html>", "text/html", "PDF_MIME_INVALID"),
        (b"invalid bytes", "application/pdf", "PDF_HEADER_INVALID"),
    ],
)
async def test_html_or_fake_pdf_cannot_enter_the_document_store(
    tmp_path: Path,
    content: bytes,
    mime: str,
    code: str,
) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"Content-Type": mime},
            content=content,
        )
    )
    with pytest.raises(DomainError) as exc:
        await PDFDownloader(
            Settings(_env_file=None, storage_root=tmp_path), transport=transport
        ).download("https://93.184.216.34/paper.pdf")
    assert exc.value.code == code
    assert list(tmp_path.rglob("*.part")) == []
    assert list(tmp_path.rglob("*.pdf")) == []


async def test_streaming_limit_stops_body_even_without_an_accurate_length(tmp_path: Path) -> None:
    class Body(httpx.AsyncByteStream):
        produced = 0

        async def __aiter__(self):
            for block in (b"%PDF-", b"a" * (1024 * 1024), b"unnecessary-body"):
                self.produced += 1
                yield block

    body = Body()
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"Content-Type": "application/pdf"},
            stream=body,
        )
    )
    with pytest.raises(DomainError) as exc:
        await PDFDownloader(
            Settings(_env_file=None, storage_root=tmp_path, max_download_mb=1), transport=transport
        ).download("https://93.184.216.34/paper.pdf")
    assert exc.value.code == "PDF_SIZE_LIMIT"
    assert body.produced == 2
    assert list(tmp_path.rglob("*.part")) == []
