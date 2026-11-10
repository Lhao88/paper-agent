import { describe, expect, it } from "vitest";
import { pollingInterval, relevanceLabel } from "./status";

describe("honest research status", () => {
  it("distinguishes missing information and zero score", () => {
    expect(relevanceLabel(null)).toBe("信息不足");
    expect(relevanceLabel(0)).toBe("0 / 4");
  });
  it("stops polling after a terminal state", () => {
    expect(pollingInterval("completed")).toBe(false);
    expect(pollingInterval("partial")).toBe(false);
    expect(pollingInterval("running")).toBe(2000);
  });
});
