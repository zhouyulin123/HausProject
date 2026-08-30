import { describe, expect, it, vi } from "vitest";
import { importWithRetry } from "./lazyImport";

describe("importWithRetry", () => {
  it("retries a transient dynamic import failure and returns the module", async () => {
    const module = { default: "FurniturePage" };
    const importer = vi
      .fn<() => Promise<typeof module>>()
      .mockRejectedValueOnce(
        new TypeError("Failed to fetch dynamically imported module"),
      )
      .mockResolvedValue(module);
    const wait = vi.fn(async () => undefined);

    await expect(
      importWithRetry(importer, { delaysMs: [20], wait }),
    ).resolves.toBe(module);
    expect(importer).toHaveBeenCalledTimes(2);
    expect(wait).toHaveBeenCalledWith(20);
  });

  it("does not retry a page implementation error", async () => {
    const error = new Error("FurniturePage render failed");
    const importer = vi.fn<() => Promise<never>>().mockRejectedValue(error);
    const wait = vi.fn(async () => undefined);

    await expect(
      importWithRetry(importer, { delaysMs: [20, 40], wait }),
    ).rejects.toBe(error);
    expect(importer).toHaveBeenCalledTimes(1);
    expect(wait).not.toHaveBeenCalled();
  });

  it("stops after the configured transient retries", async () => {
    const error = new TypeError(
      "Failed to fetch dynamically imported module: /src/pages/FurniturePage.tsx",
    );
    const importer = vi.fn<() => Promise<never>>().mockRejectedValue(error);
    const wait = vi.fn(async () => undefined);

    await expect(
      importWithRetry(importer, { delaysMs: [20, 40], wait }),
    ).rejects.toBe(error);
    expect(importer).toHaveBeenCalledTimes(3);
    expect(wait).toHaveBeenNthCalledWith(1, 20);
    expect(wait).toHaveBeenNthCalledWith(2, 40);
  });
});
