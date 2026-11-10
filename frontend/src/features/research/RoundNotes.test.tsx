import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RoundNotes } from "./RoundNotes";

describe("round notes", () => {
  it("shows two rounds and the unmet questions", () => {
    render(
      <RoundNotes
        unmet={["q2"]}
        pages={[
          {
            round_index: 0,
            executed_action_ids: ["search-0"],
            rejected_actions: [],
            new_paper_ids: [],
            filled_column_ids: ["c1"],
            open_gaps: ["q2"],
            index_mode: "hybrid",
          },
          {
            round_index: 1,
            executed_action_ids: ["search-1"],
            rejected_actions: [{ action_id: "stop-1", reason: "unmet_coverage" }],
            new_paper_ids: [],
            filled_column_ids: [],
            open_gaps: ["q2"],
            index_mode: "hybrid",
          },
        ]}
      />,
    );
    expect(screen.getByRole("heading", { name: "第 1 轮" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "第 2 轮" })).toBeInTheDocument();
    expect(screen.getByText("未满足问题：q2")).toBeInTheDocument();
    expect(screen.getByText(/stop-1（unmet_coverage）/)).toBeInTheDocument();
  });
});