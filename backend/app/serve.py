import uvicorn

from app.config import get_settings
from app.runtime import run_async


def main() -> None:
    settings = get_settings()
    server = uvicorn.Server(
        uvicorn.Config(
            "app.main:app",
            host=settings.api_host,
            port=settings.api_port,
            log_level=settings.log_level.lower(),
            reload=False,
        )
    )
    run_async(server.serve())


if __name__ == "__main__":
    main()
