import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createDesignProject, type DesignProject } from "@/lib/designProject";
import { emptyRequirement } from "@/types/requirement";

const testState = vi.hoisted(() => ({
  moveHandler: undefined as undefined | ((move: {
    sceneId: number;
    sceneVersion: number;
    instanceId: string;
  }) => void),
  submit: vi.fn(),
  project: undefined as DesignProject | undefined,
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
vi.mock("@/store/useDesignProjectStore", () => {
  const getState = () => ({
    projects: testState.project ? { 42: testState.project } : {},
    currentProjectId: testState.project?.id ?? null,
    selectProject: vi.fn(),
    setMessages: vi.fn(),
    applyAgentState: vi.fn(),
    attachPlan: vi.fn(),
    setSceneReference: vi.fn(),
    setFurnitureSelection: vi.fn(),
  });
  const useDesignProjectStore = (
    selector: (state: ReturnType<typeof getState>) => unknown,
  ) => selector(getState());
  useDesignProjectStore.getState = getState;
  return { useDesignProjectStore };
});
vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router-dom")>()),
  useParams: () => ({ projectId: "42" }),
}));

import DesignWorkspacePage from "./DesignWorkspacePage";

describe("统一设计工作台", () => {
  beforeEach(() => {
    testState.moveHandler = undefined;
    testState.submit.mockReset();
    testState.project = createDesignProject("catalog_design", {
      requirement: { ...emptyRequirement, rooms: ["客厅"] },
      roomModel: null,
    }, { id: 42 });
    testState.project.activePlanId = "plan-42";
    testState.project.activePlanVersionId = 8;
  });

  it("把 3D 持久化移动接入结构化反馈且重复回调只投递一次", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter initialEntries={["/design/42/workspace"]}>
        <Routes>
          <Route path="/design/:projectId/workspace" element={<DesignWorkspacePage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(html).toContain("ROOM VIEW");
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
