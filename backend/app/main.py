from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.router import build_router
from app.config import Settings, get_settings
from app.db.session import create_engine, session_factory
from app.errors import DomainError
from app.mcp_gateway.server import build_mcp_server
from app.services.base import Services


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()
    engine = create_engine(config)
    services = Services(config, session_factory(engine))
    mcp_server = build_mcp_server(services, config) if config.mcp_enabled else None
    mcp_app = (
        mcp_server.streamable_http_app(
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=config.mcp_allowed_hosts,
                allowed_origins=config.mcp_allowed_origins,
            )
        )
        if mcp_server
        else None
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        for directory in ("documents", "parsed", "exports"):
            (config.storage_root / directory).mkdir(parents=True, exist_ok=True)
        application.state.settings = config
        application.state.engine = engine
        try:
            async with AsyncExitStack() as stack:
                if mcp_server:
                    await stack.enter_async_context(mcp_server.session_manager.run())
                yield
        finally:
            await engine.dispose()

    app = FastAPI(title="Academic Research Workbench", version="0.1.0", lifespan=lifespan)
    app.include_router(build_router(services))

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, error: DomainError) -> JSONResponse:
        code = (
            404
            if error.code.endswith("NOT_FOUND") or error.code.endswith("FORBIDDEN")
            else 413
            if error.code == "PDF_SIZE_LIMIT"
            else 422
            if error.code.startswith("INVALID_")
            or error.code in {"PDF_HEADER_INVALID", "INVALID_UPLOAD"}
            else 409
        )
        return JSONResponse(
            {
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "retryable": error.retryable,
                    "details": error.details,
                    "request_id": str(uuid4()),
                }
            },
            status_code=code,
        )

    @app.get("/api/health/live", tags=["health"])
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/health/ready", tags=["health"])
    async def readiness() -> JSONResponse:
        database = "ok"
        storage = "ok"
        try:
            async with engine.connect() as connection:
                await connection.execute(text("select 1"))
        except (SQLAlchemyError, OSError):
            database = "unavailable"
        probe = config.storage_root / f".ready-{uuid4()}"
        try:
            probe.write_text("probe", encoding="utf-8")
            probe.unlink()
        except OSError:
            storage = "unavailable"
        ready = database == "ok" and storage == "ok"
        return JSONResponse(
            {"status": "ok" if ready else "unavailable", "database": database, "storage": storage},
            status_code=200 if ready else 503,
        )

    if mcp_app:
        app.mount("/", mcp_app)
    return app


app = create_app()
