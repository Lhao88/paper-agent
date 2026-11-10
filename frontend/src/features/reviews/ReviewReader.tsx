import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, post } from "../../api/client";
import type { ClaimBlock, ReviewView } from "../../api/types";
import { ErrorNotice, Loading } from "../../components";
import { EvidencePanel } from "../papers/EvidencePanel";

export function Claim({
  block,
  onEvidence,
  numbers = {},
}: {
  block: ClaimBlock;
  onEvidence: (id: string) => void;
  numbers?: Record<string, number>;
}) {
  return (
    <div className={`claim ${block.kind}`} id={`block-${block.block_id}`}>
      {block.kind === "hypothesis" && (
        <span className="badge amber">待验证假设</span>
      )}
      <Markdown remarkPlugins={[remarkGfm]} skipHtml>
        {block.text}
      </Markdown>
      <div className="claim-citations">
        {block.evidence_ids.map((id, i) => (
          <button
            className="cite"
            key={id}
            aria-label={`查看证据 ${i + 1}`}
            onClick={() => onEvidence(id)}
          >
            [{numbers[id] ?? block.citation_numbers[i] ?? i + 1}] 原文
          </button>
        ))}
      </div>
    </div>
  );
}

export function ReviewReader() {
  const { projectId = "", artifactId = "" } = useParams();
  const [evidenceId, setEvidenceId] = useState("");
  const [editing, setEditing] = useState(false);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const navigate = useNavigate();
  const client = useQueryClient();
  const result = useQuery({
    queryKey: ["review", projectId, artifactId],
    queryFn: ({ signal }) =>
      api<ReviewView>(`/projects/${projectId}/reviews/${artifactId}`, {
        signal,
      }),
  });
  const save = useMutation({
    mutationFn: () =>
      post<{ id: string }>(
        `/projects/${projectId}/reviews/${artifactId}/edits`,
        { base_version: result.data?.version, edited_blocks: edits },
      ),
    onSuccess: (value) => {
      setEditing(false);
      setEdits({});
      void client.invalidateQueries({ queryKey: ["reviews", projectId] });
      void navigate(`/projects/${projectId}/reviews/${value.id}`);
    },
  });
  if (result.isPending) return <Loading />;
  if (!result.data) return <ErrorNotice error={result.error} />;
  const { review } = result.data;
  const referenceNumbers = new Map(
    review.references.map((ref) => [ref.paper_id, ref.number]),
  );
  const numbers = Object.fromEntries(
    review.evidence.map((item) => [
      item.evidence_id,
      referenceNumbers.get(item.paper_id) ?? 0,
    ]),
  );
  return (
    <>
      <header className="page-heading compact">
        <div>
          <span className="eyebrow">
            LITERATURE REVIEW · V{result.data.version}
          </span>
          <h1>{review.topic}</h1>
          <p>
            生成于 {new Date(review.generated_at).toLocaleString("zh-CN")} ·{" "}
            {result.data.origin === "review_edit"
              ? "用户编辑，需重新核验"
              : "AI 辅助综述，待人工核验"}
          </p>
        </div>
        <div className="actions">
          <Link className="quiet" to={`/projects/${projectId}/research`}>
            返回研究
          </Link>
          <a
            className="primary inline"
            href={`/api/projects/${projectId}/reviews/${artifactId}/export`}
          >
            导出 Markdown ↓
          </a>
        </div>
      </header>
      <div className="review-grid">
        <nav className="outline" aria-label="综述目录">
          <span className="eyebrow">CONTENTS</span>
          {review.sections.map((section, i) => (
            <a href={`#${section.section_id}`} key={section.section_id}>
              <small>{String(i + 1).padStart(2, "0")}</small>
              {section.title}
            </a>
          ))}
          <a href="#references">参考文献</a>
          <button className="quiet" onClick={() => setEditing(!editing)}>
            {editing ? "返回阅读" : "编辑当前版本"}
          </button>
        </nav>
        <article className="review-content">
          <details className="notice limitations">
            <summary>范围、覆盖局限与核验状态</summary>
            <ul>
              {review.limitations.map((text, i) => (
                <li key={i}>{text}</li>
              ))}
            </ul>
          </details>
          <p className="hint">
            引用存在性和文档位置可核对；语义支持尚未完成人工验证。
          </p>
          {review.sections.map((section) => (
            <section id={section.section_id} key={section.section_id}>
              <span className="eyebrow">RESEARCH FINDINGS</span>
              <h2>{section.title}</h2>
              {section.blocks.map((block) =>
                editing ? (
                  <label className="edit-block" key={block.block_id}>
                    编辑段落
                    <textarea
                      aria-label="编辑段落"
                      rows={5}
                      value={edits[block.block_id] ?? block.text}
                      onChange={(e) =>
                        setEdits({ ...edits, [block.block_id]: e.target.value })
                      }
                    />
                    <span className="hint">
                      证据关联保留，改写后需重新核对支持关系。
                    </span>
                  </label>
                ) : (
                  <Claim
                    key={block.block_id}
                    block={block}
                    numbers={numbers}
                    onEvidence={setEvidenceId}
                  />
                ),
              )}
              {section.unresolved_questions.length > 0 && (
                <div className="research-gap">
                  <strong>仍待解决</strong>
                  <ul>
                    {section.unresolved_questions.map((question, i) => (
                      <li key={i}>{question}</li>
                    ))}
                  </ul>
                </div>
              )}
            </section>
          ))}
          {editing && (
            <div className="panel">
              <ErrorNotice error={save.error} />
              <button
                className="primary"
                disabled={save.isPending || !Object.keys(edits).length}
                onClick={() => save.mutate()}
              >
                {save.isPending ? "正在保存…" : "另存为新版本"}
              </button>
              <p className="hint">
                遇到版本冲突时保留当前文本，请先在另一标签页读取最新版本。
              </p>
            </div>
          )}
          <section id="references">
            <h2>参考文献</h2>
            {review.references.map((ref) => (
              <div className="reference" key={ref.paper_id}>
                <span>[{ref.number}]</span>
                <div>
                  <strong>{ref.title}</strong>
                  <p>
                    {ref.authors.join(", ") || "作者未提供"} ·{" "}
                    {ref.year ?? "年份未提供"}
                  </p>
                  {ref.doi && (
                    <a
                      target="_blank"
                      rel="noreferrer"
                      href={`https://doi.org/${encodeURI(ref.doi)}`}
                    >
                      DOI ↗
                    </a>
                  )}
                </div>
              </div>
            ))}
          </section>
        </article>
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
