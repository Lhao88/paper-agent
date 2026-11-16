from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import ProjectPaper

if TYPE_CHECKING:
    from app.planning.admit import PaperAdmission

INCLUDED = "included"
PINNED = "pinned"
EXCLUDED = "excluded"

_CANONICAL = {
    "include": INCLUDED,
    "included": INCLUDED,
    "pin": PINNED,
    "pinned": PINNED,
    "exclude": EXCLUDED,
    "excluded": EXCLUDED,
}


def canonical_decision(decision: str) -> str:
    try:
        return _CANONICAL[decision]
    except KeyError as exc:
        raise ValueError("文献库决定必须是 included、pinned 或 excluded。") from exc


def admission_for(decision: str) -> PaperAdmission:
    from app.planning.admit import PaperAdmission

    stored = canonical_decision(decision)
    if stored == EXCLUDED:
        return PaperAdmission(paper_id=uuid4(), status=EXCLUDED)
    if stored == PINNED:
        return PaperAdmission(paper_id=uuid4(), status=PINNED, included=True)
    return PaperAdmission(paper_id=uuid4(), status="active", included=True)


def is_excluded(decision: str | None) -> bool:
    if decision is None:
        return False
    try:
        return canonical_decision(decision) == EXCLUDED
    except ValueError:
        return False


def candidate_ids(rows: Sequence[tuple[UUID, str]]) -> list[UUID]:
    return [paper_id for paper_id, decision in rows if canonical_decision(decision) != EXCLUDED]


async def visible_decisions(session: AsyncSession, project_id: UUID) -> dict[str, list[UUID]]:
    """下一次运行检索前可见的在库、钉住和排除。"""
    rows = list(
        await session.scalars(select(ProjectPaper).where(ProjectPaper.project_id == project_id))
    )
    grouped: dict[str, list[UUID]] = {INCLUDED: [], PINNED: [], EXCLUDED: []}
    for row in rows:
        if row.user_decision is None:
            continue
        try:
            grouped[canonical_decision(row.user_decision)].append(row.paper_id)
        except ValueError:
            continue
    return grouped
