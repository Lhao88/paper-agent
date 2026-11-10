from uuid import UUID

from sqlalchemy import select

from app.db import Project, Run
from app.errors import DomainError
from app.repositories.projects import ProjectRepository
from app.services.base import Services, row_data


async def list_projects(
    services: Services, limit: int = 20, cursor: str | None = None
) -> dict[str, object]:
    if not 1 <= limit <= 100:
        raise DomainError("INVALID_PAGE", "分页参数无效。")
    async with services.factory() as session:
        query = select(Project)
        if cursor:
            try:
                query = query.where(Project.id > UUID(cursor))
            except ValueError as exc:
                raise DomainError("INVALID_PAGE", "项目游标无效。") from exc
        rows = list(await session.scalars(query.order_by(Project.id).limit(limit + 1)))
        return {
            "items": [row_data(row) for row in rows[:limit]],
            "next_cursor": str(rows[limit - 1].id) if len(rows) > limit else None,
        }


async def create_project(services: Services, title: str, topic: str) -> dict[str, object]:
    if not title.strip() or len(title) > 300 or not topic.strip() or len(topic) > 2000:
        raise DomainError("INVALID_PROJECT", "项目标题或主题长度无效。")
    async with services.factory.begin() as session:
        return row_data(await ProjectRepository(session).create(title.strip(), topic.strip()))


async def get_project(services: Services, project_id: UUID) -> dict[str, object]:
    async with services.factory() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise DomainError("PROJECT_NOT_FOUND", "项目不存在。")
        result = row_data(project)
        result["runs"] = [
            row_data(run)
            for run in await session.scalars(
                select(Run)
                .where(Run.project_id == project_id)
                .order_by(Run.created_at.desc())
                .limit(50)
            )
        ]
        return result
