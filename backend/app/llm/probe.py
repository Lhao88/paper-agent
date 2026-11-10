from typing import Literal

from pydantic import BaseModel

from app.config import PROJECT_ROOT, Settings
from app.db import Run
from app.db.session import create_engine, session_factory
from app.errors import DomainError
from app.llm.base import CallContext, Message
from app.llm.budget import BudgetService
from app.llm.gateway import ModelGateway
from app.llm.mock import MockModelTransport
from app.llm.openai_compatible import OpenAICompatibleTransport
from app.repositories.projects import ProjectRepository


class ProbeOutput(BaseModel):
    ok: bool
    message_zh: str


async def probe_model(
    settings: Settings, profile: Literal["screen", "research"]
) -> dict[str, object]:
    engine = create_engine(settings)
    factory = session_factory(engine)
    try:
        async with factory.begin() as session:
            repo = ProjectRepository(session)
            project = await repo.create("模型连通性检查", "diagnostic probe")
            run = await repo.create_run(
                project.id,
                "probe",
                "probe",
                {},
                {
                    "diagnostic": True,
                    "mode": settings.llm_mode,
                    "profile": profile,
                },
            )
            run.max_calls = settings.max_model_retries + 1
            run.max_tokens = min(settings.max_estimated_total_tokens, 20000)
            run_id = run.id
        transport = (
            MockModelTransport(PROJECT_ROOT / "backend" / "fixtures" / "model")
            if settings.llm_mode == "mock"
            else OpenAICompatibleTransport(settings)
        )
        gateway = ModelGateway(BudgetService(factory), transport, settings)
        try:
            result = await gateway.generate(
                ProbeOutput,
                [Message("user", "请返回ok=true，并用一句中文说明连通性检查成功。")],
                profile,
                CallContext(run_id, "probe"),
            )
        except DomainError as exc:
            async with factory.begin() as session:
                saved_run = await session.get(Run, run_id)
                if saved_run is not None:
                    saved_run.status = (
                        "interrupted" if exc.code == "MODEL_TIMEOUT_UNKNOWN" else "failed"
                    )
                    saved_run.error_json = {"code": exc.code, "message": exc.message}
            raise
        async with factory.begin() as session:
            saved_run = await session.get(Run, run_id)
            if saved_run is not None:
                saved_run.status = "completed"
        return {
            "run_id": str(run_id),
            "mode": settings.llm_mode,
            "result": result.parsed.model_dump(),
            "tokens": result.total_tokens,
        }
    finally:
        await engine.dispose()
