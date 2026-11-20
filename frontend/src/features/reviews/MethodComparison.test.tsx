import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MethodComparison } from "./ReviewReader";

describe("method comparison", () => {
  it("keeps opposite polarity as two rows", () => {
    render(
      <MethodComparison
        rows={[
          {
            paper_id: "paper-1",
            column_id: "c1",
            polarity: "support",
            quote: "原文支持句",
            evidence_id: "evidence-support",
          },
          {
            paper_id: "paper-1",
            column_id: "c1",
            polarity: "contradict",
            quote: "原文反驳句",
            evidence_id: "evidence-contradict",
          },
        ]}
      />,
    );
    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(2);
    expect(screen.getByText("support")).toBeInTheDocument();
    expect(screen.getByText("contradict")).toBeInTheDocument();
    expect(screen.getByText("原文支持句")).toBeInTheDocument();
    expect(screen.getByText("原文反驳句")).toBeInTheDocument();
  });
});
