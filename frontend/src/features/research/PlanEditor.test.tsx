import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PlanEditor } from "./PlanEditor";
import type { Plan } from "../../api/types";

describe("plan editor", () => {
  it("preserves edited text and submits actual question fields", () => {
    const plan: Plan = {
      topic: "检索研究",
      plan_id: "plan",
      project_id: "project",
      version: 1,
      scope: { enabled_sources: ["openalex"] },
      questions: [
        {
          question_id: "q1",
          text_zh: "问题一",
          search_terms_en: ["retrieval"],
          priority: 1,
        },
        {
          question_id: "q2",
          text_zh: "问题二",
          search_terms_en: ["evidence"],
          priority: 1,
        },
        {
          question_id: "q3",
          text_zh: "问题三",
          search_terms_en: ["evaluation"],
          priority: 2,
        },
      ],
    };
    const save = vi.fn();
    render(
      <PlanEditor
        plan={plan}
        busy={false}
        error="版本冲突，请刷新后重试"
        onApprove={save}
      />,
    );
    fireEvent.change(screen.getByLabelText("研究问题 1"), {
      target: { value: "新的研究问题" },
    });
    fireEvent.click(screen.getByRole("button", { name: "确认计划并开始研究" }));
    expect(save.mock.calls[0][0].questions[0].text_zh).toBe("新的研究问题");
    expect(screen.getByDisplayValue("新的研究问题")).toBeInTheDocument();
  });

  it("submits an added exclusion rule with the spec", () => {
    const plan: Plan = {
      topic: "检索研究",
      plan_id: "plan",
      project_id: "project",
      version: 1,
      scope: { enabled_sources: ["openalex"] },
      questions: [
        { question_id: "q1", text_zh: "问题一", search_terms_en: ["retrieval"], priority: 1 },
        { question_id: "q2", text_zh: "问题二", search_terms_en: ["evidence"], priority: 1 },
        { question_id: "q3", text_zh: "问题三", search_terms_en: ["evaluation"], priority: 2 },
      ],
    };
    const save = vi.fn();
    render(
      <PlanEditor
        plan={plan}
        busy={false}
        spec={{
          topic: "检索研究",
          questions: plan.questions,
          scope: { enabled_sources: ["openalex"] },
          inclusion_rules: [{ rule_id: "r1", polarity: "include", text_zh: "纳入方法论文" }],
          columns: [
            {
              column_id: "c1",
              question_id: "q1",
              field: "method",
              required: true,
              description_zh: "方法",
            },
          ],
          coverage: [{ question_id: "q1", min_included_papers: 1, required_column_ids: ["c1"] }],
        }}
        onApprove={save}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "添加排除规则" }));
    fireEvent.change(screen.getByLabelText("排除规则 1"), {
      target: { value: "排除与主题无关的论文" },
    });
    fireEvent.click(screen.getByRole("button", { name: "确认规格并开始研究" }));
    expect(save.mock.calls[0][1].inclusion_rules[1]).toMatchObject({
      polarity: "exclude",
      text_zh: "排除与主题无关的论文",
    });
    expect(screen.getByText(/q1 至少 1 篇/)).toBeInTheDocument();
  });
});
