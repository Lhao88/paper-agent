from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.workflow.coverage_flow import (
    approve_spec,
    begin_round,
    draft_spec,
    execute,
    note,
    propose,
    read_selected,
    screen_new,
)
from app.workflow.nodes import WorkflowNodes
from app.workflow.state import ResearchState


def route_after_note(state: ResearchState) -> str:
    return "write" if state["stop_reason"] else "begin_round"


def build_graph(services: WorkflowNodes, checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    graph = StateGraph(ResearchState)
    names = [
        "plan",
        "approve_plan",
        "retrieve",
        "screen",
        "select",
        "read",
        "analyze",
        "decide",
        "write",
        "validate",
        "finalize",
    ]
    for name in names:
        graph.add_node(name, getattr(services, name))
    graph.add_edge(START, "plan")
    for left, right in zip(names, names[1:], strict=False):
        if left != "decide":
            graph.add_edge(left, right)
    graph.add_conditional_edges(
        "decide",
        lambda state: state["next_action"],
        {"retrieve": "retrieve", "read": "read", "write": "write"},
    )
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)


def build_coverage_graph(
    services: WorkflowNodes, checkpointer: BaseCheckpointSaver
) -> CompiledStateGraph:
    graph = StateGraph(ResearchState)

    async def _draft(state: ResearchState) -> dict[str, object]:
        return await draft_spec(services, state)

    async def _approve(state: ResearchState) -> dict[str, object]:
        return await approve_spec(services, state)

    async def _begin(state: ResearchState) -> dict[str, object]:
        return await begin_round(services, state)

    async def _propose(state: ResearchState) -> dict[str, object]:
        return await propose(services, state)

    async def _execute(state: ResearchState) -> dict[str, object]:
        return await execute(services, state)

    async def _screen(state: ResearchState) -> dict[str, object]:
        return await screen_new(services, state)

    async def _read(state: ResearchState) -> dict[str, object]:
        return await read_selected(services, state)

    async def _note(state: ResearchState) -> dict[str, object]:
        return await note(services, state)

    graph.add_node("draft_spec", _draft)
    graph.add_node("approve_spec", _approve)
    graph.add_node("begin_round", _begin)
    graph.add_node("propose", _propose)
    graph.add_node("execute", _execute)
    graph.add_node("screen_new", _screen)
    graph.add_node("read_selected", _read)
    graph.add_node("note", _note)
    graph.add_node("write", services.write)
    graph.add_node("validate", services.validate)
    graph.add_node("finalize", services.finalize)
    graph.add_edge(START, "draft_spec")
    graph.add_edge("draft_spec", "approve_spec")
    graph.add_edge("approve_spec", "begin_round")
    graph.add_edge("begin_round", "propose")
    graph.add_edge("propose", "execute")
    graph.add_edge("execute", "screen_new")
    graph.add_edge("screen_new", "read_selected")
    graph.add_edge("read_selected", "note")
    graph.add_conditional_edges(
        "note",
        route_after_note,
        {"begin_round": "begin_round", "write": "write"},
    )
    graph.add_edge("write", "validate")
    graph.add_edge("validate", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)
