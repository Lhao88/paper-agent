from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Project, Run
from app.db.models_projects import ACTIVE_STATUSES
from app.errors import DomainError


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, title: str, topic: str) -> Project:
        project = Project(title=title, topic=topic)
        self.session.add(project)
        await self.session.flush()
        return project

    async def create_run(
        self,
        project_id: UUID,
        idempotency_key: str,
        request_hash: str,
        inputs: dict[str, object],
        config: dict[str, object],
    ) -> Run:
        project = await self.session.scalar(
            select(Project).where(Project.id == project_id).with_for_update()
        )
        if project is None:
            raise DomainError("PROJECT_NOT_FOUND", "项目不存在。")
        existing = await self.session.scalar(
            select(Run).where(Run.project_id == project_id, Run.idempotency_key == idempotency_key)
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise DomainError("IDEMPOTENCY_CONFLICT", "相同幂等键对应不同请求。")
            return existing
        active = await self.session.scalar(
            select(Run).where(Run.project_id == project_id, Run.status.in_(ACTIVE_STATUSES))
        )
        if active is not None:
            raise DomainError(
                "ACTIVE_RUN_EXISTS",
                "该项目已有活动研究。",
                details={
                    "existing_run_id": str(active.id),
                },
            )
        run = Run(
            project_id=project_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            input_snapshot=inputs,
            config_snapshot=config,
            max_calls=config["max_llm_calls"]
            if isinstance(config.get("max_llm_calls"), int)
            else 150,
            max_tokens=config["max_estimated_total_tokens"]
            if isinstance(config.get("max_estimated_total_tokens"), int)
            else 400000,
        )
        self.session.add(run)
        await self.session.flush()
        return run
