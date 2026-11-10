from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Claim, Evidence
from app.errors import DomainError

EXPERIMENTAL_FIELDS = {"result", "metric", "experimental_setup"}


async def record_claim(
    session: AsyncSession,
    *,
    project_id: UUID,
    run_id: UUID,
    paper_id: UUID,
    question_id: str,
    column_id: str,
    column_field: str,
    evidence_id: UUID,
    polarity: Literal["support", "contradict"],
    value_zh: str,
) -> Claim:
    existing = await _existing(
        session, project_id, paper_id, column_id, evidence_id, polarity
    )
    if existing is not None:
        return existing
    evidence = await session.get(Evidence, evidence_id)
    if evidence is None or evidence.paper_id != paper_id:
        raise DomainError("CLAIM_EVIDENCE_MISMATCH", "主张必须指向同一篇论文的证据。")
    if evidence.basis == "abstract" and column_field in EXPERIMENTAL_FIELDS:
        raise DomainError("ABSTRACT_NOT_EXPERIMENTAL", "仅摘要证据不能写成实验结论。")
    claim = Claim(
        project_id=project_id,
        run_id=run_id,
        paper_id=paper_id,
        question_id=question_id,
        column_id=column_id,
        evidence_id=evidence_id,
        polarity=polarity,
        value_zh=value_zh,
    )
    try:
        async with session.begin_nested():
            session.add(claim)
            await session.flush()
    except IntegrityError:
        raced = await _existing(session, project_id, paper_id, column_id, evidence_id, polarity)
        if raced is None:
            raise
        return raced
    return claim


async def _existing(
    session: AsyncSession,
    project_id: UUID,
    paper_id: UUID,
    column_id: str,
    evidence_id: UUID,
    polarity: str,
) -> Claim | None:
    return await session.scalar(
        select(Claim).where(
            Claim.project_id == project_id,
            Claim.paper_id == paper_id,
            Claim.column_id == column_id,
            Claim.evidence_id == evidence_id,
            Claim.polarity == polarity,
        )
    )
