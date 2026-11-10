import hashlib
from uuid import UUID

import httpx
from langgraph.types import interrupt
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.context import AgentContext
from app.agents.coordinator import CoordinatorAgent
from app.agents.prompts import json_text, prompt_messages
from app.agents.retrieval import RetrievalAgent
from app.agents.review import ReviewAgent
from app.db import Artifact, Project, RunEvent
from app.db import ResearchPlan as PlanRow
from app.documents.reading_service import ReadingService
from app.errors import DomainError
from app.llm.base import CallContext
from app.repositories.artifacts import ArtifactRepository
from app.review.models import ReviewBundle, SynthesisArtifact
from app.review.repository import load_evidence_bundle
from app.review.service import generate_review
from app.schemas.contracts import (
    FollowupDecision,
    PlanRequest,
    QueryPlan,
    ResearchPlan,
    RetrievalResult,
    SearchQuery,
    SelectionResult,
)
from app.screening.service import ScreeningBundle, screen_and_select
from app.sources.factory import build_sources
from app.worker.claim import RunLease, lock_owned
from app.workflow.literature import drain_search_tasks, manual_materials
from app.workflow.routing import decide_route
from app.workflow.state import ResearchState


class WorkflowNodes:
    def __init__(
        self,
        context: AgentContext,
        control_factory: async_sessionmaker[AsyncSession],
        lease: RunLease,
    ):
        self.context, self.factory, self.lease = context, control_factory, lease

    async def enter(self, stage: str, accept_searches: bool = True) -> None:
        self.context.check_cancelled()
        async with self.factory.begin() as session:
            run = await lock_owned(session, self.lease)
            if run.cancel_requested_at is not None:
                raise DomainError("RUN_CANCELLED", "用户已请求取消。")
            if run.active_elapsed_seconds >= self.context.settings.max_research_seconds:
                raise DomainError("TIME_BUDGET_EXHAUSTED", "累计研究时间达到上限，保留已有资料。")
            run.stage = stage
            run.retrieval_accepting = stage == "retrieve" and accept_searches
            run.version += 1
            session.add(RunEvent(run_id=run.id, event_type="stage", payload_json={"stage": stage}))

    async def save(self, key: str, kind: str, value: BaseModel) -> UUID:
        payload = value.model_dump(mode="json")
        digest = hashlib.sha256(json_text(payload).encode()).hexdigest()
        async with self.context.require_repositories().factory.begin() as session:
            artifact = await ArtifactRepository(session).get_or_create(
                self.context.run_id, key, kind, payload, digest
            )
            return artifact.id

    async def load[T: BaseModel](self, identifier: str | UUID | None, schema: type[T]) -> T:
        if identifier is None:
            raise DomainError("ARTIFACT_NOT_FOUND", "缺少前序成果。")
        async with self.factory() as session:
            artifact = await session.get(Artifact, UUID(str(identifier)))
            if artifact is None or artifact.run_id != self.context.run_id:
                raise DomainError("ARTIFACT_NOT_FOUND", "成果不属于本次研究。")
            return schema.model_validate(artifact.payload_json)

    async def get_plan(self, state: ResearchState) -> ResearchPlan:
        async with self.factory() as session:
            artifact = await session.scalar(
                select(Artifact).where(
                    Artifact.run_id == self.context.run_id,
                    Artifact.operation_key == f"plan:{state['plan_id']}",
                )
            )
            if artifact is None:
                raise DomainError("PLAN_NOT_FOUND", "研究计划未保存。")
            return ResearchPlan.model_validate(artifact.payload_json)

    async def plan(self, state: ResearchState) -> dict[str, object]:
        await self.enter("plan")
        async with self.factory() as session:
            run = await lock_owned(session, self.lease)
            inputs, project_id = run.input_snapshot, run.project_id
            existing = await session.scalar(
                select(Artifact).where(
                    Artifact.run_id == run.id, Artifact.operation_key == "plan:initial"
                )
            )
        if existing:
            return {"plan_id": str(existing.payload_json["plan_id"]), "stage": "approve_plan"}
        draft = await CoordinatorAgent().plan(
            PlanRequest.model_validate(inputs["request"]), self.context
        )
        async with self.context.require_repositories().factory.begin() as session:
            await session.scalar(select(Project).where(Project.id == project_id).with_for_update())
            version = (
                await session.scalar(
                    select(func.max(PlanRow.version)).where(PlanRow.project_id == project_id)
                )
                or 0
            ) + 1
            row = PlanRow(
                project_id=project_id,
                version=version,
                questions_json=[q.model_dump(mode="json") for q in draft.questions],
                scope_json=draft.scope.model_dump(mode="json"),
            )
            session.add(row)
            await session.flush()
            plan = ResearchPlan(
                **draft.model_dump(), plan_id=row.id, project_id=project_id, version=version
            )
            repo = ArtifactRepository(session)
            payload = plan.model_dump(mode="json")
            digest = hashlib.sha256(plan.model_dump_json().encode()).hexdigest()
            await repo.get_or_create(self.context.run_id, f"plan:{row.id}", "plan", payload, digest)
            await repo.get_or_create(self.context.run_id, "plan:initial", "plan", payload, digest)
            run = await lock_owned(session, self.lease)
            run.plan_id = row.id
        return {"plan_id": str(plan.plan_id), "stage": "approve_plan"}

    async def approve_plan(self, state: ResearchState) -> dict[str, object]:
        await self.enter("approve_plan")
        plan = await self.get_plan(state)
        approved = interrupt({"type": "approve_plan", "plan": plan.model_dump(mode="json")})
        if not isinstance(approved, dict) or approved.get("approved") is not True:
            raise DomainError("PLAN_NOT_APPROVED", "需要有效的计划确认。")
        plan_id = UUID(str(approved.get("plan_id", state["plan_id"])))
        async with self.factory() as session:
            run = await lock_owned(session, self.lease)
            row = await session.get(PlanRow, plan_id)
            if (
                row is None
                or row.project_id != run.project_id
                or row.confirmed_at is None
                or run.plan_id != plan_id
            ):
                raise DomainError("PLAN_NOT_APPROVED", "提交的计划版本未由服务确认。")
        return {"plan_id": str(plan_id), "stage": "retrieve"}

    async def retrieve(self, state: ResearchState) -> dict[str, object]:
        key = f"workflow:retrieval:{state['supplement_round']}"
        async with self.factory() as session:
            saved = await session.scalar(
                select(Artifact).where(
                    Artifact.run_id == self.context.run_id, Artifact.operation_key == key
                )
            )
        await self.enter("retrieve", accept_searches=saved is None)
        if saved is not None:
            persisted = RetrievalResult.model_validate(saved.payload_json)
            async with self.factory.begin() as session:
                run = await lock_owned(session, self.lease)
                run.progress_json = {
                    **run.progress_json,
                    "retrieval_warnings": list(dict.fromkeys(persisted.warnings)),
                }
            return {"retrieval_artifact_id": str(saved.id), "stage": "screen"}
        plan = await self.get_plan(state)
        if state["supplement_round"]:
            queries = QueryPlan(
                scope=plan.scope,
                queries=[
                    SearchQuery(
                        query_id=f"supplement-{q.question_id}",
                        question_ids=[q.question_id],
                        provider=plan.scope.enabled_sources[0],
                        terms=" ".join(q.search_terms_en),
                        year_from=plan.scope.year_from,
                        year_to=plan.scope.year_to,
                        languages=plan.scope.languages,
                    )
                    for q in plan.questions
                ],
            )
        else:
            queries = await RetrievalAgent().formulate_queries(plan, self.context)
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            sources = build_sources(self.context.settings, client)
            result = await RetrievalAgent(sources).retrieve(queries, self.context)
            extra = await drain_search_tasks(self.context, self.factory, self.lease, plan, sources)
        uploads, _, _ = await manual_materials(self.context, plan.project_id)
        merged = {paper.paper_id: paper for paper in result.records}
        for extra_result in extra:
            result.warnings.extend(extra_result.warnings)
            for paper in extra_result.records:
                if paper.paper_id in merged or len(merged) < self.context.settings.max_candidates:
                    merged[paper.paper_id] = paper
        for paper in uploads:
            if len(merged) < self.context.settings.max_candidates or paper.paper_id in merged:
                merged[paper.paper_id] = paper
        result.records = list(merged.values())
        if state["retrieval_artifact_id"]:
            previous = await self.load(state["retrieval_artifact_id"], RetrievalResult)
            combined = {paper.paper_id: paper for paper in previous.records}
            for paper in result.records:
                if (
                    paper.paper_id in combined
                    or len(combined) < self.context.settings.max_candidates
                ):
                    combined[paper.paper_id] = paper
            result = RetrievalResult(
                records=list(combined.values()),
                warnings=previous.warnings + result.warnings,
                filtered_out=previous.filtered_out + result.filtered_out,
            )
        artifact_id = await self.save(
            f"workflow:retrieval:{state['supplement_round']}", "retrieval_bundle", result
        )
        async with self.factory.begin() as session:
            run = await lock_owned(session, self.lease)
            run.progress_json = {
                **run.progress_json,
                "retrieval_warnings": list(dict.fromkeys(result.warnings)),
            }
        return {"retrieval_artifact_id": str(artifact_id), "stage": "screen"}

    async def screen(self, state: ResearchState) -> dict[str, object]:
        await self.enter("screen")
        plan = await self.get_plan(state)
        retrieved = await self.load(state["retrieval_artifact_id"], RetrievalResult)
        _, manual_ids, excluded_ids = await manual_materials(self.context, plan.project_id)
        records = [paper for paper in retrieved.records if paper.paper_id not in excluded_ids]
        manual_ids = [
            identifier
            for identifier in manual_ids
            if identifier in {paper.paper_id for paper in records}
        ]
        bundle = await screen_and_select(records, plan, self.context, manual_ids)
        identifier = await self.save(
            f"workflow:screening:{state['supplement_round']}", "screening_bundle", bundle
        )
        stop = next(
            (
                item
                for item in bundle.failures
                if item["code"]
                in {
                    "BUDGET_EXHAUSTED",
                    "MODEL_TIMEOUT_UNKNOWN",
                    "UNRESOLVED_MODEL_CALLS",
                    "RUN_CANCELLED",
                }
            ),
            None,
        )
        if stop:
            raise DomainError(stop["code"], stop["message"])
        return {
            "screening_artifact_id": str(identifier),
            "selection_artifact_id": str(bundle.selection_artifact_id),
            "stage": "select",
        }

    async def select(self, state: ResearchState) -> dict[str, object]:
        await self.enter("select")
        plan = await self.get_plan(state)
        retrieved = await self.load(state["retrieval_artifact_id"], RetrievalResult)
        _, manual_ids, excluded = await manual_materials(self.context, plan.project_id)
        records = [paper for paper in retrieved.records if paper.paper_id not in excluded]
        manual_ids = [
            identifier
            for identifier in manual_ids
            if identifier in {paper.paper_id for paper in records}
        ]
        bundle = await screen_and_select(records, plan, self.context, manual_ids)
        return {"stage": "read", "selection_artifact_id": str(bundle.selection_artifact_id)}

    async def read(self, state: ResearchState) -> dict[str, object]:
        await self.enter("read")
        plan = await self.get_plan(state)
        retrieved = await self.load(state["retrieval_artifact_id"], RetrievalResult)
        selection = await self.load(state["selection_artifact_id"], SelectionResult)
        reading = await ReadingService(self.context).read_selected(
            retrieved.records, selection, plan
        )
        return {"reading_artifact_ids": list(map(str, reading.artifact_ids)), "stage": "analyze"}

    async def analyze(self, state: ResearchState) -> dict[str, object]:
        await self.enter("analyze")
        bundle = await load_evidence_bundle(
            list(map(UUID, state["reading_artifact_ids"])), self.context
        )
        if not bundle.evidence:
            return {"synthesis_artifact_id": None, "stage": "decide"}
        synthesis = await ReviewAgent().analyze(bundle, await self.get_plan(state), self.context)
        identifier = await self.save(
            f"workflow:synthesis:{state['supplement_round']}", "synthesis", synthesis
        )
        return {"synthesis_artifact_id": str(identifier), "stage": "decide"}

    async def decide(self, state: ResearchState) -> dict[str, object]:
        await self.enter("decide")
        if self.context.settings.research_strategy in {"B0", "B1", "A2"}:
            return {"next_action": "write", "stage": "write"}
        if not state["synthesis_artifact_id"]:
            return {"next_action": "write", "stage": "write"}
        plan = await self.get_plan(state)
        synthesis = await self.load(state["synthesis_artifact_id"], SynthesisArtifact)
        decision = await self.context.model_gateway.generate(
            FollowupDecision,
            prompt_messages(
                "coordinator_followup.j2",
                gaps_json=json_text([q.model_dump(mode="json") for q in synthesis.questions]),
                existing_artifacts_json=json_text(state),
                remaining_budget_json=json_text({"supplement_round": state["supplement_round"]}),
            ),
            "research",
            CallContext(self.context.run_id, f"decide:{state['supplement_round']}"),
        )
        suggestion = decision.parsed
        if not set(suggestion.question_ids) <= {q.question_id for q in plan.questions}:
            raise DomainError("FOLLOWUP_INVALID", "补充建议含未知问题。")
        # Reading more is possible only for relevant, previously screened candidates.
        screened = await self.load(state["screening_artifact_id"], ScreeningBundle)
        eligible = {
            card.paper_id
            for card in screened.cards
            if card.relevance is not None and card.relevance >= 3
        }
        selected = await self.load(state["selection_artifact_id"], SelectionResult)
        additional = set(suggestion.paper_ids) & eligible - set(selected.selected_ids)
        room = self.context.settings.max_deep_read_papers - len(selected.selected_ids)
        has_new = (
            bool(additional and room > 0)
            if suggestion.action == "read_more"
            else bool(suggestion.question_ids)
        )
        route = decide_route(
            suggestion.action,
            state["supplement_round"],
            self.context.settings.max_supplement_rounds,
            has_new,
        )
        selection_id: str | None
        if route == "read":
            updated = selected.model_copy(
                update={"selected_ids": selected.selected_ids + sorted(additional, key=str)[:room]}
            )
            identifier = await self.save("workflow:supplement-selection", "selection", updated)
            selection_id = str(identifier)
        else:
            selection_id = state["selection_artifact_id"]
        rounds = state["supplement_round"] + (route in {"read", "retrieve"})
        async with self.factory.begin() as session:
            run = await lock_owned(session, self.lease)
            run.supplement_round = rounds
        return {
            "next_action": route,
            "supplement_round": rounds,
            "selection_artifact_id": selection_id,
            "stage": route,
        }

    async def write(self, state: ResearchState) -> dict[str, object]:
        await self.enter("write")
        bundle = await generate_review(
            list(map(UUID, state["reading_artifact_ids"])), await self.get_plan(state), self.context
        )
        identifier = await self.save("workflow:final-bundle", "review_bundle", bundle)
        return {
            "review_artifact_id": str(bundle.review_artifact_id),
            "review_bundle_artifact_id": str(identifier),
            "revision_round": bundle.validation.revision_round,
            "stage": "validate",
        }

    async def validate(self, state: ResearchState) -> dict[str, object]:
        # No additional model calls here. T07's bounded self-check is already persisted.
        await self.enter("validate")
        await self.load(state["review_bundle_artifact_id"], ReviewBundle)
        return {"stage": "finalize"}

    async def finalize(self, state: ResearchState) -> dict[str, object]:
        await self.enter("finalize")
        async with self.factory.begin() as session:
            run = await lock_owned(session, self.lease)
            run.progress_json = {**run.progress_json, **dict(state)}
            run.revision_round = state["revision_round"]
        return {"stage": "done", "next_action": "finish"}
