import asyncio
import hashlib
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import httpx

from app.config import Settings
from app.errors import DomainError

AddressResolver = Callable[[str, int], Awaitable[list[str]]]


@dataclass(frozen=True)
class DownloadedFile:
    sha256: str
    storage_key: str


class PDFDownloader:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: AddressResolver | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self.resolver = resolver or resolve_addresses

    async def download(self, url: str) -> DownloadedFile:
        try:
            current = httpx.URL(url)
        except httpx.InvalidURL as exc:
            raise DomainError("UNSAFE_DOWNLOAD_URL", "全文链接格式无效。") from exc
        maximum = self.settings.max_download_mb * 1024 * 1024
        for _ in range(4):
            if current.scheme not in ("http", "https") or not current.host or current.userinfo:
                raise DomainError("UNSAFE_DOWNLOAD_URL", "全文链接协议或身份字段不允许。")
            host = current.raw_host.decode("ascii")
            port = current.port or (443 if current.scheme == "https" else 80)
            try:
                addresses = [str(ipaddress.ip_address(host))]
            except ValueError:
                addresses = await asyncio.wait_for(self.resolver(host, port), timeout=10)
            if not addresses:
                raise DomainError("UNSAFE_DOWNLOAD_URL", "全文链接没有可验证的公网地址。")
            for address in addresses:
                parsed_address = ipaddress.ip_address(address)
                if (
                    not parsed_address.is_global
                    or parsed_address.is_multicast
                    or parsed_address.is_reserved
                    or "%" in address
                ):
                    raise DomainError("UNSAFE_DOWNLOAD_URL", "全文链接不能访问非公网地址。")
            # Connect to the checked IP, preserving Host and TLS hostname. Fresh client per
            # hop prevents pooled connections from crossing original-host/SNI boundaries.
            pinned = current.copy_with(host=addresses[0])
            headers = {
                "Host": current.netloc.decode("ascii"),
                "User-Agent": self.settings.http_user_agent,
            }
            async with httpx.AsyncClient(
                transport=self.transport, trust_env=False, follow_redirects=False, timeout=30
            ) as client:
                async with client.stream(
                    "GET", pinned, headers=headers, extensions={"sni_hostname": host}
                ) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        if not location:
                            raise DomainError("PDF_DOWNLOAD_FAILED", "重定向缺少目标地址。")
                        current = current.join(location)
                        continue
                    if response.status_code != 200:
                        raise DomainError("PDF_DOWNLOAD_FAILED", "公开全文暂时无法取得。")
                    mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                    if mime not in (
                        "",
                        "application/pdf",
                        "application/x-pdf",
                        "application/octet-stream",
                        "binary/octet-stream",
                    ):
                        raise DomainError("PDF_MIME_INVALID", "返回内容不是PDF。")
                    length = response.headers.get("Content-Length", "")
                    if length.isdigit() and int(length) > maximum:
                        raise DomainError("PDF_SIZE_LIMIT", "PDF大小超过配置上限。")
                    temporary = resolve_storage_key(
                        self.settings.storage_root, f"tmp/{uuid4()}.part"
                    )
                    temporary.parent.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256()
                    total = 0
                    prefix = b""
                    try:
                        with temporary.open("xb") as output:
                            async for block in response.aiter_bytes():
                                total += len(block)
                                if total > maximum:
                                    raise DomainError("PDF_SIZE_LIMIT", "PDF流式读取超过配置上限。")
                                prefix = (prefix + block)[:5]
                                if len(prefix) >= 5 and prefix != b"%PDF-":
                                    raise DomainError("PDF_HEADER_INVALID", "PDF文件头无效。")
                                digest.update(block)
                                output.write(block)
                        if prefix != b"%PDF-":
                            raise DomainError("PDF_HEADER_INVALID", "PDF文件头无效。")
                        fingerprint = digest.hexdigest()
                        key = f"documents/{fingerprint}.pdf"
                        destination = resolve_storage_key(self.settings.storage_root, key)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        temporary.replace(destination)
                        return DownloadedFile(fingerprint, key)
                    finally:
                        if temporary.exists():
                            temporary.unlink()
        raise DomainError("PDF_REDIRECT_LIMIT", "全文重定向次数超过上限。")


def resolve_storage_key(root: Path, key: str) -> Path:
    resolved_root = root.resolve()
    path = (resolved_root / key).resolve()
    if (
        Path(key).is_absolute()
        or ":" in key
        or "\x00" in key
        or not path.is_relative_to(resolved_root)
        or path == resolved_root
    ):
        raise DomainError("INVALID_STORAGE_KEY", "资料路径不属于配置的存储目录。")
    return path


async def resolve_addresses(host: str, port: int) -> list[str]:
    try:
        records = await asyncio.to_thread(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise DomainError("PDF_RESOLUTION_FAILED", "全文域名暂时无法解析。") from exc
    addresses: list[str] = []
    for record in records:
        address = record[4][0]
        if isinstance(address, str) and address not in addresses:
            addresses.append(address)
    return addresses
