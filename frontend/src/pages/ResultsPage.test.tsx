import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { emptyRequirement } from "@/types/requirement";

const api = vi.hoisted(() => ({
  generateDesigns: vi.fn(),
  restoreCurrentDesigns: vi.fn(),
}));

vi.mock("@/api/designApi", () => api);

import {
  ResultsLoadError,
  loadResultsPlans,
} from "./ResultsPage";

describe("方案结果恢复", () => {
  beforeEach(() => {
    api.generateDesigns.mockReset();
    api.restoreCurrentDesigns.mockReset();
  });

  it("恢复失败时保留错误，不静默创建新任务", async () => {
    api.restoreCurrentDesigns.mockRejectedValueOnce(new Error("network unavailable"));

    await expect(loadResultsPlans(emptyRequirement, () => false)).rejects.toThrow(
      "network unavailable",
    );
    expect(api.generateDesigns).not.toHaveBeenCalled();
  });

  it("仅在恢复明确返回 null 时创建新任务", async () => {
    api.restoreCurrentDesigns.mockResolvedValueOnce(null);
    api.generateDesigns.mockResolvedValueOnce([]);

    await expect(loadResultsPlans(emptyRequirement, () => false)).resolves.toEqual([]);
    expect(api.generateDesigns).toHaveBeenCalledTimes(1);
    expect(api.generateDesigns).toHaveBeenCalledWith(emptyRequirement);
  });

  it("恢复返回空数组时也不创建新任务", async () => {
    api.restoreCurrentDesigns.mockResolvedValueOnce([]);

    await expect(loadResultsPlans(emptyRequirement, () => false)).resolves.toEqual([]);
    expect(api.generateDesigns).not.toHaveBeenCalled();
  });

  it("StrictMode 清理发生在恢复完成前时不继续创建任务", async () => {
    api.restoreCurrentDesigns.mockResolvedValueOnce(null);

    await expect(loadResultsPlans(emptyRequirement, () => true)).resolves.toBeUndefined();
    expect(api.generateDesigns).not.toHaveBeenCalled();
  });

  it("显示明确恢复错误并由用户按钮触发重试", () => {
    const retry = vi.fn();
    const element = ResultsLoadError({ onRetry: retry });
    const html = renderToStaticMarkup(element);

    expect(html).toContain("历史方案恢复失败");
    expect(html).toContain("不会自动创建新任务");
    expect(html).toContain("重新恢复");

    const children = element.props.children as Array<React.ReactElement>;
    const retryButton = children.find((child) => child.type === "button");
    expect(retryButton).toBeDefined();
    retryButton?.props.onClick();
    expect(retry).toHaveBeenCalledTimes(1);
  });
});
