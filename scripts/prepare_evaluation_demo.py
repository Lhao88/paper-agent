"""Prepare synthetic evaluation plumbing examples, not a scientific benchmark."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write_new(path: Path, value: str) -> None:
    if not path.exists():
        path.write_text(value, encoding="utf-8")


def main() -> None:
    from app.evaluation.models import BenchmarkTopic
    root = ROOT / "evals"
    for directory in ("corpora", "annotations", "documents", "configs"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    papers = json.loads((ROOT / "backend/fixtures/papers.json").read_text(encoding="utf-8"))
    write_new(root / "corpora/demo.jsonl", "\n".join(json.dumps(paper, ensure_ascii=False) for paper in papers) + "\n")
    gold = [{"paper_key": f"mock:paper-{i}:v1", "relevance": 4 if i < 3 else None, "key_paper": i < 3,
             "synthetic": True, "rater_id": "fixture-author-not-human-study"} for i in range(1, 4)]
    write_new(root / "annotations/demo.jsonl", "\n".join(json.dumps(row) for row in gold) + "\n")
    write_new(root / "documents/demo-manifest.jsonl", "")
    topics = [{"topic_id": f"demo-{i}", "split": "dev", "topic_zh": name, "cutoff_date": "2026-10-30",
        "question_ids": ["q1", "q2", "q3"], "corpus_snapshot": "corpora/demo.jsonl",
        "gold_annotations": "annotations/demo.jsonl", "document_manifest": "documents/demo-manifest.jsonl",
        "protocol_version": "v1", "synthetic": True} for i, name in enumerate([
            "合成演示：学术检索研究概览", "合成演示：文献证据方法比较", "合成演示：研究评价与近期进展"], 1)]
    write_new(root / "benchmark.dev.jsonl", "\n".join(json.dumps(topic, ensure_ascii=False) for topic in topics) + "\n")
    write_new(root / "benchmark.test.jsonl", "")
    write_new(root / "dataset.schema.json", json.dumps(BenchmarkTopic.model_json_schema(), ensure_ascii=False, indent=2))
    for strategy in ("B0", "B1", "B2", "A1", "A2"):
        write_new(root / "configs" / f"{strategy}.json", json.dumps({"name": f"synthetic-{strategy}", "strategy": strategy,
            "dataset": "benchmark.dev.jsonl", "repetitions": 1, "budgets": {"max_candidates": 10, "max_screen_papers": 5,
                "max_deep_read_papers": 3, "max_llm_calls": 40}, "llm_mode": "mock", "protocol_version": "v1"}, indent=2))
    print("Synthetic development examples prepared; independent test set intentionally empty.")


if __name__ == "__main__":
    main()
