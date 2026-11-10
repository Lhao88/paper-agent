from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, Header, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import select

from app.db import Run, RunEvent, Task
from app.errors import DomainError
from app.review.export import export_markdown
from app.review.models import ReviewDocument
from app.schemas.api import (
    EditInput,
    EvidenceView,
    NotebookView,
    PaperDetailsView,
    PaperPage,
    PlanView,
    ProjectDetails,
    ProjectInput,
    ProjectPage,
    ProjectView,
    ResumeInput,
    RetryInput,
    ReviewListItem,
    ReviewView,
    RunView,
    SelectionInput,
)
from app.services import literature, projects, research, results, uploads
from app.services.base import Services, row_data
from app.workflow.recovery import recover_run


def build_router(services: Services) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.post("/projects", status_code=201, response_model=ProjectView)
    async def create_project(body: ProjectInput) -> dict[str, object]:
        return await projects.create_project(services, body.title, body.topic)

    @router.get("/projects", response_model=ProjectPage)
    async def list_projects(
        limit: int = Query(20, ge=1, le=100), cursor: str | None = None
    ) -> dict[str, object]:
        return await projects.list_projects(services, limit, cursor)

    @router.get("/projects/{project_id}", response_model=ProjectDetails)
    async def get_project(project_id: UUID) -> dict[str, object]:
        return await projects.get_project(services, project_id)

    @router.post("/projects/{project_id}/runs", status_code=202, response_model=RunView)
    async def start(
        project_id: UUID,
        body: research.StartResearch,
        idempotency_key: str = Header(min_length=1, max_length=200),
    ) -> dict[str, object]:
        return await research.start_research(services, project_id, body, idempotency_key)

    @router.get("/runs/{run_id}", response_model=RunView)
    async def status(run_id: UUID, task_id: UUID | None = None) -> dict[str, object]:
        result = await research.get_status(services, run_id)
        if task_id:
            async with services.factory() as session:
                task = await session.get(Task, task_id)
                if task is None or task.run_id != run_id:
                    raise DomainError("TASK_NOT_FOUND", "任务不存在。")
                result["task"] = row_data(task)
        return result

    @router.get("/runs/{run_id}/plan", response_model=PlanView)
    async def plan(run_id: UUID) -> dict[str, object]:
        return await research.get_plan(services, run_id)

    @router.get("/runs/{run_id}/notebook", response_model=NotebookView)
    async def notebook(run_id: UUID) -> dict[str, object]:
        return await research.get_notebook(services, run_id)

    @router.post("/runs/{run_id}/approve", status_code=202, response_model=RunView)
    async def approve(
        run_id: UUID,
        body: research.ApprovePlan,
        idempotency_key: str = Header(min_length=1, max_length=200),
    ) -> dict[str, object]:
        return await research.approve_plan(services, run_id, body, idempotency_key)

    @router.post("/runs/{run_id}/cancel", status_code=202, response_model=RunView)
    async def cancel(run_id: UUID) -> dict[str, object]:
        return await research.cancel_research(services, run_id)

    @router.post("/runs/{run_id}/resume", status_code=202, response_model=RunView)
    async def resume(run_id: UUID, body: ResumeInput) -> dict[str, object]:
        await recover_run(
            services.factory, run_id, body.expected_claim_token, body.old_worker_stopped
        )
        return await research.get_status(services, run_id)

    @router.post("/runs/{run_id}/retry", status_code=202, response_model=RunView)
    async def retry(run_id: UUID, body: RetryInput) -> dict[str, object]:
        async with services.factory() as session:
            run = await session.get(Run, run_id)
            if run is None or run.version != body.expected_run_version:
                raise DomainError("VERSION_CONFLICT", "运行版本已变化。")
            tasks = list(
                await session.scalars(
                    select(Task).where(Task.run_id == run_id, Task.id.in_(body.task_ids))
                )
            )
            if len(tasks) != len(set(body.task_ids)) or any(
                task.status != "failed" or task.operation != "source_search" for task in tasks
            ):
                raise DomainError("RETRY_UNSAFE", "仅允许明确失败的来源请求按检查点重试。")
            token = run.claim_token
        await recover_run(services.factory, run_id, token, body.old_worker_stopped)
        return await research.get_status(services, run_id)

    @router.get("/runs/{run_id}/events")
    async def events(
        run_id: UUID,
        after_id: str = Query("0", pattern=r"^\d{1,20}$"),
        limit: int = Query(100, ge=1, le=100),
    ) -> dict[str, object]:
        await research.get_status(services, run_id)
        async with services.factory() as session:
            rows = list(
                await session.scalars(
                    select(RunEvent)
                    .where(RunEvent.run_id == run_id, RunEvent.id > int(after_id))
                    .order_by(RunEvent.id)
                    .limit(limit)
                )
            )
            return {
                "items": [{**row_data(row), "id": str(row.id)} for row in rows],
                "next_cursor": str(rows[-1].id) if rows else after_id,
            }

    @router.post("/runs/{run_id}/searches", status_code=202)
    async def search(
        run_id: UUID,
        body: literature.SearchRequest,
        idempotency_key: str = Header(min_length=1, max_length=200),
    ) -> dict[str, object]:
        status = await research.get_status(services, run_id)
        return await literature.submit_search(
            services, UUID(str(status["project_id"])), run_id, body, idempotency_key
        )

    @router.get("/projects/{project_id}/papers", response_model=PaperPage)
    async def papers(
        project_id: UUID, limit: int = Query(20, ge=1, le=100), cursor: str | None = None
    ) -> dict[str, object]:
        return await literature.list_papers(services, project_id, limit, cursor)

    @router.get("/projects/{project_id}/papers/{paper_id}", response_model=PaperDetailsView)
    async def paper(project_id: UUID, paper_id: UUID) -> dict[str, object]:
        return await literature.paper_details(services, project_id, paper_id)

    @router.patch("/projects/{project_id}/papers/{paper_id}")
    async def choose(project_id: UUID, paper_id: UUID, body: SelectionInput) -> dict[str, object]:
        return await literature.update_selection(
            services, project_id, paper_id, body.user_decision, body.expected_version
        )

    @router.post("/projects/{project_id}/documents", status_code=201)
    async def upload(
        project_id: UUID,
        file: Annotated[UploadFile, File()],
        paper_id: Annotated[UUID | None, Form()] = None,
        display_title: Annotated[str, Form(max_length=300)] = "用户上传资料",
    ) -> dict[str, object]:
        async def chunks() -> AsyncIterator[bytes]:
            while block := await file.read(65536):
                yield block

        try:
            return await uploads.upload_pdf(
                services,
                project_id,
                file.filename or "upload.pdf",
                file.content_type or "application/octet-stream",
                chunks(),
                display_title,
                paper_id,
            )
        finally:
            await file.close()

    @router.get("/projects/{project_id}/documents/{document_id}/file")
    async def document(project_id: UUID, document_id: UUID) -> FileResponse:
        path = await uploads.document_file(services, project_id, document_id)
        return FileResponse(path, media_type="application/pdf", filename=f"{document_id}.pdf")

    @router.get("/projects/{project_id}/evidence/{evidence_id}", response_model=EvidenceView)
    async def evidence(project_id: UUID, evidence_id: UUID) -> dict[str, object]:
        return await results.get_evidence(services, project_id, evidence_id)

    @router.get("/projects/{project_id}/reviews", response_model=list[ReviewListItem])
    async def reviews(project_id: UUID) -> list[dict[str, object]]:
        return await results.list_reviews(services, project_id)

    @router.get("/projects/{project_id}/reviews/{artifact_id}", response_model=ReviewView)
    async def review(project_id: UUID, artifact_id: UUID) -> dict[str, object]:
        return await results.get_review(services, project_id, artifact_id)

    @router.post("/projects/{project_id}/reviews/{artifact_id}/edits", status_code=201)
    async def edit(project_id: UUID, artifact_id: UUID, body: EditInput) -> dict[str, object]:
        return await results.edit_review(
            services, project_id, artifact_id, body.base_version, body.edited_blocks
        )

    @router.get("/projects/{project_id}/reviews/{artifact_id}/export")
    async def export(
        project_id: UUID, artifact_id: UUID, format: str = Query("markdown", pattern="^markdown$")
    ) -> Response:
        data = await results.get_review(services, project_id, artifact_id)
        text = export_markdown(ReviewDocument.model_validate(data["review"]))
        return Response(
            text,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="review-{artifact_id}.md"'},
        )

    return router
