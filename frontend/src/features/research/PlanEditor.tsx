import { useState } from "react";
import type { Plan, PlanDraft, ResearchSpec } from "../../api/types";

const fields = [
  "method",
  "dataset",
  "experimental_setup",
  "metric",
  "result",
  "limitation",
] as const;

export type KnownPaper = { paper_id: string; title: string };
export type PaperDecision = { paper_id: string; decision: "pin" | "exclude" };

export function PlanEditor({
  plan,
  spec,
  knownPapers = [],
  busy,
  error,
  onApprove,
}: {
  plan: Plan;
  spec?: ResearchSpec | null;
  knownPapers?: KnownPaper[];
  busy: boolean;
  error?: string;
  onApprove: (
    draft: PlanDraft,
    spec?: ResearchSpec,
    decisions?: PaperDecision[],
  ) => void;
}) {
  const [researchSpec, setResearchSpec] = useState<ResearchSpec | null>(
    spec ?? null,
  );
  const [paperDecisions, setPaperDecisions] = useState<
    Record<string, "pin" | "exclude">
  >({});
  const [draft, setDraft] = useState<PlanDraft>({
    topic: plan.topic,
    questions: plan.questions,
    scope: plan.scope,
    assumptions: plan.assumptions,
    suggested_budgets: plan.suggested_budgets,
  });
  return (
    <section className="panel plan-editor">
      <div className="section-heading">
        <div>
          <span className="eyebrow">RESEARCH PLAN · V{plan.version}</span>
          <h2>先确定问题，再开始检索。</h2>
        </div>
        <span className="badge amber">等待确认</span>
      </div>
      <p className="muted">
        可以调整研究问题和检索词。确认后冻结本次范围，后续修改需创建新的研究。
      </p>
      {draft.questions.map((question, index) => (
        <div className="question-row" key={question.question_id}>
          <span className="index">Q{index + 1}</span>
          <div>
            <label>
              研究问题 {index + 1}
              <textarea
                rows={2}
                value={question.text_zh}
                required
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    questions: draft.questions.map((q, i) =>
                      i === index ? { ...q, text_zh: event.target.value } : q,
                    ),
                  })
                }
              />
            </label>
            <label className="small-label">
              英文检索词
              <input
                value={question.search_terms_en.join(", ")}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    questions: draft.questions.map((q, i) =>
                      i === index
                        ? {
                            ...q,
                            search_terms_en: event.target.value
                              .split(",")
                              .map((term) => term.trim())
                              .filter(Boolean),
                          }
                        : q,
                    ),
                  })
                }
              />
            </label>
          </div>
        </div>
      ))}
      <div className="field-pair">
        <label>
          起始年份
          <input
            aria-label="起始年份"
            type="number"
            min={1800}
            max={2200}
            value={draft.scope.year_from ?? ""}
            onChange={(e) =>
              setDraft({
                ...draft,
                scope: {
                  ...draft.scope,
                  year_from: e.target.value ? Number(e.target.value) : null,
                },
              })
            }
          />
        </label>
        <label>
          截止年份
          <input
            aria-label="截止年份"
            type="number"
            min={1800}
            max={2200}
            value={draft.scope.year_to ?? ""}
            onChange={(e) =>
              setDraft({
                ...draft,
                scope: {
                  ...draft.scope,
                  year_to: e.target.value ? Number(e.target.value) : null,
                },
              })
            }
          />
        </label>
      </div>
      {researchSpec && (
        <SpecFields spec={researchSpec} onChange={setResearchSpec} />
      )}
      <p className="hint">
        来源：{draft.scope.enabled_sources?.join("、")} ·{" "}
        {plan.assumptions?.join("；")}
      </p>
      {knownPapers.length > 0 && (
        <div>
          <h3>确认前的已知论文</h3>
          {knownPapers.map((paper) => (
            <div className="question-row" key={paper.paper_id}>
              <span>{paper.title}</span>
              <button
                className="quiet"
                type="button"
                onClick={() =>
                  setPaperDecisions((current) => ({
                    ...current,
                    [paper.paper_id]: "pin",
                  }))
                }
              >
                钉住 {paper.title}
              </button>
              <button
                className="quiet"
                type="button"
                onClick={() =>
                  setPaperDecisions((current) => ({
                    ...current,
                    [paper.paper_id]: "exclude",
                  }))
                }
              >
                排除 {paper.title}
              </button>
            </div>
          ))}
        </div>
      )}
      {error && (
        <div role="alert" className="notice error">
          {error}
        </div>
      )}
      <button
        className="primary"
        disabled={
          busy ||
          draft.questions.some(
            (q) => !q.text_zh.trim() || !q.search_terms_en.length,
          ) ||
          Boolean(
            researchSpec &&
              (researchSpec.inclusion_rules.some((rule) => !rule.text_zh.trim()) ||
                researchSpec.columns.some((column) => !column.description_zh.trim())),
          )
        }
        onClick={() =>
          onApprove(
            draft,
            researchSpec ?? undefined,
            knownPapers.flatMap((paper) => {
              const decision = paperDecisions[paper.paper_id];
              return decision
                ? [{ paper_id: paper.paper_id, decision }]
                : [];
            }),
          )
        }
      >
        {busy
          ? "正在确认…"
          : researchSpec
            ? "确认规格并开始研究"
            : "确认计划并开始研究"}
      </button>
    </section>
  );
}

