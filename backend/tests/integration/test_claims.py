from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Evidence
from app.errors import DomainError
from app.memory.ledger import record_claim
from app.repositories.papers import PaperRepository
from app.repositories.projects import ProjectRepository


async def test_record_claim_is_idempotent_and_rejects_cross_paper_evidence(
    db_session: AsyncSession,
) -> None:
    project = await ProjectRepository(db_session).create("账本", "图神经网络")
    run = await ProjectRepository(db_session).create_run(project.id, "ledger", "hash", {}, {})
    papers = PaperRepository(db_session)
    first = await papers.upsert_source(
        "fixture", str(uuid4()), "v1", "第一篇", None, "方法摘要", {}
    )
    second = await papers.upsert_source("fixture", str(uuid4()), "v1", "第二篇", None, "摘要", {})
    evidence = Evidence(
        paper_id=first.paper_id,
        basis="abstract",
        source_id=first.id,
        quote="方法摘要",
        quote_start=0,
        quote_end=4,
        statement_type="reported_fact",
    )
    db_session.add(evidence)
    await db_session.flush()
    created = await record_claim(
        db_session,
        project_id=project.id,
        run_id=run.id,
        paper_id=first.paper_id,
        question_id="q1",
        column_id="c1",
        column_field="method",
        evidence_id=evidence.id,
        polarity="support",
        value_zh="使用图卷积",
    )
    repeated = await record_claim(
        db_session,
        project_id=project.id,
        run_id=run.id,
        paper_id=first.paper_id,
        question_id="q1",
        column_id="c1",
        column_field="method",
        evidence_id=evidence.id,
        polarity="support",
        value_zh="使用图卷积",
    )
    assert repeated.id == created.id
    with pytest.raises(DomainError) as mismatch:
        await record_claim(
            db_session,
            project_id=project.id,
            run_id=run.id,
            paper_id=second.paper_id,
            question_id="q1",
            column_id="c1",
            column_field="method",
            evidence_id=evidence.id,
            polarity="support",
            value_zh="错误归属",
        )
    assert mismatch.value.code == "CLAIM_EVIDENCE_MISMATCH"
    with pytest.raises(DomainError) as experimental:
        await record_claim(
            db_session,
            project_id=project.id,
            run_id=run.id,
            paper_id=first.paper_id,
            question_id="q1",
            column_id="c2",
            column_field="result",
            evidence_id=evidence.id,
            polarity="support",
            value_zh="准确率更高",
        )
    assert experimental.value.code == "ABSTRACT_NOT_EXPERIMENTAL"


async def test_record_claim_rejects_a_quote_span_that_misses_the_source(
    db_session: AsyncSession,
) -> None:
    from sqlalchemy import func, select

    from app.db import Claim

    project = await ProjectRepository(db_session).create("跨度", "图神经网络")
    run = await ProjectRepository(db_session).create_run(project.id, "span", "hash", {}, {})
    papers = PaperRepository(db_session)
    saved = await papers.upsert_source(
        "fixture", str(uuid4()), "v1", "第一篇", None, "方法摘要", {}
    )
    evidence = Evidence(
        paper_id=saved.paper_id,
        basis="abstract",
        source_id=saved.id,
        quote="不在摘要",
        quote_start=0,
        quote_end=4,
        statement_type="reported_fact",
    )
    db_session.add(evidence)
    await db_session.flush()
    with pytest.raises(DomainError) as mismatch:
        await record_claim(
            db_session,
            project_id=project.id,
            run_id=run.id,
            paper_id=saved.paper_id,
            question_id="q1",
            column_id="c1",
            column_field="method",
            evidence_id=evidence.id,
            polarity="support",
            value_zh="错误引用",
        )
    assert mismatch.value.code == "EVIDENCE_INVALID"
    count = await db_session.scalar(
        select(func.count()).select_from(Claim).where(Claim.project_id == project.id)
    )
    assert count == 0
