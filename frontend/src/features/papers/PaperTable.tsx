import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { PaperDetails, PaperPage } from "../../api/types";
import { Empty, ErrorNotice, Loading } from "../../components";
import { relevanceLabel } from "../research/status";
import { EvidencePanel } from "./EvidencePanel";

const fieldNames: Record<string, string> = {
  research_question: "研究问题",
  method: "方法",
  dataset: "数据集",
  result: "结果",
  metric: "指标",
  limitation: "局限",
  abstract_background: "摘要背景",
  experimental_setup: "实验设置",
};

export function PaperTable() {
  const { projectId = "" } = useParams();
  const [cursor, setCursor] = useState<string | null>(null);
  const [paperId, setPaperId] = useState("");
  const [evidenceId, setEvidenceId] = useState("");
  const [uploadTitle, setUploadTitle] = useState("用户上传资料");
  const client = useQueryClient();
  const papers = useQuery({
    queryKey: ["papers", projectId, cursor],
    queryFn: ({ signal }) =>
      api<PaperPage>(
        `/projects/${projectId}/papers?limit=20${cursor ? `&cursor=${cursor}` : ""}`,
        { signal },
      ),
  });
  const detail = useQuery({
    queryKey: ["paper", projectId, paperId],
    queryFn: ({ signal }) =>
      api<PaperDetails>(`/projects/${projectId}/papers/${paperId}`, { signal }),
    enabled: !!paperId,
  });
  const choose = useMutation({
    mutationFn: (decision: string | null) =>
      api(`/projects/${projectId}/papers/${paperId}`, {
        method: "PATCH",
        body: JSON.stringify({
          expected_version: detail.data?.selection.version,
          user_decision: decision,
        }),
      }),
    onSuccess: () => {
      void client.invalidateQueries({
        queryKey: ["paper", projectId, paperId],
      });
      void client.invalidateQueries({ queryKey: ["papers", projectId] });
    },
  });
  const upload = useMutation({
    mutationFn: (file: File) => {
      const body = new FormData();
      body.set("file", file);
      body.set("display_title", uploadTitle);
      return api(`/projects/${projectId}/documents`, { method: "POST", body });
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["papers", projectId] });
    },
  });
  return (
    <>
      <header className="page-heading compact">
        <div>
          <span className="eyebrow">LITERATURE LIBRARY</span>
          <h1>文献与证据</h1>
          <p>保留原始摘要、筛选理由与实际阅读范围。</p>
        </div>
        <Link className="quiet" to={`/projects/${projectId}/research`}>
          返回研究概览 ↗
        </Link>
      </header>
      <details className="panel upload">
        <summary>添加本地 PDF</summary>
        <p className="hint">
          上传仅保存到此项目。点击“选择精读”后，才会在尚未开始精读的研究或后续研究中送入模型。
        </p>
        <label>
          资料显示标题
          <input
            value={uploadTitle}
            onChange={(e) => setUploadTitle(e.target.value)}
            maxLength={300}
          />
        </label>
        <label className="file-input">
          选择 PDF 文件
          <input
            type="file"
            accept="application/pdf,.pdf"
            disabled={upload.isPending}
            onChange={(e) => {
              if (e.target.files?.[0]) upload.mutate(e.target.files[0]);
              e.target.value = "";
            }}
          />
        </label>
        <ErrorNotice error={upload.error} />
        {upload.isSuccess && <p role="status">资料已保存，尚未发送给模型。</p>}
      </details>
      <div className="library-grid">
        <section className="paper-list">
          <div className="section-heading">
            <h2>项目资料</h2>
            <button className="quiet" onClick={() => void papers.refetch()}>
              刷新
            </button>
          </div>
          <ErrorNotice error={papers.error} />
          {papers.isPending && <Loading />}
          {papers.data?.items.length === 0 && (
            <Empty title="还没有文献">
              确认研究计划后，检索结果会进入这里。也可以添加本地 PDF。
            </Empty>
          )}
          {papers.data?.items.map((paper, index) => (
            <button
              key={paper.id}
              className={`paper-row ${paperId === paper.id ? "selected" : ""}`}
              onClick={() => {
                setPaperId(paper.id);
                choose.reset();
              }}
            >
              <span className="index">
                {String(index + 1).padStart(2, "0")}
              </span>
              <div>
                <h3>{paper.title}</h3>
                <p>
                  {paper.year ?? "年份未提供"} ·{" "}
                  {paper.authors_json.slice(0, 2).join(", ") || "作者待补充"}
                </p>
                <span className="badge">
                  {paper.selection.user_decision === "include"
                    ? "人工选择精读"
                    : paper.selection.user_decision === "exclude"
                      ? "人工排除"
                      : "查看筛选与阅读情况"}
                </span>
              </div>
            </button>
          ))}
          <div className="actions">
            {cursor && (
              <button className="quiet" onClick={() => setCursor(null)}>
                回到首页
              </button>
            )}
            {papers.data?.next_cursor && (
              <button
                className="quiet"
                onClick={() => setCursor(papers.data!.next_cursor)}
              >
                下一页 →
              </button>
            )}
          </div>
        </section>
        <aside className="paper-detail panel">
          {!paperId && (
            <Empty title="选择一篇文献">
              摘要概括与原始摘要分别保存。只有入选资料才进行全文精读。
            </Empty>
          )}
          {detail.isFetching && <Loading />}
          <ErrorNotice error={detail.error} />
          {detail.data && (
            <>
              <span className="eyebrow">PAPER NOTES</span>
              <h2>{detail.data.title}</h2>
              <div className="actions">
                <button
                  className="primary"
                  disabled={choose.isPending}
                  onClick={() => choose.mutate("include")}
                >
                  选择精读
                </button>
                <button
                  className="quiet"
                  disabled={choose.isPending}
                  onClick={() => choose.mutate("exclude")}
                >
                  排除
                </button>
                <button
                  className="quiet"
                  disabled={choose.isPending}
                  onClick={() => choose.mutate(null)}
                >
                  恢复自动
                </button>
              </div>
              <ErrorNotice error={choose.error} />
              <p className="hint">
                已开始精读的研究保持原版本，新的选择供后续运行使用。
              </p>
              <h3>摘要初读</h3>
              {detail.data.screen_cards[0] ? (
                <>
                  <span className="badge">
                    相关性{" "}
                    {relevanceLabel(detail.data.screen_cards[0].relevance)}
                  </span>
                  <p>{detail.data.screen_cards[0].summary_zh}</p>
                  <p className="hint">
                    筛选理由：{detail.data.screen_cards[0].reason}
                  </p>
                </>
              ) : (
                <p className="muted">尚未初读</p>
              )}
              <h3>原始摘要与来源</h3>
              {detail.data.sources.map((source) => (
                <details key={source.id}>
                  <summary>
                    {source.provider} · {source.version_label.slice(0, 16)}
                  </summary>
                  <p className="original-abstract">
                    {source.abstract_text || "来源未提供原始摘要，信息不足。"}
                  </p>
                </details>
              ))}
              <h3>精读笔记</h3>
              {!detail.data.reading_cards.length && (
                <p className="muted">
                  尚无精读结果。选择精读不会立即触发收费调用，将由研究流程按预算执行。
                </p>
              )}
              {detail.data.reading_cards.map((card, index) => (
                <div
                  className="reading-note"
                  key={`${card.document_id}-${index}`}
                >
                  <span className="badge">
                    {card.reading_scope === "abstract_only"
                      ? "仅摘要"
                      : card.reading_scope === "full_text_complete"
                        ? "全文完整阅读"
                        : "定向精读"}
                  </span>
                  {Object.entries(card.fields).map(([field, facts]) => (
                    <div key={field}>
                      <h4>{fieldNames[field] ?? field}</h4>
                      {facts.map((fact, i) => (
                        <p key={i}>
                          {fact.value_zh}{" "}
                          {fact.evidence_ids.map((id) => (
                            <button
                              className="cite"
                              key={id}
                              onClick={() => setEvidenceId(id)}
                            >
                              原文证据
                            </button>
                          ))}
                        </p>
                      ))}
                    </div>
                  ))}
                  <details>
                    <summary>未获取字段与阅读限制</summary>
                    <p className="hint">
                      {Object.entries(card.missing_fields)
                        .map(([field, why]) => `${field}: ${why}`)
                        .join("；")}
                    </p>
                    <p className="hint">{card.warnings.join("；")}</p>
                  </details>
                </div>
              ))}
            </>
          )}
        </aside>
      </div>
      {evidenceId && (
        <EvidencePanel
          projectId={projectId}
          evidenceId={evidenceId}
          onClose={() => setEvidenceId("")}
        />
      )}
    </>
  );
}
