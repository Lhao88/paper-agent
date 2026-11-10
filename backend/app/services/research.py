from datetime import UTC, datetime
from uuid import UUID

from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Artifact, ModelCall, Project, Run, RunEvent, Task
from app.db import ResearchPlan as PlanRow
from app.errors import DomainError
from app.planning.spec import allowed_sources_for
from app.repositories.artifacts import ArtifactRepository
from app.repositories.projects import ProjectRepository
from app.schemas.contracts import (
    CoverageReport,
    NotebookPage,
    PlanDraft,
    PlanRequest,
    ResearchPlan,
    ResearchSpec,
    Scope,
    StrictModel,
)
from app.services.base import Services, hash_input, row_data, validate_key


class StartResearch(StrictModel):
    scope: Scope = Field(default_factory=Scope)
    budgets: dict[str, int] = Field(default_factory=dict)


class ApprovePlan(StrictModel):
    expected_version: int = Field(ge=1)
    plan: PlanDraft | None = None
    spec: ResearchSpec | None = None


async def start_research(
    services: Services, project_id: UUID, request: StartResearch, key: str
) -> dict[str, object]:
    validate_key(key)
    digest = hash_input(request.model_dump())
    async with services.factory() as session:
        existing = await session.scalar(
            select(Run).where(Run.project_id == project_id, Run.idempotency_key == key)
        )
        if existing is not None:
            if existing.request_hash != digest:
                raise DomainError("IDEMPOTENCY_CONFLICT", "相同幂等键对应不同请求。")
            return row_data(existing)
    settings = services.settings
    allowed = {key for key in type(settings).model_fields if key.startswith("max_")}
    for field, value in request.budgets.items():
        cap = getattr(settings, field, None)
        if (
            field not in allowed
            or not isinstance(cap, int)
            or value < (0 if "rounds" in field else 1)
            or value > cap
        ):
            raise DomainError("INVALID_BUDGET", "预算必须在服务器配置上限以内。")
    snapshot = {
        key: getattr(settings, key)
        for key in allowed
        | {
            "llm_mode",
            "mock_corpus_profile",
            "research_strategy",
            "source_mode",
            "llm_screen_model",
            "llm_research_model",
            "llm_output_mode",
            "enable_arxiv",
            "planner_mode",
            "embedding_mode",
            "enable_semantic_scholar",
            "read_concurrency",
            "chunk_target_tokens",
            "chunks_per_extraction_call",
        }
    }
    snapshot.update(request.budgets)
    snapshot["frozen_corpus_path"] = (
        str(settings.frozen_corpus_path) if settings.frozen_corpus_path else None
    )
    async with services.factory.begin() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise DomainError("PROJECT_NOT_FOUND", "项目不存在。")
        plan_request = PlanRequest(topic=project.topic, scope=request.scope)
        allowed_sources = allowed_sources_for(settings)
        if (
            not plan_request.scope.enabled_sources
            or not set(plan_request.scope.enabled_sources) <= allowed_sources
        ):
            raise DomainError("SOURCE_NOT_ENABLED", "来源未启用或为空。")
        run = await ProjectRepository(session).create_run(
            project_id,
            key,
            digest,
            {"request": plan_request.model_dump(mode="json")},
            snapshot,
        )
        return row_data(run)


async def get_status(services: Services, run_id: UUID) -> dict[str, object]:
    async with services.factory() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise DomainError("RUN_NOT_FOUND", "研究不存在。")
        result = row_data(run)
        result["unknown_calls"] = await session.scalar(
            select(func.count())
            .select_from(ModelCall)
            .where(ModelCall.run_id == run_id, ModelCall.status == "unknown")
        )
        result["has_worker"] = run.worker_id is not None
        result["counts"] = dict(
            (
                await session.execute(
                    select(Artifact.kind, func.count(func.distinct(Artifact.paper_id)))
                    .where(Artifact.run_id == run_id, Artifact.kind.in_(["screening", "reading"]))
                    .group_by(Artifact.kind)
                )
            ).all()
        )
        result["suspected_interruption"] = run.status == "running" and (
            run.lease_until is None or run.lease_until < datetime.now(UTC)
        )
        result["partial_artifacts"] = [
            row_data(artifact)
            for artifact in await session.scalars(
                select(Artifact)
                .where(Artifact.run_id == run_id)
                .order_by(Artifact.created_at.desc())
                .limit(50)
            )
        ]
        coverage = await _coverage_progress(session, run)
        result["round_index"] = coverage["round_index"]
        result["unmet_question_ids"] = coverage["unmet_question_ids"]
        result["stop_reason"] = coverage["stop_reason"]
        return result


