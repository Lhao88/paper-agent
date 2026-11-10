from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Artifact
from app.errors import DomainError
from app.repositories.locking import lock_operation


class ArtifactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create(
        self,
        run_id: UUID,
        operation_key: str,
        kind: str,
        payload: dict[str, object],
        input_hash: str,
    ) -> Artifact:
        await lock_operation(self.session, f"artifact:{run_id}:{operation_key}")
        existing = await self.session.scalar(
            select(Artifact).where(
                Artifact.run_id == run_id, Artifact.operation_key == operation_key
            )
        )
        if existing is not None:
            if existing.input_hash != input_hash:
                raise DomainError("ARTIFACT_INPUT_CONFLICT", "已有成果的输入版本不同。")
            return existing
        artifact = Artifact(
            run_id=run_id,
            operation_key=operation_key,
            kind=kind,
            payload_json=payload,
            input_hash=input_hash,
        )
        self.session.add(artifact)
        await self.session.flush()
        return artifact
