import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from uuid import UUID, uuid4

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import select

from app.config import PROJECT_ROOT, Settings
from app.db import Artifact, PaperSource, Run
from app.db.session import create_engine, get_test_settings, session_factory
from app.errors import DomainError
from app.evaluation.export import export_results
from app.evaluation.metrics import calculate_metrics
from app.evaluation.models import BenchmarkTopic, EvaluationConfig
from app.review.models import ReviewDocument
from app.schemas.contracts import (
    CoverageReport,
    PaperRecord,
    PreselectionResult,
    ResearchPlan,
    SelectionResult,
)
from app.services.base import Services
from app.services.projects import create_project
from app.services.research import (
    ApprovePlan,
    StartResearch,
    approve_plan,
    get_plan,
    get_status,
    start_research,
)
from app.worker.claim import claim_next_run
from app.worker.execute import execute_run

EVAL_ROOT = PROJECT_ROOT / "evals"


def resolve_input(value: str) -> Path:
    path = (EVAL_ROOT / value).resolve()
    if not path.is_relative_to(EVAL_ROOT.resolve()) or not path.is_file():
        raise DomainError("INVALID_EVAL_PATH", "评价输入必须是evals目录内已存在的文件。")
    return path


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, object]]:
    values = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if any(not isinstance(value, dict) for value in values):
        raise DomainError("INVALID_EVAL_DATA", "JSONL每行需为对象。")
    return values