async def get_plan(services: Services, run_id: UUID) -> dict[str, object]:
    async with services.factory() as session:
        run = await session.get(Run, run_id)
        if run is None or run.plan_id is None:
            raise DomainError("PLAN_NOT_FOUND", "研究计划尚未生成。")
        artifact = await session.scalar(
            select(Artifact).where(
                Artifact.run_id == run_id, Artifact.operation_key == f"plan:{run.plan_id}"
            )
        )
        if artifact is None:
            raise DomainError("PLAN_NOT_FOUND", "研究计划尚未保存。")
        row = await session.get(PlanRow, run.plan_id)
        return {
            "run_version": run.version,
            "plan": artifact.payload_json,
            "status": run.status,
            "spec": row.spec_json if row is not None else None,
        }


async def approve_plan(
    services: Services, run_id: UUID, request: ApprovePlan, key: str
) -> dict[str, object]:
    validate_key(key)
    digest = hash_input(request.model_dump(mode="json"))
    async with services.factory.begin() as session:
        run = await session.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if run is None:
            raise DomainError("RUN_NOT_FOUND", "研究不存在。")
        previous = await session.scalar(
            select(Task).where(
                Task.run_id == run_id,
                Task.operation == "approve_plan",
                Task.client_request_key == key,
            )
        )
        if previous:
            if previous.input_hash != digest:
                raise DomainError("IDEMPOTENCY_CONFLICT", "相同幂等键对应不同计划确认。")
            return row_data(run)
        if run.status != "waiting_user" or run.stage != "approve_plan":
            raise DomainError("VERSION_CONFLICT", "计划状态或版本已变化，请刷新。")
        artifact = await session.scalar(
            select(Artifact).where(
                Artifact.run_id == run_id, Artifact.operation_key == f"plan:{run.plan_id}"
            )
        )
        if artifact is None:
            raise DomainError("PLAN_NOT_FOUND", "计划不存在。")
        current = ResearchPlan.model_validate(artifact.payload_json)
        if current.version != request.expected_version:
            raise DomainError(
                "VERSION_CONFLICT",
                "计划版本已变化，请刷新。",
                details={"current_version": current.version},
            )
        row = await session.get(PlanRow, run.plan_id)
        if request.plan is not None or request.spec is not None:
            if request.plan is not None:
                allowed = {"openalex"} | ({"arxiv"} if services.settings.enable_arxiv else set())
                if (
                    request.plan.topic != current.topic
                    or not request.plan.scope.enabled_sources
                    or not set(request.plan.scope.enabled_sources) <= allowed
                ):
                    raise DomainError("PLAN_INVALID", "计划主题或数据来源不满足项目约束。")
            checked = (
                _checked_spec(
                    request.spec, current.topic, allowed_sources_for(services.settings)
                )
                if request.spec is not None
                else None
            )
            await session.scalar(
                select(Project).where(Project.id == run.project_id).with_for_update()
            )
            version = (
                await session.scalar(
                    select(func.max(PlanRow.version)).where(PlanRow.project_id == run.project_id)
                )
                or 0
            ) + 1
            if checked is not None:
                questions, scope = checked.questions, checked.scope
            elif request.plan is not None:
                questions, scope = request.plan.questions, request.plan.scope
            else:
                raise DomainError("PLAN_INVALID", "计划主题或数据来源不满足项目约束。")
            assumptions = (
                request.plan.assumptions if request.plan is not None else current.assumptions
            )
            suggested = (
                request.plan.suggested_budgets
                if request.plan is not None
                else current.suggested_budgets
            )
            row = PlanRow(
                project_id=run.project_id,
                version=version,
                questions_json=[question.model_dump(mode="json") for question in questions],
                scope_json=scope.model_dump(mode="json"),
                spec_json=(
                    checked.model_dump(mode="json")
                    if checked is not None
                    else row.spec_json if row is not None else None
                ),
            )
            session.add(row)
            await session.flush()
            current = ResearchPlan(
                topic=current.topic,
                questions=questions,
                scope=scope,
                assumptions=assumptions,
                suggested_budgets=suggested,
                plan_id=row.id,
                project_id=run.project_id,
                version=version,
                budgets=current.budgets,
            )
            await ArtifactRepository(session).get_or_create(
                run.id,
                f"plan:{row.id}",
                "plan",
                current.model_dump(mode="json"),
                hash_input(current.model_dump(mode="json")),
            )
        if row is None:
            raise DomainError("PLAN_NOT_FOUND", "计划不存在。")
        row.confirmed_at = datetime.now(UTC)
        run.plan_id, run.status, run.available_at = row.id, "queued", datetime.now(UTC)
        run.input_snapshot = {
            **run.input_snapshot,
            "resume_payload": {"approved": True, "plan_id": str(row.id)},
        }
        run.version += 1
        session.add(
            Task(
                run_id=run_id,
                role="user",
                operation="approve_plan",
                status="completed",
                input_hash=digest,
                client_request_key=key,
                input_json=request.model_dump(mode="json"),
            )
        )
        session.add(
            RunEvent(
                run_id=run_id, event_type="plan_approved", payload_json={"plan_id": str(row.id)}
            )
        )
        return row_data(run)


