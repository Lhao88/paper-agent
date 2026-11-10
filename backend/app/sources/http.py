import httpx

from app.errors import DomainError


def check_source_response(response: httpx.Response) -> None:
    if response.status_code == 429:
        delay = response.headers.get("Retry-After", "")
        raise DomainError(
            "SOURCE_RATE_LIMITED",
            "论文来源暂时限流。",
            retryable=True,
            details={"retry_after": int(delay) if delay.isdigit() else None},
        )
    if response.status_code >= 400:
        raise DomainError(
            "SOURCE_UNAVAILABLE",
            "论文来源请求失败。",
            retryable=response.status_code >= 500,
            details={"status_code": response.status_code},
        )
