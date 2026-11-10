from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, InputRequiredResult, Tool


class StrictMCPServer(MCPServer):
    """Add the application's unknown-field policy through public SDK entry points."""

    async def list_tools(self) -> list[Tool]:
        return [
            tool.model_copy(
                update={"input_schema": {**tool.input_schema, "additionalProperties": False}}
            )
            for tool in await super().list_tools()
        ]

    async def call_tool(
        self, name: str, arguments: dict[str, object], context: Context | None = None
    ) -> CallToolResult | InputRequiredResult:
        tool = next((item for item in await self.list_tools() if item.name == name), None)
        if tool is not None and set(arguments) - set(tool.input_schema.get("properties", {})):
            raise ToolError("INVALID_ARGUMENT: 工具输入包含未定义字段。")
        return await super().call_tool(name, arguments, context)
