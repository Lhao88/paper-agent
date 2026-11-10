from datetime import date
from typing import Literal

from pydantic import Field

from app.schemas.contracts import Scope, StrictModel


class BenchmarkTopic(StrictModel):
    topic_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    split: Literal["dev", "test"]
    topic_zh: str
    cutoff_date: date
    question_ids: list[str]
    scope: Scope = Field(default_factory=Scope)
    corpus_snapshot: str
    gold_annotations: str
    document_manifest: str
    protocol_version: str
    synthetic: bool = False


class EvaluationConfig(StrictModel):
    name: str
    strategy: Literal["B0", "B1", "B2", "A1", "A2", "coverage"] = "B2"
    planner_mode: Literal["legacy", "coverage"] = "legacy"
    dataset: str
    repetitions: int = Field(default=3, ge=1, le=10)
    budgets: dict[str, int] = Field(default_factory=dict)
    llm_mode: Literal["mock", "live"] = "mock"
    cache_policy: Literal["cold_model_warm_files"] = "cold_model_warm_files"
    human_annotations: str | None = None
    protocol_version: str = "v1"
    model_screen: str | None = None
    model_research: str | None = None
    line: Literal["fixed_corpus"] = "fixed_corpus"
