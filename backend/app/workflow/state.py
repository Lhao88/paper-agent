from typing import TypedDict


class ResearchState(TypedDict):
    run_id: str
    plan_id: str | None
    stage: str
    retrieval_artifact_id: str | None
    screening_artifact_id: str | None
    selection_artifact_id: str | None
    reading_artifact_ids: list[str]
    synthesis_artifact_id: str | None
    review_artifact_id: str | None
    review_bundle_artifact_id: str | None
    supplement_round: int
    revision_round: int
    next_action: str
    round_index: int
    coverage_artifact_id: str | None
    notebook_ids: list[str]
    stop_reason: str


def initial_state(run_id: str) -> ResearchState:
    return ResearchState(
        run_id=run_id,
        plan_id=None,
        stage="plan",
        retrieval_artifact_id=None,
        screening_artifact_id=None,
        selection_artifact_id=None,
        reading_artifact_ids=[],
        synthesis_artifact_id=None,
        review_artifact_id=None,
        review_bundle_artifact_id=None,
        supplement_round=0,
        revision_round=0,
        next_action="finish",
        round_index=0,
        coverage_artifact_id=None,
        notebook_ids=[],
        stop_reason="",
    )
