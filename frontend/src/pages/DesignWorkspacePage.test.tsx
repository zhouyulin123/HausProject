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
    setAuthoritativeScene: vi.fn(),
    setCustomFurnitureDraftReference: vi.fn(),
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

  it("移动反馈由场景保存事务原子生成，页面不再二次投递", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter initialEntries={["/design/42/workspace"]}>
        <Routes>
          <Route path="/design/:projectId/workspace" element={<DesignWorkspacePage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(html).toContain("ROOM VIEW");
    expect(testState.moveHandler).toBeUndefined();
    expect(testState.submit).not.toHaveBeenCalled();
  });
});
