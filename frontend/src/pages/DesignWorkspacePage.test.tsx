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
  chatBaseStateVersion: undefined as number | undefined,
}));

vi.mock("@/components/design/RoomView3D", () => ({
  default: (props: { onMovePersisted?: typeof testState.moveHandler }) => {
    testState.moveHandler = props.onMovePersisted;
    return <div>ROOM VIEW</div>;
  },
}));
vi.mock("@/components/chat/ChatPanel", () => ({
  default: (props: { baseStateVersion?: number }) => {
    testState.chatBaseStateVersion = props.baseStateVersion;
    return <div>CHAT</div>;
  },
}));
vi.mock("@/components/workspace/DesignWorkspaceInspector", () => ({ default: () => <div>INSPECTOR</div> }));
vi.mock("@/hooks/useFeedbackDelivery", () => ({
  useFeedbackDelivery: () => ({ deliveries: [], submit: testState.submit, retry: vi.fn() }),
}));
vi.mock("@/store/useDesignProjectStore", () => {
  const getState = () => ({
    projects: testState.project ? { 42: testState.project } : {},
    currentProjectId: testState.project?.id ?? null,
    registerProject: vi.fn(),
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

import DesignWorkspacePage, {
  applyAuthoritativeOpenGeometry,
  refreshAuthoritativeSceneFromAgent,
  resolveCustomFurniturePreviewSource,
} from "./DesignWorkspacePage";
import type { OpenGeometryState } from "@/types/openGeometry";
import type { CustomFurniturePreviewResult } from "@/types/customFurniture";
import type { DesignScene } from "@/types/scene";

describe("统一设计工作台", () => {
  beforeEach(() => {
    testState.moveHandler = undefined;
    testState.submit.mockReset();
    testState.chatBaseStateVersion = undefined;
    testState.project = createDesignProject("catalog_design", {
      requirement: { ...emptyRequirement, rooms: ["客厅"] },
      roomModel: null,
    }, { id: 42 });
    testState.project.activePlanId = "plan-42";
    testState.project.activePlanVersionId = 8;
  });

  it("Agent 场景动作只用匹配当前任务和返回版本的权威场景刷新房间", async () => {
    const scene = {
      id: 7,
      current_version: 3,
    } as DesignScene;
    const apply = vi.fn();
    const accepted = await refreshAuthoritativeSceneFromAgent(
      42,
      { scene_id: 7, version: 3 },
      () => 42,
      vi.fn().mockResolvedValue(scene),
      apply,
    );

    expect(accepted).toBe(true);
    expect(apply).toHaveBeenCalledWith(scene);

    const rejected = await refreshAuthoritativeSceneFromAgent(
      42,
      { scene_id: 7, version: 3 },
      () => 99,
      vi.fn().mockResolvedValue(scene),
      apply,
    );
    expect(rejected).toBe(false);
    expect(apply).toHaveBeenCalledTimes(1);
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

  it("聊天入口收到项目当前 Agent 状态版本", () => {
    testState.project!.stateVersion = 12;

    renderToStaticMarkup(
      <MemoryRouter initialEntries={["/design/42/workspace"]}>
        <Routes>
          <Route path="/design/:projectId/workspace" element={<DesignWorkspacePage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(testState.chatBaseStateVersion).toBe(12);
  });

  it("本地项目缺失时先恢复服务端检查点，不提前宣告项目不存在", () => {
    testState.project = undefined;

    const html = renderToStaticMarkup(
      <MemoryRouter initialEntries={["/design/42/workspace"]}>
        <Routes>
          <Route path="/design/:projectId/workspace" element={<DesignWorkspacePage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(html).toContain("正在从服务端恢复设计项目");
    expect(html).not.toContain("找不到这个设计项目");
  });

  it("Agent 响应中的开放几何立即成为 3D 权威状态", () => {
    const setState = vi.fn();
    const geometry = {
      task_id: 42,
      current_version: 1,
      current: null,
      history: [],
    } satisfies OpenGeometryState;

    applyAuthoritativeOpenGeometry(42, { task_id: 42, open_geometry: geometry }, setState);

    expect(setState).toHaveBeenCalledWith(geometry);
  });

  it("首次 checkpoint 的 null 几何恢复为权威空任务状态", () => {
    const setState = vi.fn();

    applyAuthoritativeOpenGeometry(42, { task_id: 42, open_geometry: null }, setState);

    expect(setState).toHaveBeenCalledWith({
      task_id: 42,
      current_version: 0,
      current: null,
      history: [],
    });
  });

  it("忽略其他任务延迟返回的开放几何状态", () => {
    const setState = vi.fn();
    const staleGeometry = {
      task_id: 41,
      current_version: 3,
      current: null,
      history: [],
    } satisfies OpenGeometryState;

    applyAuthoritativeOpenGeometry(
      42,
      { task_id: 41, open_geometry: staleGeometry },
      setState,
    );
    applyAuthoritativeOpenGeometry(
      42,
      { task_id: 41, open_geometry: null },
      setState,
    );
    applyAuthoritativeOpenGeometry(
      42,
      { task_id: 42, open_geometry: staleGeometry },
      setState,
    );

    expect(setState).not.toHaveBeenCalled();
  });

  it("最近的结构化响应覆盖旧开放几何预览，开放几何响应也可切回", () => {
    const geometry = {
      task_id: 42,
      current_version: 2,
      current: { version: 2 },
      history: [],
    } as unknown as OpenGeometryState;
    const structured = { status: "preview_ready" } as CustomFurniturePreviewResult;

    expect(resolveCustomFurniturePreviewSource({
      intent: "custom_furniture",
      open_geometry: geometry,
    }, structured)).toBe("structured");
    expect(resolveCustomFurniturePreviewSource({
      intent: "open_geometry",
      open_geometry: geometry,
    }, structured)).toBe("open_geometry");
  });
});
