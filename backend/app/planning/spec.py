from app.config import Settings
from app.errors import DomainError
from app.schemas.contracts import (
    CoverageTarget,
    ExtractionColumn,
    InclusionRule,
    PlanRequest,
    Question,
    ResearchSpec,
    SpecDraft,
)


def allowed_sources_for(settings: Settings) -> set[str]:
    sources = {"openalex"}
    if settings.enable_arxiv:
        sources.add("arxiv")
    if settings.enable_semantic_scholar:
        sources.add("semantic_scholar")
    return sources


def normalize_spec(
    draft: SpecDraft, request: PlanRequest, allowed_sources: set[str]
) -> ResearchSpec:
    _require_allowed(draft.scope.enabled_sources, allowed_sources)
    _require_allowed(request.scope.enabled_sources, allowed_sources)
    questions, question_ids = _reindex_questions(draft.questions)
    rules = _reindex_rules(draft.inclusion_rules)
    columns, column_ids = _reindex_columns(draft.columns, question_ids)
    coverage = _reindex_coverage(draft.coverage, question_ids, column_ids)
    return ResearchSpec(
        topic=request.topic,
        questions=questions,
        scope=request.scope,
        inclusion_rules=rules,
        columns=columns,
        coverage=coverage,
        assumptions=list(draft.assumptions),
    )


def _require_allowed(sources: list[str], allowed_sources: set[str]) -> None:
    if not set(sources) <= allowed_sources:
        raise DomainError("SOURCE_NOT_ENABLED", "计划请求了未启用的数据来源。")


def _reindex_questions(questions: list[Question]) -> tuple[list[Question], dict[str, str]]:
    mapping: dict[str, str] = {}
    rewritten: list[Question] = []
    for index, question in enumerate(questions, 1):
        if question.question_id in mapping:
            raise DomainError("SPEC_INVALID", "研究规格含重复问题编号。")
        new_id = f"q{index}"
        mapping[question.question_id] = new_id
        rewritten.append(question.model_copy(update={"question_id": new_id}))
    return rewritten, mapping


def _reindex_rules(rules: list[InclusionRule]) -> list[InclusionRule]:
    seen: set[str] = set()
    rewritten: list[InclusionRule] = []
    for index, rule in enumerate(rules, 1):
        if rule.rule_id in seen:
            raise DomainError("SPEC_INVALID", "研究规格含重复纳入规则编号。")
        seen.add(rule.rule_id)
        rewritten.append(rule.model_copy(update={"rule_id": f"r{index}"}))
    return rewritten


def _reindex_columns(
    columns: list[ExtractionColumn], question_ids: dict[str, str]
) -> tuple[list[ExtractionColumn], dict[str, str]]:
    mapping: dict[str, str] = {}
    rewritten: list[ExtractionColumn] = []
    for index, column in enumerate(columns, 1):
        if column.question_id not in question_ids:
            raise DomainError("SPEC_INVALID", "抽取列指向了不存在的问题。")
        if column.column_id in mapping:
            raise DomainError("SPEC_INVALID", "研究规格含重复抽取列编号。")
        new_id = f"c{index}"
        mapping[column.column_id] = new_id
        rewritten.append(
            column.model_copy(
                update={"column_id": new_id, "question_id": question_ids[column.question_id]}
            )
        )
    return rewritten, mapping


def _reindex_coverage(
    coverage: list[CoverageTarget], question_ids: dict[str, str], column_ids: dict[str, str]
) -> list[CoverageTarget]:
    rewritten: list[CoverageTarget] = []
    for target in coverage:
        if target.question_id not in question_ids:
            raise DomainError("SPEC_INVALID", "覆盖目标指向了不存在的问题。")
        required: list[str] = []
        for column_id in target.required_column_ids:
            if column_id not in column_ids:
                raise DomainError("SPEC_INVALID", "覆盖目标指向了不存在的抽取列。")
            required.append(column_ids[column_id])
        rewritten.append(
            target.model_copy(
                update={
                    "question_id": question_ids[target.question_id],
                    "required_column_ids": required,
                }
            )
        )
    return rewritten
