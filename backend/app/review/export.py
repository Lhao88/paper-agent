from urllib.parse import urlsplit

from app.review.models import ReviewDocument


def _safe_link(value: str) -> str:
    parsed = urlsplit(value)
    return (
        value.replace("\n", "").replace("\r", "").replace(">", "%3E")
        if parsed.scheme in {"http", "https"}
        else ""
    )


def export_markdown(review: ReviewDocument) -> str:
    lines = [
        f"# {review.topic}",
        "",
        f"检索截止/本版本生成时间：{review.generated_at.isoformat()}",
        "",
        "引用结构已校验；语义支持仍需人工核验。",
        "",
        "## 范围与局限",
        "",
    ]
    lines.extend(f"- {item}" for item in review.limitations)
    for section in review.sections:
        lines.extend(["", f"## {section.title}", ""])
        for block in section.blocks:
            numbers = "".join(f"[{number}]" for number in block.citation_numbers)
            prefix = "【假设，待验证】" if block.kind == "hypothesis" else ""
            lines.extend([prefix + block.text + numbers, ""])
        lines.extend(f"- 待解决：{question}" for question in section.unresolved_questions)
    lines.extend(["", "## 参考文献", ""])
    for ref in review.references:
        links = list(ref.source_urls)
        if ref.doi:
            links.insert(0, "https://doi.org/" + ref.doi)
        lines.append(
            f"[{ref.number}] {'; '.join(ref.authors) or '作者未提供'}. {ref.title}. "
            f"{ref.year or '年份未提供'}. "
            + " ".join(f"<{_safe_link(url)}>" for url in links if _safe_link(url))
        )
    lines.extend(["", "## 证据定位", ""])
    for item in review.evidence:
        page = f"PDF第{item.page_number}页" if item.basis == "full_text" else "仅摘要，未验证全文"
        lines.append(
            f"- {item.evidence_id} · {page} · 文档{item.document_id or item.source_id}："
            f"{item.quote}"
        )
    return "\n".join(lines) + "\n"
