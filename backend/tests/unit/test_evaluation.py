import json
from pathlib import Path

import pytest

from app.config import PROJECT_ROOT, Settings
from app.errors import DomainError
from app.evaluation.runner import evaluate, resolve_input


async def test_evaluation_refuses_overwrite_before_starting_run(tmp_path: Path):
    with pytest.raises(FileExistsError):
        await evaluate(PROJECT_ROOT / "evals/configs/B2.json", tmp_path, Settings())


async def test_empty_benchmark_test_set_is_refused(tmp_path: Path):
    config = tmp_path / "empty.json"
    config.write_text(
        json.dumps(
            {
                "name": "empty",
                "strategy": "B2",
                "dataset": "benchmark.test.jsonl",
                "repetitions": 1,
                "llm_mode": "mock",
                "protocol_version": "v1",
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "out"
    with pytest.raises(DomainError) as exc:
        await evaluate(config, output, Settings())
    assert exc.value.code == "INVALID_EVAL_DATA"
    assert not output.exists()


def test_evaluation_input_cannot_escape_root():
    with pytest.raises(DomainError) as exc:
        resolve_input("../.env")
    assert exc.value.code == "INVALID_EVAL_PATH"
