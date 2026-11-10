"""Original, explicitly synthetic extended corpus; never overwrites existing fixtures."""

import json
from pathlib import Path

from app.config import PROJECT_ROOT


def write_missing(path: Path, value: object) -> None:
    if not path.exists():
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_extended_fixtures() -> dict[str, object]:
    from reportlab.pdfgen import canvas

    root = PROJECT_ROOT / "backend" / "fixtures"
    papers = json.loads((root / "papers.json").read_text(encoding="utf-8"))
    gold = {"paper-1": 4, "paper-2": 4, "paper-3": None}
    for index in range(4, 11):
        abstract = (
            None
            if index == 4
            else (
                "Synthetic marine algae growth study, unrelated to academic retrieval."
                if index in {5, 6}
                else "This synthetic study examines evaluation limitations of evidence retrieval."
                if index == 7
                else (
                    "Synthetic metadata organization for literature research, "
                    "with insufficient evaluation."
                )
            )
        )
        identifier = f"paper-{index}"
        source = {
            "provider": "mock",
            "provider_id": identifier,
            "version_label": "v1",
            "abstract": abstract,
            "raw_payload": {
                "synthetic": True,
                **({"fixture_pdf": "paper-7.pdf"} if index == 7 else {}),
            },
        }
        papers.append(
            {
                "title": f"Synthetic Example {index}: "
                + ("Missing abstract" if abstract is None else abstract[:70]),
                "authors": ["Fixture Author"],
                "year": 2025,
                "abstract": abstract,
                "abstract_status": "provided" if abstract else "missing",
                "abstract_source_key": f"mock:{identifier}:v1",
                "sources": [source],
            }
        )
        relevance = None if index == 4 else 0 if index in {5, 6} else 4 if index == 7 else 2
        gold[identifier] = relevance
        if relevance is not None:
            write_missing(
                root / "model" / f"ScreenOutput-{identifier}.json",
                {
                    "summary_zh": "原创合成资料，用于测试筛选边界。",
                    "matched_question_ids": []
                    if relevance == 0
                    else ["q3"]
                    if index == 7
                    else ["q1"],
                    "relevance": relevance,
                    "decision": "exclude"
                    if relevance == 0
                    else "priority"
                    if relevance == 4
                    else "candidate",
                    "reason": "合成金标的预期分类，不代表真实领域相关性。",
                    "missing_information": [],
                },
            )
    # Two repeated source records exercise deduplication; ten distinct papers remain.
    papers.extend([papers[0], papers[1]])
    write_missing(root / "papers-extended.json", papers)
    write_missing(
        root / "gold-extended.json",
        {
            "synthetic": True,
            "profile_version": "extended-v1",
            "raw_records": 12,
            "unique_papers": 10,
            "relevance": gold,
            "expected_selected": ["paper-1", "paper-2", "paper-7"],
            "missing_abstracts": ["paper-3", "paper-4"],
        },
    )
    path = root / "documents" / "paper-7.pdf"
    if not path.exists():
        document = canvas.Canvas(str(path), invariant=1)
        for title, text in [
            ("Methods", "This synthetic study evaluates test coverage on ToyCorpus."),
            (
                "Results",
                "Toy recall is 0.5 on a fictional set of four items; no real claim is made.",
            ),
            ("Limitations", "ToyCorpus has no real-world scientific validity."),
        ]:
            document.drawString(50, 750, title + " (synthetic software-test fixture)")
            document.drawString(50, 720, text)
            document.showPage()
        document.save()
    write_missing(
        root / "model" / "ExtractionOutput-paper-7.json",
        {
            "candidates": [
                {
                    "field_name": "method",
                    "value_zh": "在合成ToyCorpus上检查测试覆盖。",
                    "chunk_id": "$chunk_0",
                    "quote": "This synthetic study evaluates test coverage on ToyCorpus.",
                    "statement_type": "reported_fact",
                }
            ]
        },
    )
    write_missing(
        root / "expected-evidence.json",
        {
            "synthetic": True,
            "paper-7": {
                "page": 1,
                "quote": "This synthetic study evaluates test coverage on ToyCorpus.",
            },
        },
    )
    blank = root / "documents" / "blank.pdf"
    if not blank.exists():
        document = canvas.Canvas(str(blank), invariant=1)
        document.showPage()
        document.save()
    corrupt = root / "documents" / "corrupt.pdf"
    if not corrupt.exists():
        corrupt.write_bytes(b"%PDF-corrupt synthetic fixture, intentionally not parseable")
    return {"profile": "extended", "raw_records": 12, "unique_papers": 10, "synthetic": True}
