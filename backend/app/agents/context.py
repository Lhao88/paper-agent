import asyncio
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.errors import DomainError
from app.llm.budget import BudgetService
from app.llm.gateway import ModelGateway


@dataclass(frozen=True)
class RepositoryAccess:
    factory: async_sessionmaker[AsyncSession]


@dataclass(frozen=True)
class AgentContext:
    run_id: UUID
    plan_id: UUID | None
    model_gateway: ModelGateway
    budget: BudgetService
    settings: Settings
    repositories: RepositoryAccess | None = None
    cancel_token: asyncio.Event = field(default_factory=asyncio.Event)

    def check_cancelled(self) -> None:
        if self.cancel_token.is_set():
            raise DomainError("RUN_CANCELLED", "研究已请求取消。")

    def require_repositories(self) -> RepositoryAccess:
        if self.repositories is None:
            raise RuntimeError("this operation requires persistent repositories")
        return self.repositories
