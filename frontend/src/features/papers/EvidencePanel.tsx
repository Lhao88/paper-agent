import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { Evidence } from "../../api/types";
import { ErrorNotice, Loading } from "../../components";

export function EvidencePanel({
  projectId,
  evidenceId,
  onClose,
}: {
  projectId: string;
  evidenceId: string;
  onClose: () => void;
}) {
  const close = useRef<HTMLButtonElement>(null);
  const evidence = useQuery({
    queryKey: ["evidence", projectId, evidenceId],
    queryFn: ({ signal }) =>
      api<Evidence>(`/projects/${projectId}/evidence/${evidenceId}`, {
        signal,
      }),
  });
  useEffect(() => {
    const previous = document.activeElement;
    close.current?.focus();
    const handle = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handle);
    return () => {
      window.removeEventListener("keydown", handle);
      if (previous instanceof HTMLElement) previous.focus();
    };
  }, [onClose]);
  return (
    <div className="drawer-backdrop">
      <aside
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-label="原文证据"
      >
        <div className="section-heading">
          <span className="eyebrow">SOURCE EVIDENCE</span>
          <button className="quiet" ref={close} onClick={onClose}>
            关闭 ×
          </button>
        </div>
        <h2>回到原文，核对判断。</h2>
        {evidence.isPending && <Loading />}
        <ErrorNotice error={evidence.error} />
        {evidence.data && (
          <>
            <span className="badge">
              {evidence.data.basis === "abstract"
                ? "仅摘要"
                : `PDF 第 ${evidence.data.page_number} 页`}
            </span>
            <blockquote className="source-quote">
              {evidence.data.quote}
            </blockquote>
            {evidence.data.claims?.map((claim) => (
              <p key={`${claim.column_id}-${claim.polarity}-${claim.question_id}`}>
                <span className="badge">
                  {claim.polarity === "support" ? "支持" : "反驳"}
                </span>{" "}
                {claim.value_zh}
              </p>
            ))}
            <dl className="details">
              <dt>阅读范围</dt>
              <dd>
                {evidence.data.reading_scope === "abstract_only"
                  ? "仅摘要"
                  : "定向全文阅读"}
              </dd>
              <dt>证据ID</dt>
              <dd>{evidence.data.evidence_id}</dd>
              <dt>文档版本</dt>
              <dd>{evidence.data.document_id ?? evidence.data.source_id}</dd>
            </dl>
            <p className="notice">
              原文定位可核对，结论是否被该原文支持仍需人工判断。
            </p>
            {evidence.data.document_id && (
              <a
                className="primary inline"
                target="_blank"
                rel="noreferrer"
                href={`/api/projects/${projectId}/documents/${evidence.data.document_id}/file#page=${evidence.data.page_number}`}
              >
                打开对应 PDF ↗
              </a>
            )}
            <p className="hint">若浏览器未跳转，请按页码手动定位。</p>
          </>
        )}
      </aside>
    </div>
  );
}
