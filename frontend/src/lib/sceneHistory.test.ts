import { describe, expect, it } from "vitest";
import { mockDesigns } from "@/data/mockDesigns";
import { buildSceneDocument } from "./sceneDocument";
import {
  commitScene,
  createSceneHistory,
  redoScene,
  replaceScene,
  undoScene,
} from "./sceneHistory";

describe("3D 场景编辑历史", () => {
  it("支持提交、撤销和重做", () => {
    const initial = buildSceneDocument(mockDesigns[0], "客厅");
    const changed = {
      ...initial,
      camera: {
        position: { x: 6, y: 5, z: 7 },
        target: { x: 0, y: 0.5, z: 0 },
        fov: 45,
      },
    };

    const committed = commitScene(createSceneHistory(initial), changed);
    const undone = undoScene(committed);
    const redone = redoScene(undone);

    expect(committed.canUndo).toBe(true);
    expect(undone.present).toEqual(initial);
    expect(undone.canRedo).toBe(true);
    expect(redone.present).toEqual(changed);
  });

  it("撤销后产生新修改会清空重做分支", () => {
    const initial = buildSceneDocument(mockDesigns[0], "客厅");
    const first = { ...initial, camera: null };
    const second = {
      ...initial,
      room: { ...initial.room, name: "客厅新布局" },
    };
    const branched = commitScene(
      undoScene(commitScene(createSceneHistory(initial), first)),
      second,
    );

    expect(branched.canRedo).toBe(false);
  });

  it("载入服务端场景时重置历史且不标记为本地修改", () => {
    const initial = buildSceneDocument(mockDesigns[0], "客厅");
    const edited = commitScene(createSceneHistory(initial), {
      ...initial,
      camera: null,
    });

    const replaced = replaceScene(edited, initial);

    expect(replaced.canUndo).toBe(false);
    expect(replaced.changeId).toBe(0);
  });

  it("无可用历史时撤销、重做和重复提交均保持原状态", () => {
    const initial = buildSceneDocument(mockDesigns[0], "客厅");
    const history = createSceneHistory(initial);

    expect(undoScene(history)).toBe(history);
    expect(redoScene(history)).toBe(history);
    expect(commitScene(history, initial)).toBe(history);
  });
});
