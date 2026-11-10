import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Claim } from "./ReviewReader";

describe("review claims", () => {
  it("opens the exact evidence ID and does not execute raw HTML", () => {
    const open = vi.fn();
    const { container } = render(
      <Claim
        block={{
          block_id: "b1",
          text: "<script>bad()</script>正常内容",
          evidence_ids: ["evidence-1"],
          citation_numbers: [1],
          kind: "literature_claim",
        }}
        onEvidence={open}
      />,
    );
    expect(container.querySelector("script")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "查看证据 1" }));
    expect(open).toHaveBeenCalledWith("evidence-1");
  });
});
