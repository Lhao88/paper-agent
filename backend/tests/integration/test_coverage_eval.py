import json

from app.config import PROJECT_ROOT
from app.db.session import get_test_settings
from app.evaluation.runner import evaluate


async def test_coverage_smoke_completes_without_human_support(tmp_path):
    output = tmp_path / "coverage-smoke"
    await evaluate(PROJECT_ROOT / "evals/configs/coverage.json", output, get_test_settings())
    records = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
    assert records
    for record in records:
        assert record["status"] == "completed"
        assert record["citation_support_rate"] is None
        assert isinstance(record["seed_paper_recall"], int | float)
        assert isinstance(record["sentence_evidence_existence_rate"], int | float)
