import type { NotebookPage } from "../../api/types";

export function RoundNotes({
  pages,
  unmet,
}: {
  pages: NotebookPage[];
  unmet: string[];
}) {
  return (
    <section className="panel">
      <div className="section-heading">
        <h2>研究轮次</h2>
        <span className="eyebrow">{pages.length} 页笔记</span>
      </div>
      <p>未满足问题：{unmet.length ? unmet.join("、") : "无"}</p>
      {pages.map((page) => (
        <article key={page.round_index}>
          <h3>第 {page.round_index + 1} 轮</h3>
          <p>已执行：{page.executed_action_ids.join("、") || "无"}</p>
          <p>
            被拒：
            {page.rejected_actions.length
              ? page.rejected_actions
                  .map((item) => `${item.action_id ?? ""}（${item.reason ?? ""}）`)
                  .join("、")
              : "无"}
          </p>
          <p>本轮缺口：{page.open_gaps.join("、") || "无"}</p>
        </article>
      ))}
    </section>
  );
}