def corpus_identity_map(
    papers: list[PaperRecord], sources: list[PaperSource], preferred: set[str]
) -> dict[str, str]:
    """Map only exact source snapshots in this frozen corpus, never global last-writer identity."""
    stored = {
        (source.provider, source.provider_id, source.version_label): source.paper_id
        for source in sources
    }
    candidates: dict[str, set[str]] = {}
    for paper in papers:
        for source in paper.sources:
            digest = hashlib.sha256(
                json.dumps(
                    {"abstract": source.abstract, "payload": source.raw_payload},
                    sort_keys=True,
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()
            paper_id = stored.get(
                (source.provider, source.provider_id, f"{source.version_label}:{digest[:16]}")
            )
            if paper_id is not None:
                candidates.setdefault(str(paper_id), set()).add(source.source_key)
    result: dict[str, str] = {}
    for canonical_id, aliases in candidates.items():
        annotated = aliases & preferred
        if len(annotated) > 1:
            raise DomainError(
                "INVALID_EVAL_DATA", "同一论文的重复来源被重复标注，请先按身份去重金标。"
            )
        result[canonical_id] = min(annotated or aliases)
    return result


def coverage_fill_counts(artifacts: list[Artifact]) -> dict[str, int]:
    latest: Artifact | None = None
    latest_index = -1
    for artifact in artifacts:
        if artifact.kind != "coverage":
            continue
        index = artifact.payload_json.get("round_index")
        if isinstance(index, bool) or not isinstance(index, int) or index < latest_index:
            continue
        latest, latest_index = artifact, index
    if latest is None:
        return {}
    report = CoverageReport.model_validate(latest.payload_json)
    required = [cell for cell in report.cells if cell.required]
    return {
        "required_cells": len(required),
        "filled_required_cells": sum(cell.filled_papers > 0 for cell in required),
    }


def validate_snapshot(topic: BenchmarkTopic) -> dict[str, str]:
    paths = [
        resolve_input(value)
        for value in (topic.corpus_snapshot, topic.gold_annotations, topic.document_manifest)
    ]
    papers = [PaperRecord.model_validate(value) for value in read_jsonl(paths[0])]
    if not papers:
        raise DomainError("INVALID_EVAL_DATA", "冻结候选池不能为空。")
    for paper in papers:
        for source in paper.sources:
            if source.pdf_url:
                raise DomainError(
                    "INVALID_EVAL_DATA", "固定语料实验禁止在线PDF地址，请使用冻结文档清单。"
                )
            if not topic.synthetic and source.provider != "frozen":
                raise DomainError(
                    "INVALID_EVAL_DATA", "真实冻结语料使用frozen来源，不能标为mock演示资料。"
                )
    manifest = read_jsonl(paths[2])
    hashes = {str(path.relative_to(EVAL_ROOT)): file_hash(path) for path in paths}
    available = set()
    for item in manifest:
        path = resolve_input(str(item["path"]))
        if item.get("allowed_to_process") is not True or item.get("sha256") != file_hash(path):
            raise DomainError("INVALID_EVAL_DATA", "文档许可确认或哈希不匹配。")
        hashes[str(path.relative_to(EVAL_ROOT))] = file_hash(path)
        available.add(path.name)
    for paper in papers:
        for source in paper.sources:
            if (
                source.raw_payload.get("local_pdf_key")
                and source.raw_payload["local_pdf_key"] not in available
            ):
                raise DomainError("INVALID_EVAL_DATA", "论文引用了清单外的冻结PDF。")
    return hashes


async def evaluate(config_path: Path, output: Path, settings: Settings) -> dict[str, object]:
    config = EvaluationConfig.model_validate_json(config_path.read_text(encoding="utf-8"))
    dataset = resolve_input(config.dataset)
    topics = [BenchmarkTopic.model_validate(value) for value in read_jsonl(dataset)]
    if not topics:
        raise DomainError("INVALID_EVAL_DATA", "评价集尚未准备；不得用空测试集生成结论。")
    hashes = {
        config_path.name: file_hash(config_path),
        str(dataset.relative_to(EVAL_ROOT)): file_hash(dataset),
    }
    for topic in topics:
        hashes.update(validate_snapshot(topic))
    # Never overwrite an earlier experiment, even if it only partially completed.
    output.mkdir(parents=True, exist_ok=False)
    source_files = sorted((PROJECT_ROOT / "backend" / "app").rglob("*.py"))
    source_hash = hashlib.sha256(
        "".join(file_hash(path) for path in source_files).encode()
    ).hexdigest()
    manifest = {
        "started_at": datetime.now(UTC).isoformat(),
        "config": config.model_dump(mode="json"),
        "inputs": hashes,
        "source_sha256": source_hash,
        "backend_lock_sha256": file_hash(PROJECT_ROOT / "backend" / "uv.lock"),
        "frontend_lock_sha256": file_hash(PROJECT_ROOT / "frontend" / "package-lock.json"),
        "prompts": {
            path.name: file_hash(path)
            for path in sorted((PROJECT_ROOT / "backend/prompts").glob("*.j2"))
        },
        "screen_model": config.model_screen or settings.llm_screen_model,
        "research_model": config.model_research or settings.llm_research_model,
        "mock_results_are_not_scientific_evidence": config.llm_mode == "mock",
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    records: list[dict[str, object]] = []
    audit: list[dict[str, object]] = []
    original = get_test_settings(settings)
    engine = create_engine(original)
    factory = session_factory(engine)
    try:
        async with AsyncPostgresSaver.from_conn_string(original.checkpoint_dsn) as saver:
            await saver.setup()
            for topic in topics:
                for repeat in range(config.repetitions):
                    planner_mode = "coverage" if config.strategy == "coverage" else "legacy"
                    research_strategy = "B2" if config.strategy == "coverage" else config.strategy
                    frozen = Settings.model_validate(
                        {
                            **original.model_dump(),
                            "llm_mode": config.llm_mode,
                            "source_mode": "mock",
                            "mock_corpus_profile": "frozen",
                            "frozen_corpus_path": resolve_input(topic.corpus_snapshot),
                            "research_strategy": research_strategy,
                            "planner_mode": planner_mode,
                            "llm_screen_model": config.model_screen or original.llm_screen_model,
                            "llm_research_model": config.model_research
                            or original.llm_research_model,
                        }
                    )
                    services = Services(frozen, factory)
                    project = await create_project(
                        services,
                        f"[评估 {config.strategy}] {topic.topic_id} #{repeat + 1}",
                        topic.topic_zh,
                    )
                    started = monotonic()
                    accepted = await start_research(
                        services,
                        UUID(str(project["id"])),
                        StartResearch(scope=topic.scope, budgets=config.budgets),
                        str(uuid4()),
                    )
                    run_id = UUID(str(accepted["id"]))
                    lease = await claim_next_run(factory, "evaluation-cli", run_id)
                    if lease:
                        await execute_run(engine, factory, frozen, saver, lease)
                    status = await get_status(services, run_id)
                    if status["status"] == "waiting_user":
                        planned = await get_plan(services, run_id)
                        typed = ResearchPlan.model_validate(planned["plan"])
                        await approve_plan(
                            services,
                            run_id,
                            ApprovePlan(expected_version=typed.version),
                            "evaluation-approved-plan",
                        )
                        lease = await claim_next_run(factory, "evaluation-cli", run_id)
                        if lease:
                            await execute_run(engine, factory, frozen, saver, lease)
                    status = await get_status(services, run_id)
                    async with factory() as session:
                        run = await session.get(Run, run_id)
                        artifacts = list(
                            await session.scalars(
                                select(Artifact)
                                .where(Artifact.run_id == run_id)
                                .order_by(Artifact.created_at)
                            )
                        )
                        corpus = [
                            PaperRecord.model_validate(value)
                            for value in read_jsonl(resolve_input(topic.corpus_snapshot))
                        ]
                        identifiers = {
                            source.provider_id for paper in corpus for source in paper.sources
                        }
                        sources = list(
                            await session.scalars(
                                select(PaperSource).where(PaperSource.provider_id.in_(identifiers))
                            )
                        )
                        gold = read_jsonl(resolve_input(topic.gold_annotations))
                        keys = corpus_identity_map(
                            corpus, sources, {str(row["paper_key"]) for row in gold}
                        )
                        selected, preselected, screened = [], [], []
                        document = None
                        for artifact in artifacts:
                            if artifact.kind == "selection":
                                selected = [
                                    keys[str(identifier)]
                                    for identifier in SelectionResult.model_validate(
                                        artifact.payload_json
                                    ).selected_ids
                                ]
                            if artifact.kind == "preselection":
                                preselected = [
                                    keys[str(identifier)]
                                    for identifier in PreselectionResult.model_validate(
                                        artifact.payload_json
                                    ).selected_ids
                                ]
                            if artifact.kind == "screening" and artifact.paper_id:
                                screened.append(keys[str(artifact.paper_id)])
                            if artifact.kind == "review":
                                document = ReviewDocument.model_validate(artifact.payload_json)
                        claims = (
                            []
                            if document is None
                            else [
                                block
                                for section in document.sections
                                for block in section.blocks
                                if block.kind in {"literature_claim", "synthesis"}
                            ]
                        )
                        cited = [
                            identifier for block in claims for identifier in block.evidence_ids
                        ]
                        known = (
                            set()
                            if document is None
                            else {item.evidence_id for item in document.evidence}
                        )
                        evidenced_sentences = sum(
                            1
                            for block in claims
                            if block.evidence_ids and set(block.evidence_ids) <= known
                        )
                        usage = {
                            "question_ids": topic.question_ids,
                            "run_id": str(run_id),
                            "topic_id": topic.topic_id,
                            "strategy": config.strategy,
                            "repetition": repeat + 1,
                            "status": status["status"],
                            "stop_reason": status["error_json"],
                            "used_calls": status["used_calls"],
                            "used_tokens": status["used_tokens"],
                            "reserved_tokens": status["reserved_tokens"],
                            "unknown_calls": status["unknown_calls"],
                            "elapsed_seconds": monotonic() - started,
                            "reported_currency_cost": None,
                            "citation_count": len(cited),
                            "existing_citations": sum(identifier in known for identifier in cited),
                            "sentence_count": len(claims),
                            "sentences_with_existing_evidence": evidenced_sentences,
                            "planner_mode": planner_mode,
                            **coverage_fill_counts(artifacts),
                            "synthetic": topic.synthetic,
                            "llm_mode": config.llm_mode,
                            "frozen_budget": {} if run is None else run.config_snapshot,
                        }
                        gold = read_jsonl(resolve_input(topic.gold_annotations))
                        raw = {
                            "usage": usage,
                            "gold": gold,
                            "selected": selected,
                            "preselected": preselected,
                            "screened": screened,
                            "review": document.model_dump(mode="json") if document else None,
                        }
                        (output / f"run-{run_id}.json").write_text(
                            json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
                        )
                        records.append(
                            calculate_metrics(gold, selected, preselected, screened, [], usage)
                        )
                        evidence = (
                            {}
                            if document is None
                            else {item.evidence_id: item.quote for item in document.evidence}
                        )
                        audit.extend(
                            {
                                "run_id": str(run_id),
                                "block_id": str(block.block_id),
                                "text": block.text,
                                "evidence_ids": list(map(str, block.evidence_ids)),
                                "quotes": [
                                    evidence.get(identifier, "")
                                    for identifier in block.evidence_ids
                                ],
                                "rater_id": "",
                                "support": "",
                                "question_ids": "",
                                "notes": "",
                            }
                            for block in claims
                        )
                    export_results(output, records, audit)
    finally:
        await engine.dispose()
    return {"runs": len(records), "output": str(output), "mock": config.llm_mode == "mock"}


def score_existing(input_directory: Path, human_path: Path, output: Path) -> dict[str, object]:
    with human_path.open(encoding="utf-8-sig", newline="") as stream:
        annotations = list(csv.DictReader(stream))
    raw_files = sorted(input_directory.glob("run-*.json"))
    if not raw_files:
        raise DomainError("INVALID_EVAL_DATA", "未找到原始实验运行。")
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for path in raw_files:
        raw = json.loads(path.read_text(encoding="utf-8"))
        labels = [row for row in annotations if row["run_id"] == raw["usage"]["run_id"]]
        valid_blocks = (
            set()
            if raw["review"] is None
            else {
                str(block["block_id"])
                for section in raw["review"]["sections"]
                for block in section["blocks"]
            }
        )
        if any(row["block_id"] not in valid_blocks for row in labels):
            raise DomainError("INVALID_EVAL_DATA", "人工标注含不属于原始运行的段落ID。")
        records.append(
            calculate_metrics(
                raw["gold"],
                raw["selected"],
                raw["preselected"],
                raw["screened"],
                labels,
                raw["usage"],
            )
        )
    export_results(output, records, [])
    (output / "audit-inputs.json").write_text(
        json.dumps(
            {
                "human_sha256": file_hash(human_path),
                "raw_runs": {path.name: file_hash(path) for path in raw_files},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"runs": len(records), "output": str(output), "model_calls": 0}
