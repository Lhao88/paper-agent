from unittest.mock import AsyncMock

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from app.config import Settings
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
