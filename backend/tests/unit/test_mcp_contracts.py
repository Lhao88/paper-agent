from unittest.mock import AsyncMock

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from app.config import PROJECT_ROOT, Settings
from app.mcp_gateway.server import build_mcp_server
from app.services.base import Services


async def test_nine_tools_and_shared_contracts():
    server = build_mcp_server(
        Services(Settings(_env_file=None), AsyncMock()), Settings(_env_file=None)
    )
    tools = await server.list_tools()
    names = {tool.name for tool in tools}
    assert names == {
        "list_projects",
        "start_research",
        "get_research_status",
        "approve_research_plan",
        "cancel_research",
        "search_papers",
        "get_paper_details",
        "get_review",
        "get_evidence",
    }
    search = next(tool for tool in tools if tool.name == "search_papers")
    assert "run_id" in search.input_schema["required"]
    assert search.input_schema["properties"]["limit"]["maximum"] == 100
    assert search.input_schema["additionalProperties"] is False
    with pytest.raises(ToolError, match="INVALID_ARGUMENT"):
        await server.call_tool("list_projects", {"unknown": True})


def test_external_acceptance_items_stay_unfinished() -> None:
    text = (PROJECT_ROOT / "docs/implementation/acceptance-status.md").read_text(encoding="utf-8")
    unfinished = text.split("## 尚未通过的外部验收", 1)[1].split("## ", 1)[0]
    for item in (
        "真实供应商",
        "IDE和桌面助手客户端",
        "独立评价集与人工评分尚未准备",
        "PostgreSQL16复现",
        "Docker容器构建",
        "备份恢复演练尚未执行",
    ):
        assert item in unfinished
    verified = text.split("## 已实际验证", 1)[1].split("## ", 1)[0]
    for item in ("PostgreSQL16", "Docker容器构建", "备份恢复演练", "人工评分", "真实供应商"):
        assert item not in verified
