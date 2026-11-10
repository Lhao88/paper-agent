import asyncio
from contextlib import suppress
from time import monotonic

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.context import AgentContext, RepositoryAccess
from app.config import PROJECT_ROOT, Settings
from app.db import ModelCall, Run
from app.errors import DomainError
from app.llm.budget import BudgetService
from app.llm.gateway import ModelGateway
from app.llm.mock import MockModelTransport
from app.llm.openai_compatible import OpenAICompatibleTransport
from app.worker.claim import RunLease, heartbeat, lock_owned, release_run
from app.worker.fencing import fenced_factory
from app.workflow.graph import build_coverage_graph, build_graph
from app.workflow.nodes import WorkflowNodes
from app.workflow.state import ResearchState, initial_state


async def execute_run(
    engine: AsyncEngine,
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    saver: BaseCheckpointSaver,
    lease: RunLease,
) -> str:
    async with factory() as session:
        run = await lock_owned(session, lease)
        snapshot, inputs, elapsed = (
            run.config_snapshot,
            run.input_snapshot,
            run.active_elapsed_seconds,
        )
        unresolved = await session.scalar(
            select(ModelCall.id)
            .where(
                ModelCall.run_id == run.id, ModelCall.status.in_(["sent", "unknown", "reserved"])
            )
            .limit(1)
        )
    if unresolved:
        await release_run(factory, lease, "interrupted", {"code": "UNRESOLVED_MODEL_CALLS"})
        return "interrupted"
    # Only explicitly frozen non-secret settings may override current credentials/environment.
    allowed = {key for key in Settings.model_fields if key.startswith("max_")} | {
        "llm_mode",
        "mock_corpus_profile",
        "frozen_corpus_path",
        "research_strategy",
        "source_mode",
        "llm_screen_model",
        "llm_research_model",
        "enable_arxiv",
        "planner_mode",
        "embedding_mode",
        "enable_semantic_scholar",
        "read_concurrency",
        "llm_output_mode",
        "chunk_target_tokens",
        "chunks_per_extraction_call",
    }
    frozen = Settings.model_validate(
        {
            **settings.model_dump(),
            **{key: value for key, value in snapshot.items() if key in allowed},
        }
    )
    if frozen.research_strategy == "B0":
        frozen = frozen.model_copy(update={"read_concurrency": 1})
    business_factory = fenced_factory(engine, lease)
    budget = BudgetService(business_factory)
    transport = (
        MockModelTransport(PROJECT_ROOT / "backend" / "fixtures" / "model")
        if frozen.llm_mode == "mock"
        else OpenAICompatibleTransport(frozen)
    )
    context = AgentContext(
        lease.run_id,
        None,
        ModelGateway(budget, transport, frozen),
        budget,
        frozen,
        RepositoryAccess(business_factory),
    )
    nodes = WorkflowNodes(context, factory, lease)
    graph = (
        build_coverage_graph(nodes, saver)
        if frozen.planner_mode == "coverage"
        else build_graph(nodes, saver)
    )
    config: RunnableConfig = {"configurable": {"thread_id": str(lease.run_id)}}
    checkpoint = await saver.aget_tuple(config)
    previous = await graph.aget_state(config) if checkpoint else None
    if previous and not previous.next and previous.values.get("review_artifact_id"):
        await release_run(factory, lease, "completed", None)
        return "completed"
    graph_input: ResearchState | Command | None = (
        initial_state(str(lease.run_id)) if checkpoint is None else None
    )
    if previous and any(task.interrupts for task in previous.tasks):
        resume = inputs.get("resume_payload")
        if not isinstance(resume, dict):
            await release_run(factory, lease, "waiting_user", None)
            return "waiting_user"
        graph_input = Command(resume=resume)
    started = last_beat = monotonic()
    task = asyncio.create_task(graph.ainvoke(graph_input, config, durability="sync"))
    status = "interrupted"
    error: dict[str, object] | None = None
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=0.5)
            now = monotonic()
            async with factory() as session:
                current = await session.get(Run, lease.run_id)
                if current is None or current.claim_token != lease.claim_token:
                    raise DomainError("CLAIM_LOST", "执行归属已改变。")
                cancelled = current.cancel_requested_at is not None
            if cancelled:
                raise DomainError("RUN_CANCELLED", "用户已取消，保留已完成结果。")
            if elapsed + now - started >= frozen.max_research_seconds:
                raise DomainError("TIME_BUDGET_EXHAUSTED", "累计研究时间预算耗尽。")
            if now - last_beat >= 10:
                await heartbeat(factory, lease, now - last_beat)
                last_beat = now
        await task
        final = await graph.aget_state(config)
        if final.next:
            status = (
                "waiting_user" if any(item.interrupts for item in final.tasks) else "interrupted"
            )
        else:
            status = "completed" if final.values.get("review_artifact_id") else "partial"
            async with factory() as session:
                unknown = await session.scalar(
                    select(ModelCall.id)
                    .where(ModelCall.run_id == lease.run_id, ModelCall.status == "unknown")
                    .limit(1)
                )
            if unknown:
                status, error = (
                    "partial",
                    {
                        "code": "MODEL_TIMEOUT_UNKNOWN",
                        "message": "已有成果，但部分调用状态未知，请核对用量。",
                    },
                )
    except DomainError as exc:
        error = {"code": exc.code, "message": exc.message}
        status = (
            "cancelled"
            if exc.code == "RUN_CANCELLED"
            else "interrupted"
            if exc.code in {"MODEL_TIMEOUT_UNKNOWN", "UNRESOLVED_MODEL_CALLS", "CLAIM_LOST"}
            else "partial"
        )
    except asyncio.CancelledError:
        error = {"code": "WORKER_STOPPED", "message": "worker停止，恢复前确认进程已退出。"}
        status = "interrupted"
    except Exception as exc:
        error = {"code": "WORKFLOW_FAILED", "error_type": type(exc).__name__}
        status = "failed"
    finally:
        if not task.done():
            context.cancel_token.set()
            task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await task
    try:
        await release_run(factory, lease, status, error, monotonic() - last_beat)
    except DomainError as exc:
        if exc.code != "CLAIM_LOST":
            raise
    return status