async def get_notebook(services: Services, run_id: UUID) -> dict[str, object]:
    async with services.factory() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise DomainError("RUN_NOT_FOUND", "研究不存在。")
        coverage = await _coverage_progress(session, run)
    return {"pages": coverage["pages"], "unmet_question_ids": coverage["unmet_question_ids"]}


def _checked_spec(spec: ResearchSpec, topic: str, allowed_sources: set[str]) -> ResearchSpec:
    if spec.topic != topic:
        raise DomainError("PLAN_INVALID", "计划主题或数据来源不满足项目约束。")
    if not spec.scope.enabled_sources or not set(spec.scope.enabled_sources) <= allowed_sources:
        raise DomainError("SOURCE_NOT_ENABLED", "来源未启用或为空。")
    question_ids = [question.question_id for question in spec.questions]
    rule_ids = [rule.rule_id for rule in spec.inclusion_rules]
    column_ids = [column.column_id for column in spec.columns]
    if len(question_ids) != len(set(question_ids)):
        raise DomainError("SPEC_INVALID", "研究规格含重复问题编号。")
    if len(rule_ids) != len(set(rule_ids)):
        raise DomainError("SPEC_INVALID", "研究规格含重复纳入规则编号。")
    if len(column_ids) != len(set(column_ids)):
        raise DomainError("SPEC_INVALID", "研究规格含重复抽取列编号。")
    known_questions, known_columns = set(question_ids), set(column_ids)
    for column in spec.columns:
        if column.question_id not in known_questions:
            raise DomainError("SPEC_INVALID", "抽取列指向了不存在的问题。")
    for target in spec.coverage:
        if target.question_id not in known_questions:
            raise DomainError("SPEC_INVALID", "覆盖目标指向了不存在的问题。")
        if any(column_id not in known_columns for column_id in target.required_column_ids):
            raise DomainError("SPEC_INVALID", "覆盖目标指向了不存在的抽取列。")
    return spec


async def _coverage_progress(session: AsyncSession, run: Run) -> dict[str, object]:
    progress = run.progress_json if isinstance(run.progress_json, dict) else {}
    notes = list(
        await session.scalars(
            select(Artifact).where(Artifact.run_id == run.id, Artifact.kind == "notebook")
        )
    )
    coverages = list(
        await session.scalars(
            select(Artifact).where(Artifact.run_id == run.id, Artifact.kind == "coverage")
        )
    )
    note_rounds = [
        index
        for note in notes
        if (index := _plain_int(note.payload_json.get("round_index"))) is not None
    ]
    stored_round = _plain_int(progress.get("round_index"))
    round_index = stored_round if stored_round is not None else max(note_rounds, default=0)
    latest: Artifact | None = None
    latest_index = -1
    for item in coverages:
        index = _plain_int(item.payload_json.get("round_index"))
        if index is not None and index >= latest_index:
            latest, latest_index = item, index
    unmet: list[str] = []
    if latest is not None:
        report = CoverageReport.model_validate(latest.payload_json)
        unmet = list(report.unmet_question_ids)
    stop = progress.get("stop_reason")
    pages = [
        NotebookPage.model_validate(note.payload_json).model_dump(mode="json")
        for note in sorted(
            notes, key=lambda item: _plain_int(item.payload_json.get("round_index")) or 0
        )
    ]
    return {
        "round_index": round_index,
        "unmet_question_ids": unmet,
        "stop_reason": stop if isinstance(stop, str) else "",
        "pages": pages,
    }


def _plain_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


async def cancel_research(services: Services, run_id: UUID) -> dict[str, object]:
    async with services.factory.begin() as session:
        run = await session.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if run is None:
            raise DomainError("RUN_NOT_FOUND", "研究不存在。")
        if run.status in {"queued", "waiting_user", "interrupted", "running"}:
            run.cancel_requested_at = run.cancel_requested_at or datetime.now(UTC)
            if run.status != "running":
                run.status, run.finished_at = "cancelled", datetime.now(UTC)
            run.version += 1
            session.add(
                RunEvent(
                    run_id=run_id,
                    event_type="cancel_requested",
                    payload_json={"status": run.status},
                )
            )
        return row_data(run)
