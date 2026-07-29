import { describe, expect, it } from "vitest";
import {
  readImageIds,
  readTaskId,
  writeImageIds,
  writeTaskId,
  type KeyValueStorage,
} from "./sessionStorage";

function createMemoryStorage(): KeyValueStorage {
  const values = new Map<string, string>();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
}

describe("匿名设计上下文存储", () => {
  it("可以保存并恢复当前设计任务", () => {
    const storage = createMemoryStorage();

    writeTaskId(storage, 42);

    expect(readTaskId(storage)).toBe(42);
  });

  it("损坏的任务编号不会被恢复", () => {
    const storage = createMemoryStorage();
    storage.setItem("haus-current-task-id", "not-a-number");

    expect(readTaskId(storage)).toBeNull();
  });

  it("图片编号会去重并忽略损坏数据", () => {
    const storage = createMemoryStorage();

    writeImageIds(storage, [3, 2, 3, -1]);
    expect(readImageIds(storage)).toEqual([3, 2]);

    storage.setItem("haus-uploaded-image-ids", "{bad json");
    expect(readImageIds(storage)).toEqual([]);
  });
});
