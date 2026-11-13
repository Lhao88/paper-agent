import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api/client";
import { ResearchPage } from "./ResearchPage";

vi.mock("../../api/client", () => ({
  api: vi.fn(),
  errorText: (error: unknown) => String(error),
  post: vi.fn(),
}));

const projectId = "project-1";
const runId = "run-1";

describe("research page rounds", () => {
  beforeEach(() => {
    vi.mocked(api).mockImplementation((path: string) => {
      if (path === `/projects/${projectId}/reviews`) return Promise.resolve([]);
      if (path === `/projects/${projectId}`) {
        return Promise.resolve({
          id: projectId,
          title: "覆盖研究",
          topic: "图神经网络",
          runs: [{ id: runId }],
        });
      }
      if (path === `/runs/${runId}/notebook`) {
        return Promise.resolve({
          unmet_question_ids: ["q2"],
          pages: [
            {
              round_index: 1,
              executed_action_ids: ["search-1"],
              rejected_actions: [{ action_id: "stop-1", reason: "unmet_coverage" }],
              new_paper_ids: [],
              filled_column_ids: [],
              open_gaps: ["q2"],
              index_mode: "hybrid",
            },
            {
              round_index: 0,
              executed_action_ids: ["search-0"],
              rejected_actions: [],
              new_paper_ids: [],
              filled_column_ids: ["c1"],
              open_gaps: ["q2"],
              index_mode: "hybrid",
            },
          ],
        });
      }
      if (path === `/runs/${runId}`) {
        return Promise.resolve({
          id: runId,
          status: "running",
          stage: "note",
          plan_id: null,
          used_calls: 1,
          max_calls: 10,
          used_tokens: 0,
          reserved_tokens: 0,
          used_source_requests: 1,
          active_elapsed_seconds: 3,
          unknown_calls: 0,
          suspected_interruption: false,
          error_json: null,
          config_snapshot: { llm_mode: "mock" },
          counts: { screening: 1, reading: 0 },
        });
      }
      return Promise.resolve([]);
    });
  });

  it("shows executed, rejected, and unmet items in round order while the run is still going", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[`/projects/${projectId}/research`]}>
          <Routes>
            <Route path="/projects/:projectId/research" element={<ResearchPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("heading", { name: "第 1 轮" })).toBeInTheDocument();
    const text = document.body.textContent ?? "";
    expect(text.indexOf("第 1 轮")).toBeLessThan(text.indexOf("第 2 轮"));
    expect(text.indexOf("已执行：search-0")).toBeLessThan(text.indexOf("已执行：search-1"));
    expect(screen.getByText("未满足问题：q2")).toBeInTheDocument();
    expect(screen.getByText(/stop-1（unmet_coverage）/)).toBeInTheDocument();
  });
});
