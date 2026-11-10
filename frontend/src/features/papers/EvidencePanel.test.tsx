import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api/client";
import { EvidencePanel } from "./EvidencePanel";

vi.mock("../../api/client", () => ({ api: vi.fn() }));

describe("evidence panel", () => {
  beforeEach(() => {
    vi.mocked(api).mockResolvedValue({
      evidence_id: "evidence-1",
      paper_id: "paper-1",
      basis: "full_text",
      quote: "ToyCorpus",
      quote_start: 0,
      quote_end: 9,
      page_number: 1,
      statement_type: "reported_fact",
      reading_scope: "full_text_targeted",
      claims: [
        {
          polarity: "support",
          question_id: "q1",
          column_id: "c1",
          value_zh: "使用图检索方法",
        },
        {
          polarity: "contradict",
          question_id: "q2",
          column_id: "c2",
          value_zh: "该结论被另一篇论文否定",
        },
      ],
    });
  });

  it("distinguishes support from contradict", async () => {
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <EvidencePanel projectId="project" evidenceId="evidence-1" onClose={() => undefined} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("支持")).toBeInTheDocument();
    expect(screen.getByText("反驳")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("ToyCorpus")).toBeInTheDocument());
  });
});