function SpecFields({
  spec,
  onChange,
}: {
  spec: ResearchSpec;
  onChange: (spec: ResearchSpec) => void;
}) {
  const removeColumn = (columnId: string) => {
    const coverage = spec.coverage.map((target) => ({
      ...target,
      required_column_ids: target.required_column_ids.filter((id) => id !== columnId),
    }));
    if (coverage.some((target) => target.required_column_ids.length === 0)) return;
    onChange({
      ...spec,
      columns: spec.columns.filter((column) => column.column_id !== columnId),
      coverage,
    });
  };
  return (
    <div>
      <h3>纳入与排除</h3>
      {spec.inclusion_rules.map((rule, index) => {
        const sameKind = spec.inclusion_rules
          .slice(0, index + 1)
          .filter((item) => item.polarity === rule.polarity).length;
        const label = `${rule.polarity === "exclude" ? "排除规则" : "纳入规则"} ${sameKind}`;
        return (
        <div className="question-row" key={rule.rule_id}>
          <label>
            {label}
            <input
              aria-label={label}
              value={rule.text_zh}
              onChange={(event) =>
                onChange({
                  ...spec,
                  inclusion_rules: spec.inclusion_rules.map((item, itemIndex) =>
                    itemIndex === index ? { ...item, text_zh: event.target.value } : item,
                  ),
                })
              }
            />
          </label>
          <button
            className="quiet"
            type="button"
            onClick={() =>
              onChange({
                ...spec,
                inclusion_rules: spec.inclusion_rules.filter(
                  (item) => item.rule_id !== rule.rule_id,
                ),
              })
            }
            disabled={spec.inclusion_rules.length === 1}
          >
            删除规则
          </button>
        </div>
        );
      })}
      <button
        className="quiet"
        type="button"
        onClick={() =>
          onChange({
            ...spec,
            inclusion_rules: [
              ...spec.inclusion_rules,
              {
                rule_id: `r-extra-${spec.inclusion_rules.length + 1}`,
                polarity: "exclude",
                text_zh: "",
              },
            ],
          })
        }
      >
        添加排除规则
      </button>
      <h3>抽取列</h3>
      {spec.columns.map((column) => (
        <div className="question-row" key={column.column_id}>
          <label>
            抽取列 {column.column_id}
            <input
              aria-label={`抽取列 ${column.column_id}`}
              value={column.description_zh}
              onChange={(event) =>
                onChange({
                  ...spec,
                  columns: spec.columns.map((item) =>
                    item.column_id === column.column_id
                      ? { ...item, description_zh: event.target.value }
                      : item,
                  ),
                })
              }
            />
          </label>
          <label>
            问题
            <select
              aria-label={`抽取列问题 ${column.column_id}`}
              value={column.question_id}
              onChange={(event) =>
                onChange({
                  ...spec,
                  columns: spec.columns.map((item) =>
                    item.column_id === column.column_id
                      ? { ...item, question_id: event.target.value }
                      : item,
                  ),
                })
              }
            >
              {spec.questions.map((question) => (
                <option key={question.question_id} value={question.question_id}>
                  {question.question_id}
                </option>
              ))}
            </select>
          </label>
          <label>
            字段
            <select
              aria-label={`抽取列字段 ${column.column_id}`}
              value={column.field}
              onChange={(event) =>
                onChange({
                  ...spec,
                  columns: spec.columns.map((item) =>
                    item.column_id === column.column_id
                      ? {
                          ...item,
                          field: event.target.value as (typeof fields)[number],
                        }
                      : item,
                  ),
                })
              }
            >
              {fields.map((field) => (
                <option key={field} value={field}>
                  {field}
                </option>
              ))}
            </select>
          </label>
          <button className="quiet" type="button" onClick={() => removeColumn(column.column_id)}>
            删除抽取列
          </button>
        </div>
      ))}
      <button
        className="quiet"
        type="button"
        onClick={() =>
          onChange({
            ...spec,
            columns: [
              ...spec.columns,
              {
                column_id: `c-extra-${spec.columns.length + 1}`,
                question_id: spec.questions[0]?.question_id ?? "q1",
                field: "method",
                required: false,
                description_zh: "补充抽取列",
              },
            ],
          })
        }
      >
        添加抽取列
      </button>
      <h3>覆盖目标</h3>
      {spec.coverage.map((target) => (
        <p key={target.question_id}>
          {target.question_id} 至少 {target.min_included_papers} 篇，必填列{" "}
          {target.required_column_ids.join("、")}
        </p>
      ))}
    </div>
  );
}
