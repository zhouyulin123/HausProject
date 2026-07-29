import { describe, expect, it } from "vitest";
import {
  readImageIds,
  readSessionId,
  readTaskId,
  writeImageIds,
  writeSessionId,
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
  it("只恢复合法的匿名会话编号", () => {
    const storage = createMemoryStorage();
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";

    writeSessionId(storage, sessionId);
    expect(readSessionId(storage)).toBe(sessionId);

    storage.setItem("haus-anonymous-session-id", "invalid");
    expect(readSessionId(storage)).toBeNull();
  });

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
