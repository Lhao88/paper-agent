import asyncio
import socket
from uuid import uuid4

import httpx
import httpx2
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.db.session import get_test_settings
from app.main import create_app


async def test_real_http_mcp_and_rest_share_run_after_disconnect():
    settings = get_test_settings().model_copy(update={"mcp_enabled": True})
    app = create_app(settings)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    base = f"http://127.0.0.1:{port}"
    try:
        async with asyncio.timeout(10):
            while not server.started:
                await asyncio.sleep(0.02)
        async with httpx.AsyncClient(base_url=base, trust_env=False) as rest:
            assert (await rest.get("/api/health/live")).status_code == 200
            assert (await rest.get("/openapi.json")).status_code == 200
            project = (
                await rest.post("/api/projects", json={"title": "MCP跨入口", "topic": "synthetic"})
            ).json()
            key = str(uuid4())
            async with httpx2.AsyncClient(trust_env=False) as http:
                async with streamable_http_client(base + "/mcp", http_client=http) as streams:
                    async with ClientSession(*streams) as client_a:
                        await client_a.initialize()
                        listed = await client_a.list_tools()
                        assert len(listed.tools) == 9
                        response = await client_a.call_tool(
                            "start_research", {"project_id": project["id"], "idempotency_key": key}
                        )
                        assert not response.is_error
                        run = response.structured_content["data"]
                        same = await rest.post(
                            f"/api/projects/{project['id']}/runs",
                            json={},
                            headers={"Idempotency-Key": key},
                        )
                        assert same.json()["id"] == run["id"]
                        forbidden = await client_a.call_tool(
                            "search_papers",
                            {
                                "project_id": project["id"],
                                "run_id": run["id"],
                                "query": "retrieval",
                                "question_ids": ["q1"],
                                "idempotency_key": "search",
                            },
                        )
                        assert forbidden.is_error
                # A has disconnected. A separate SDK client observes the same persistent run.
                async with streamable_http_client(base + "/mcp", http_client=http) as streams:
                    async with ClientSession(*streams) as client_b:
                        await client_b.initialize()
                        response = await client_b.call_tool(
                            "get_research_status",
                            {"project_id": project["id"], "run_id": run["id"]},
                        )
                        assert response.structured_content["data"]["id"] == run["id"]
                        assert response.structured_content["data"]["status"] == "queued"
                        denied = await client_b.call_tool(
                            "get_research_status", {"project_id": str(uuid4()), "run_id": run["id"]}
                        )
                        assert denied.is_error
            hostile = await rest.post(
                "/mcp",
                headers={
                    "Origin": "https://evil.example",
                    "Accept": "application/json, text/event-stream",
                },
                json={},
            )
            assert hostile.status_code in {400, 403}
    finally:
        server.should_exit = True
        await asyncio.wait_for(serving, 10)
        listener.close()
