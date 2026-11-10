from uuid import uuid4

import httpx

from app.config import PROJECT_ROOT
from app.db.session import get_test_settings
from app.main import create_app


async def test_project_run_idempotency_cancel_and_upload_boundaries():
    app = create_app(get_test_settings())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client:
            created = await client.post(
                "/api/projects", json={"title": "API测试", "topic": "synthetic research"}
            )
            assert created.status_code == 201, created.text
            project_id = created.json()["id"]
            headers = {"Idempotency-Key": str(uuid4())}
            url = f"/api/projects/{project_id}/runs"
            first = await client.post(url, json={}, headers=headers)
            second = await client.post(url, json={}, headers=headers)
            assert first.status_code == second.status_code == 202
            assert first.json()["id"] == second.json()["id"]
            conflict = await client.post(
                url, json={"budgets": {"max_candidates": 10}}, headers=headers
            )
            assert conflict.status_code == 409
            run_id = first.json()["id"]
            assert (await client.post(f"/api/runs/{run_id}/cancel")).status_code == 202
            assert (await client.post(f"/api/runs/{run_id}/cancel")).json()["status"] == "cancelled"
            fake = await client.post(
                f"/api/projects/{project_id}/documents",
                files={"file": ("fake.pdf", b"<html>", "application/pdf")},
            )
            assert fake.status_code == 422
            traversal = await client.post(
                f"/api/projects/{project_id}/documents",
                files={"file": ("../../bad.pdf", b"%PDF-123", "application/pdf")},
            )
            assert traversal.status_code == 422
            pdf = (PROJECT_ROOT / "backend/fixtures/documents/paper-1.pdf").read_bytes()
            uploaded = await client.post(
                f"/api/projects/{project_id}/documents",
                files={"file": ("example.pdf", pdf, "application/pdf")},
                data={"display_title": "人工资料"},
            )
            assert uploaded.status_code == 201, uploaded.text
            document_id = uploaded.json()["id"]
            assert (
                await client.get(f"/api/projects/{project_id}/documents/{document_id}/file")
            ).content == pdf
            other = (
                await client.post("/api/projects", json={"title": "其他项目", "topic": "test"})
            ).json()["id"]
            assert (
                await client.get(f"/api/projects/{other}/documents/{document_id}/file")
            ).status_code == 404
