from uuid import UUID

from pydantic import Field
from sqlalchemy import or_, select

from app.db import Artifact, Document, Paper, PaperSource, Project, ProjectPaper, Run, Task
from app.errors import DomainError
from app.schemas.contracts import ReadingCard, ResearchPlan, ScreeningCard, StrictModel
from app.services.base import Services, hash_input, row_data, validate_key


class SearchRequest(StrictModel):
    query: str = Field(min_length=1, max_length=1000)
    question_ids: list[str] = Field(min_length=1, max_length=5)
    source: str = "openalex"
    limit: int = Field(default=20, ge=1, le=100)


async def submit_search(
    services: Services, project_id: UUID, run_id: UUID, request: SearchRequest, key: str
) -> dict[str, object]:
    validate_key(key)
    digest = hash_input(request.model_dump())
    async with services.factory.begin() as session:
        run = await session.scalar(
            select(Run).where(Run.id == run_id, Run.project_id == project_id).with_for_update()
        )
        if run is None:
            raise DomainError("RUN_NOT_FOUND", "研究不存在。")
        previous = await session.scalar(
            select(Task).where(
                Task.run_id == run_id,
                Task.operation == "source_search",
                Task.client_request_key == key,
            )
        )
        if previous:
            if previous.input_hash != digest:
                raise DomainError("IDEMPOTENCY_CONFLICT", "相同检索键对应不同输入。")
            return row_data(previous)
        if run.plan_id is None or run.status == "waiting_user":
            raise DomainError("PLAN_NOT_APPROVED", "计划尚未确认。")
        if run.status != "running" or run.stage != "retrieve" or not run.retrieval_accepting:
            raise DomainError("STAGE_CONFLICT", "当前不接受追加检索，请创建后续研究。")
        artifact = await session.scalar(
            select(Artifact).where(
                Artifact.run_id == run_id, Artifact.operation_key == f"plan:{run.plan_id}"
            )
        )
        if artifact is None:
            raise DomainError("PLAN_NOT_APPROVED", "冻结计划不存在。")
        plan = ResearchPlan.model_validate(artifact.payload_json)
        if request.source not in plan.scope.enabled_sources or not set(request.question_ids) <= {
            q.question_id for q in plan.questions
        }:
            raise DomainError("QUERY_PLAN_INVALID", "检索来源或问题不在冻结计划内。")
        task = Task(
            run_id=run_id,
            role="retrieval",
            operation="source_search",
            status="queued",
            client_request_key=key,
            request_hash=digest,
            input_hash=digest,
            input_json=request.model_dump(mode="json"),
        )
        session.add(task)
        await session.flush()
        return row_data(task)


async def paper_details(services: Services, project_id: UUID, paper_id: UUID) -> dict[str, object]:
    async with services.factory() as session:
        member = await session.get(ProjectPaper, (project_id, paper_id))
        paper = await session.get(Paper, paper_id)
        if member is None or paper is None:
            raise DomainError("PAPER_NOT_FOUND", "文献不存在。")
        sources = list(
            await session.scalars(
                select(PaperSource).where(
                    PaperSource.paper_id == paper_id,
                    or_(
                        PaperSource.owner_project_id.is_(None),
                        PaperSource.owner_project_id == project_id,
                    ),
                )
            )
        )
        artifacts = list(
            await session.scalars(
                select(Artifact)
                .join(Run, Run.id == Artifact.run_id)
                .where(Run.project_id == project_id, Artifact.paper_id == paper_id)
                .order_by(Artifact.created_at.desc())
                .limit(50)
            )
        )
        documents = list(
            await session.scalars(
                select(Document).where(
                    Document.paper_id == paper_id,
                    or_(
                        Document.owner_project_id.is_(None), Document.owner_project_id == project_id
                    ),
                )
            )
        )
        return {
            **row_data(paper),
            "selection": row_data(member),
            "sources": [row_data(source) for source in sources],
            "artifacts": [row_data(artifact) for artifact in artifacts],
            "screen_cards": [
                ScreeningCard.model_validate(artifact.payload_json).model_dump(mode="json")
                for artifact in artifacts
                if artifact.kind == "screening"
            ],
            "reading_cards": [
                ReadingCard.model_validate(artifact.payload_json).model_dump(mode="json")
                for artifact in artifacts
                if artifact.kind == "reading"
            ],
            "documents": [row_data(document) for document in documents],
        }


async def list_papers(
    services: Services, project_id: UUID, limit: int = 20, cursor: str | None = None
) -> dict[str, object]:
    if not 1 <= limit <= 100:
        raise DomainError("INVALID_PAGE", "分页大小无效。")
    async with services.factory() as session:
        if await session.get(Project, project_id) is None:
            raise DomainError("PROJECT_NOT_FOUND", "项目不存在。")
        query = (
            select(Paper, ProjectPaper)
            .join(ProjectPaper, ProjectPaper.paper_id == Paper.id)
            .where(ProjectPaper.project_id == project_id)
        )
        if cursor:
            try:
                query = query.where(Paper.id > UUID(cursor))
            except ValueError as exc:
                raise DomainError("INVALID_PAGE", "分页游标无效。") from exc
        rows = list((await session.execute(query.order_by(Paper.id).limit(limit + 1))).all())
        return {
            "items": [
                {**row_data(paper), "selection": row_data(member)} for paper, member in rows[:limit]
            ],
            "next_cursor": str(rows[limit - 1][0].id) if len(rows) > limit else None,
        }


async def update_selection(
    services: Services,
    project_id: UUID,
    paper_id: UUID,
    decision: str | None,
    expected_version: int,
) -> dict[str, object]:
    if decision not in {None, "include", "exclude"}:
        raise DomainError("INVALID_DECISION", "选择仅允许include、exclude或空值。")
    async with services.factory.begin() as session:
        member = await session.scalar(
            select(ProjectPaper)
            .where(ProjectPaper.project_id == project_id, ProjectPaper.paper_id == paper_id)
            .with_for_update()
        )
        if member is None:
            raise DomainError("PAPER_NOT_FOUND", "文献不存在。")
        if member.version != expected_version:
            raise DomainError(
                "VERSION_CONFLICT",
                "人工选择版本已变化。",
                details={"current_version": member.version},
            )
        member.user_decision, member.version = decision, member.version + 1
        return {
            **row_data(member),
            "effect": "进入精读前读取最新选择；已开始的精读不变更，留待后续运行。",
        }
