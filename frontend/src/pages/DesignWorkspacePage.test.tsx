import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { emptyRequirement } from "@/types/requirement";
import { useDesignProjectStore } from "@/store/useDesignProjectStore";

const testState = vi.hoisted(() => ({
  moveHandler: undefined as undefined | ((move: {
    sceneId: number;
    sceneVersion: number;
    instanceId: string;
  }) => void),
  submit: vi.fn(),
}));

vi.mock("@/components/design/RoomView3D", () => ({
  default: (props: { onMovePersisted?: typeof testState.moveHandler }) => {
    testState.moveHandler = props.onMovePersisted;
    return <div>ROOM VIEW</div>;
  },
}));
vi.mock("@/components/chat/ChatPanel", () => ({ default: () => <div>CHAT</div> }));
vi.mock("@/components/workspace/DesignWorkspaceInspector", () => ({ default: () => <div>INSPECTOR</div> }));
vi.mock("@/hooks/useFeedbackDelivery", () => ({
  useFeedbackDelivery: () => ({ deliveries: [], submit: testState.submit, retry: vi.fn() }),
}));

import DesignWorkspacePage from "./DesignWorkspacePage";

describe("统一设计工作台", () => {
  beforeEach(() => {
    testState.moveHandler = undefined;
    testState.submit.mockReset();
    useDesignProjectStore.setState({ projects: {}, currentProjectId: null });
    useDesignProjectStore.getState().registerProject(42, "catalog_design", {
      requirement: { ...emptyRequirement, rooms: ["客厅"] },
      roomModel: null,
    });
    useDesignProjectStore.getState().attachPlan(42, {
      id: "plan-42",
      planVersionId: 8,
    });
  });

  it("把 3D 持久化移动接入结构化反馈且重复回调只投递一次", () => {
    renderToStaticMarkup(
      <MemoryRouter initialEntries={["/design/42/workspace"]}>
        <Routes>
          <Route path="/design/:projectId/workspace" element={<DesignWorkspacePage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(testState.moveHandler).toBeTypeOf("function");
    testState.moveHandler?.({ sceneId: 3, sceneVersion: 7, instanceId: "sofa-1" });
    testState.moveHandler?.({ sceneId: 3, sceneVersion: 7, instanceId: "sofa-1" });

    expect(testState.submit).toHaveBeenCalledTimes(1);
    expect(testState.submit).toHaveBeenCalledWith(
      expect.objectContaining({
        action_type: "move",
        scene_id: 3,
        scene_version: 7,
        instance_id: "sofa-1",
      }),
      "家具位置调整",
    );
  });
});
