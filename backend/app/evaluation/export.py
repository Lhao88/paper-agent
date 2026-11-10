import csv
import json
from pathlib import Path


def csv_cell(value: object) -> object:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({field: csv_cell(row.get(field)) for field in fields} for row in rows)


def export_results(
    output: Path, records: list[dict[str, object]], human: list[dict[str, object]]
) -> None:
    (output / "metrics.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    fields = sorted({key for row in records for key in row})
    write_csv(output / "results.csv", records, fields)
    write_csv(
        output / "human-review.csv",
        human,
        [
            "run_id",
            "block_id",
            "text",
            "evidence_ids",
            "quotes",
            "rater_id",
            "support",
            "question_ids",
            "notes",
        ],
    )
    report = [
        "# 实验执行记录",
        "",
        "此文件报告实际执行，不将合成/模拟结果当作学术效果证明。",
        "未导入人工审核的指标保持null；unknown预留用量不算零费用。",
        "",
        "| 运行 | 配置 | 状态 | 人工支持率 |",
        "| --- | --- | --- | --- |",
    ]
    for record in records:
        report.append(
            f"| {record.get('run_id')} | {record.get('strategy')} | {record.get('status')} "
            f"| {record.get('citation_support_rate')} |"
        )
    (output / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
