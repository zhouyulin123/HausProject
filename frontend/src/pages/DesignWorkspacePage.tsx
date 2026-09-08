import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeft,
  Box,
  CircleDot,
  MessageSquareText,
  PanelRight,
  Plus,
} from "lucide-react";
import ChatPanel from "@/components/chat/ChatPanel";
import RoomView3D from "@/components/design/RoomView3D";
import CustomFurniturePanel from "@/components/workspace/CustomFurniturePanel";
import DesignWorkspaceInspector from "@/components/workspace/DesignWorkspaceInspector";
import WorkspaceFeedbackControls from "@/components/workspace/WorkspaceFeedbackControls";
import AgentExecutionPanel from "@/components/workspace/AgentExecutionPanel";
import {
  fetchDesignAgentState,
  fetchDesignScene,
  fetchDesignTaskPlans,
  fetchFurnitureCatalog,
  mutateWorkspacePlan,
  resumeAgentGeneration,
  type AgentTurnResponse,
} from "@/api/designApi";
import { parseCustomFurniturePreview } from "@/lib/customFurnitureWorkspace";
import {
  agentExecutionFromCheckpoint,
  agentExecutionFromTurn,
} from "@/lib/agentExecution";
import { useFeedbackDelivery } from "@/hooks/useFeedbackDelivery";
import {
  buildFinalSelectFeedbackEvent,
  buildGlbLoadFailureFeedbackEvent,
  createMoveFeedbackReporter,
  createFeedbackClientEventId,
} from "@/lib/workspaceFeedback";
import { buildWorkspacePlan, DESIGN_ENTRY_MODES } from "@/lib/designProject";
import {
  parseDesignProjectId,
  WORKSPACE_CATALOG_OPTIONS,
} from "@/lib/designWorkspaceRouting";
import { useDesignProjectStore } from "@/store/useDesignProjectStore";
import { useDesignStore } from "@/store/useDesignStore";
import type { FurnitureItem } from "@/types/furniture";

type AgentConnection = "checking" | "connected" | "unavailable";
type MobilePanel = "conversation" | "scene" | "context";

const FurnitureModelViewer = lazy(
  () => import("@/components/furniture/FurnitureModelViewer"),
);

export default function DesignWorkspacePage() {
  const params = useParams();
  const projectId = parseDesignProjectId(params.projectId);
  const project = useDesignProjectStore((state) =>
    projectId ? state.projects[projectId] : undefined,
  );
  const selectProject = useDesignProjectStore((state) => state.selectProject);
  const setMessages = useDesignProjectStore((state) => state.setMessages);
  const applyAgentState = useDesignProjectStore((state) => state.applyAgentState);
  const attachPlan = useDesignProjectStore((state) => state.attachPlan);
  const setSceneReference = useDesignProjectStore((state) => state.setSceneReference);
  const setFurnitureSelection = useDesignProjectStore((state) => state.setFurnitureSelection);
  const generatedPlans = useDesignStore((state) => state.generatedPlans);
  const setGeneratedPlans = useDesignStore((state) => state.setGeneratedPlans);
  const [catalog, setCatalog] = useState<FurnitureItem[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState("");
  const [agentConnection, setAgentConnection] = useState<AgentConnection>("checking");
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>("conversation");
  const [satisfaction, setSatisfaction] = useState<1 | 2 | 3 | 4 | 5 | null>(null);
  const finalSelectRef = useRef<{ signature: string; clientEventId: string } | null>(null);
  const feedback = useFeedbackDelivery(projectId ?? 0);

  const restoreServerPlans = useCallback(async (taskId: number) => {
    try {
      const plans = await fetchDesignTaskPlans(taskId);
      if (!plans.length) return;
      const existingPlans = useDesignStore.getState().generatedPlans;
      const incomingIds = new Set(plans.map((item) => item.id));
      setGeneratedPlans([
        ...existingPlans.filter(
          (item) => item.task_id !== taskId && !incomingIds.has(item.id),
        ),
        ...plans,
      ]);
      const activePlanId = useDesignProjectStore.getState().projects[taskId]?.activePlanId;
      const activePlan = plans.find((item) => item.id === activePlanId) ?? plans[0];
      if (activePlan.planVersionId) {
        attachPlan(taskId, {
          id: activePlan.id,
          planVersionId: activePlan.planVersionId,
        });
      }
    } catch {
      // 确认控件保持禁用；绝不以 revision 或本地方案编号替代服务端方案版本。
    }
  }, [attachPlan, setGeneratedPlans]);

  const applyWorkspaceAgentResponse = useCallback((response: AgentTurnResponse) => {
    if (!projectId) return;
    applyAgentState(projectId, {
      stateVersion: response.state_version,
      status: response.status,
      activeMode: response.active_mode,
      pendingQuestions: response.pending_questions,
      sceneRef: response.scene_ref,
      exitReason: response.exit_reason,
      activeRoomId: response.active_room_id,
      customFurnitureSpec: response.state.custom_furniture_spec,
      customFurnitureResult: parseCustomFurniturePreview(response.result),
      approvalRequired: response.approval_required,
      generationRunId: response.run_id,
      execution: agentExecutionFromTurn(response),
    });
    if (response.status === "completed" && response.intent === "design") {
      void restoreServerPlans(projectId);
    }
  }, [applyAgentState, projectId, restoreServerPlans]);

  const appendConversationTurn = useCallback((message: string, reply: string) => {
    if (!projectId) return;
    const current = useDesignProjectStore.getState().projects[projectId]?.messages ?? [];
    const stamp = Date.now();
    setMessages(projectId, [
      ...current,
      { id: `local-user-${stamp}`, role: "user", content: message },
      { id: `local-ai-${stamp}`, role: "ai", content: reply },
    ]);
  }, [projectId, setMessages]);

  useEffect(() => {
    if (project) selectProject(project.id);
  }, [project, selectProject]);

  useEffect(() => {
    if (!project) return;
    let cancelled = false;
    void fetchDesignAgentState(project.id)
      .then((checkpoint) => {
        if (cancelled) return;
        applyAgentState(project.id, {
          stateVersion: checkpoint.state_version,
          status: checkpoint.status,
          activeMode: checkpoint.active_mode,
          pendingQuestions: checkpoint.pending_questions,
          sceneRef: checkpoint.scene_ref,
          exitReason: checkpoint.exit_reason,
          activeRoomId: checkpoint.active_room_id,
          customFurnitureSpec:
            checkpoint.custom_furniture_draft ?? checkpoint.custom_furniture_spec,
          customFurnitureResult: parseCustomFurniturePreview(checkpoint.result),
          approvalRequired: checkpoint.approval_required,
          generationRunId: checkpoint.run_id,
          execution: agentExecutionFromCheckpoint(
            checkpoint,
            useDesignProjectStore.getState().projects[project.id]?.execution.events,
          ),
        });
        setMessages(
          project.id,
          checkpoint.messages.map((message) => ({
            id: `server-${message.id}`,
            role: message.role,
            content: message.content,
          })),
        );
        if (checkpoint.status === "completed" && checkpoint.intent === "design") {
          void restoreServerPlans(project.id);
        }
        setAgentConnection("connected");
      })
      .catch(() => {
        if (!cancelled) setAgentConnection("unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, [applyAgentState, project?.id, restoreServerPlans, setMessages]);

  useEffect(() => {
    if (
      !project
      || project.status !== "running"
      || project.exitReason !== "generation_queued"
      || !project.generationRunId
    ) return;
    let cancelled = false;
    void resumeAgentGeneration(project.id, project.generationRunId)
      .then(({ checkpoint, plans }) => {
        if (cancelled) return;
        applyAgentState(project.id, {
          stateVersion: checkpoint.state_version,
          status: checkpoint.status,
          activeMode: checkpoint.active_mode,
          pendingQuestions: checkpoint.pending_questions,
          sceneRef: checkpoint.scene_ref,
          exitReason: checkpoint.exit_reason,
          activeRoomId: checkpoint.active_room_id,
          customFurnitureSpec:
            checkpoint.custom_furniture_draft ?? checkpoint.custom_furniture_spec,
          customFurnitureResult: parseCustomFurniturePreview(checkpoint.result),
          approvalRequired: checkpoint.approval_required,
          generationRunId: checkpoint.run_id,
          execution: agentExecutionFromCheckpoint(
            checkpoint,
            useDesignProjectStore.getState().projects[project.id]?.execution.events,
          ),
        });
        setMessages(
          project.id,
          checkpoint.messages.map((message) => ({
            id: `server-${message.id}`,
            role: message.role,
            content: message.content,
          })),
        );
        if (plans.length) {
          const existingPlans = useDesignStore.getState().generatedPlans;
          const incomingIds = new Set(plans.map((item) => item.id));
          setGeneratedPlans([
            ...existingPlans.filter(
              (item) => item.task_id !== project.id && !incomingIds.has(item.id),
            ),
            ...plans,
          ]);
          const activePlan = plans[0];
          if (activePlan.planVersionId) {
            attachPlan(project.id, {
              id: activePlan.id,
              planVersionId: activePlan.planVersionId,
            });
          }
        }
      })
      .catch(() => {
        if (!cancelled) setAgentConnection("unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, [
    applyAgentState,
    attachPlan,
    project?.exitReason,
    project?.generationRunId,
    project?.id,
    project?.status,
    setGeneratedPlans,
    setMessages,
  ]);

  useEffect(() => {
    if (project?.mode === "custom_furniture") {
      setCatalog([]);
      setCatalogError("");
      setCatalogLoading(false);
      return;
    }
    let cancelled = false;
    setCatalogLoading(true);
    setCatalogError("");
    void fetchFurnitureCatalog(WORKSPACE_CATALOG_OPTIONS)
      .then((items) => {
        if (!cancelled) setCatalog(items);
      })
      .catch(() => {
        if (!cancelled) setCatalogError("商品库连接失败，未使用演示商品替代。");
      })
      .finally(() => {
        if (!cancelled) setCatalogLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [project?.mode]);

  const activePlan = project?.activePlanId
    ? generatedPlans.find(
        (item) => item.id === project.activePlanId && item.task_id === project.id,
      )
    : undefined;
  const selectedFurniture = useMemo(
    () =>
      project
        ? catalog.filter((item) => project.selectedFurnitureIds.includes(item.id))
        : [],
    [catalog, project],
  );
  const plan = project
    ? activePlan ?? buildWorkspacePlan(project, selectedFurniture)
    : null;
  const entry = project
    ? DESIGN_ENTRY_MODES.find((item) => item.id === project.mode)
    : null;
  const planVersionId = plan?.planVersionId ?? null;
  const activeRoomId = project?.activeRoomId ?? project?.roomModel?.rooms[0]?.id ?? null;
  const reportMovePersisted = useMemo(
    () => createMoveFeedbackReporter({
      taskId: projectId ?? 0,
      planVersionId,
      roomId: activeRoomId,
      submit: feedback.submit,
    }),
    [activeRoomId, feedback.submit, planVersionId, projectId],
  );

  useEffect(() => {
    if (!project || !activePlan || !catalog.length) return;
    const selectedSkus = new Set(
      activePlan.furnitureSuggestions.map((item) => item.sku).filter(Boolean),
    );
    setFurnitureSelection(
      project.id,
      catalog.filter((item) => item.sku && selectedSkus.has(item.sku)).map((item) => item.id),
    );
  }, [activePlan, catalog, project?.id, setFurnitureSelection]);

  const handlePlanMutation = useCallback(async (mutation: {
    action: "adopt" | "remove" | "replace";
    sourceSku?: string;
    targetSku?: string;
  }) => {
    if (!project || !activePlan?.planVersionId || !activePlan.revisionVersion) {
      throw new Error("当前方案尚未恢复完成，请稍后重试。");
    }
    let sourceInstanceId: string | undefined;
    if (mutation.sourceSku) {
      if (!project.sceneRef) {
        throw new Error("3D 场景尚未恢复，不能确定要操作的家具实例。");
      }
      const currentScene = await fetchDesignScene(project.sceneRef.scene_id);
      const matches = currentScene.scene.items.filter(
        (item) => item.sku === mutation.sourceSku,
      );
      if (matches.length !== 1) {
        throw new Error(
          matches.length === 0
            ? "当前场景中没有该家具实例，请刷新后重试。"
            : "同款家具有多个实例，请先在 3D 场景中明确选择一件。",
        );
      }
      sourceInstanceId = matches[0].instanceId;
    }
    const response = await mutateWorkspacePlan(project.id, {
      clientMutationId: createFeedbackClientEventId(project.id, mutation.action),
      baseRevisionVersion: activePlan.revisionVersion,
      planVersionId: activePlan.planVersionId,
      action: mutation.action,
      sourceInstanceId,
      targetSku: mutation.targetSku,
      roomId: project.activeRoomId,
    });
    setSceneReference(project.id, {
      scene_id: response.scene.id,
      version: response.scene.current_version,
    });
    await restoreServerPlans(project.id);
  }, [activePlan, project, restoreServerPlans, setSceneReference]);

  const confirmCurrentPlan = useCallback(() => {
    if (!projectId || !planVersionId) return;
    const signature = `${planVersionId}:${satisfaction ?? "none"}`;
    const clientEventId = finalSelectRef.current?.signature === signature
      ? finalSelectRef.current.clientEventId
      : createFeedbackClientEventId(projectId, "final_select");
    finalSelectRef.current = { signature, clientEventId };
    const event = buildFinalSelectFeedbackEvent(
      clientEventId,
      planVersionId,
      satisfaction,
    );
    if (event) feedback.submit(event, "确认当前方案");
  }, [feedback.submit, planVersionId, projectId, satisfaction]);

  const reportGlbLoadFailure = useCallback((failure: {
    planVersionId: number;
    sceneId: number;
    sceneVersion: number;
    instanceId: string;
    sku: string;
  }) => {
    if (!projectId) return;
    const event = buildGlbLoadFailureFeedbackEvent({
      taskId: projectId,
      ...failure,
    });
    if (event) feedback.submit(event, "GLB 加载失败");
  }, [feedback.submit, projectId]);

  const handleSceneReferenceChange = useCallback((reference: {
    id: number;
    version: number;
  } | null) => {
    if (!projectId) return;
    setSceneReference(
      projectId,
      reference
        ? { scene_id: reference.id, version: reference.version }
        : null,
    );
  }, [projectId, setSceneReference]);

  if (!project || !plan || !entry) {
    return (
      <div className="flex min-h-[70vh] items-center justify-center bg-[#111713] px-5 text-center text-[#e5e8e1]">
        <div>
          <AlertTriangle className="mx-auto h-8 w-8 text-[#f1c08b]" />
          <h1 className="mt-5 text-2xl !text-white">找不到这个设计项目</h1>
          <p className="mt-3 max-w-sm text-sm leading-6 text-[#8f9a90]">请从项目入口恢复当前会话中的设计任务。</p>
          <Link to="/design/new" className="mt-5 inline-flex items-center gap-2 text-sm text-[#d5ff67]">
            <ArrowLeft className="h-4 w-4" /> 返回项目入口
          </Link>
        </div>
      </div>
    );
  }

  const roomType = project.requirement.rooms[0] ?? project.roomModel?.spaceType ?? "客厅";
  const sceneKey = `${plan.planVersionId ?? plan.id}-${project.selectedFurnitureIds.join("-")}-${activeRoomId ?? "no-room"}`;
  const connectionLabel = {
    checking: "正在连接智能体",
    connected: "智能体已连接",
    unavailable: "智能体暂未连接",
  }[agentConnection];

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-[#0f1511] px-3 py-3 text-[#e4e8e1] sm:px-5 lg:px-6">
      <div className="mx-auto max-w-[1920px]">
        <header className="mb-3 flex min-h-14 flex-wrap items-center justify-between gap-3 border border-[#293229] bg-[#171e18] px-4 py-3">
          <div className="flex min-w-0 items-center gap-3">
            <Link
              to="/design/new"
              title="返回项目列表"
              className="flex h-8 w-8 shrink-0 items-center justify-center border border-white/12 text-[#9ca69d] transition-colors hover:border-[#d5ff67] hover:text-[#d5ff67]"
            >
              <ArrowLeft className="h-4 w-4" />
            </Link>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <CircleDot className={`h-3.5 w-3.5 shrink-0 ${agentConnection === "connected" ? "text-[#d5ff67]" : "text-[#f1c08b]"}`} />
                <h1 className="truncate text-sm font-medium !text-[#edf0e9]">{project.title}</h1>
              </div>
              <p className="mt-1 truncate font-mono text-[9px] tracking-[0.12em] text-[#778278] uppercase">
                {entry.shortTitle} / TASK {project.id} / {connectionLabel}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Link
              to="/design/new"
              className="inline-flex min-h-9 items-center gap-1.5 border border-white/12 px-3 text-xs text-[#aeb7af] transition-colors hover:border-[#d5ff67] hover:text-[#d5ff67]"
            >
              <Plus className="h-3.5 w-3.5" /> 新项目
            </Link>
          </div>
        </header>

        <AgentExecutionPanel
          status={project.status}
          exitReason={project.exitReason}
          execution={project.execution}
        />

        <WorkspaceFeedbackControls
          planVersionId={planVersionId}
          satisfaction={satisfaction}
          delivery={feedback.deliveries[0] ?? null}
          onSatisfactionChange={setSatisfaction}
          onConfirm={confirmCurrentPlan}
          onRetry={feedback.retry}
        />

        {project.mode !== "custom_furniture" && catalogError && (
          <p role="alert" className="mb-3 border border-[#8f7040] bg-[#2b2718] px-4 py-3 text-xs text-[#f0d39e]">{catalogError}</p>
        )}

        {project.exitReason === "generation_queued" && project.status === "running" && (
          <p role="status" className="mb-3 border border-[#52613d] bg-[#1b2519] px-4 py-3 text-xs text-[#d5ff67]">
            方案正在后台生成，完成后会自动恢复到当前工作台。
          </p>
        )}

        {project.exitReason === "generation_failed" && project.status === "needs_human" && (
          <p role="alert" className="mb-3 border border-[#8f7040] bg-[#2b2718] px-4 py-3 text-xs text-[#f0d39e]">
            方案生成未完成，已停止自动执行并转入人工处理。
          </p>
        )}

        <nav aria-label="移动端工作台视图" className="mb-3 grid grid-cols-3 border border-[#293229] bg-[#171e18] xl:hidden">
          {[
            { id: "conversation" as const, label: "对话", icon: MessageSquareText },
            { id: "scene" as const, label: "3D", icon: Box },
            { id: "context" as const, label: "上下文", icon: PanelRight },
          ].map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setMobilePanel(item.id)}
                className={`flex min-h-11 items-center justify-center gap-2 text-xs font-medium ${mobilePanel === item.id ? "bg-[#d5ff67] text-[#111713]" : "text-[#9ca69d]"}`}
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </button>
            );
          })}
        </nav>

        <div className="grid items-start gap-3 xl:grid-cols-[minmax(270px,300px)_minmax(0,1fr)_minmax(320px,360px)]">
          <div className={mobilePanel === "conversation" ? "block" : "hidden xl:block"}>
            <ChatPanel
              key={project.id}
              workspace
              projectId={project.id}
              activeMode={project.mode}
              activeRoomId={activeRoomId}
              sceneId={project.sceneRef?.scene_id}
              baseSceneVersion={project.sceneRef?.version}
              initialMessages={project.messages}
              pendingQuestions={project.pendingQuestions}
              onMessagesChange={(messages) => setMessages(project.id, messages)}
              onAgentResponse={applyWorkspaceAgentResponse}
            />
          </div>

          <main className={`min-w-0 rounded-lg border border-[#293229] bg-[#d9d5ca] p-2 ${mobilePanel === "scene" ? "block" : "hidden xl:block"}`}>
            <div className="mb-2 flex min-h-9 items-center justify-between gap-3 border-b border-[#1d241f]/15 px-2 pb-2 text-[#303831]">
              <div>
                <p className="font-mono text-[9px] tracking-[0.14em] text-[#69736a] uppercase">
                  {project.mode === "custom_furniture" ? "Parameter preview" : "Live scene"}
                </p>
                <p className="mt-0.5 text-xs font-medium">
                  {project.mode === "custom_furniture"
                    ? project.customFurnitureResult?.spec.name ?? "自定义家具参数草案"
                    : `${roomType} · ${selectedFurniture.length} 件家具`}
                </p>
              </div>
              <span className="text-[10px] text-[#69736a]">
                {project.mode === "custom_furniture" || !plan.planVersionId ? "LOCAL DRAFT" : `VERSION ${plan.planVersionId}`}
              </span>
            </div>
            {project.mode === "custom_furniture" ? (
              project.customFurnitureResult ? (
                <div className="h-[540px] min-h-[420px] overflow-hidden border border-[#1d241f]/15 bg-[#efe8db]">
                  <Suspense fallback={<div className="flex h-full items-center justify-center text-xs text-[#69736a]">正在加载确定性模型…</div>}>
                    <FurnitureModelViewer spec={project.customFurnitureResult.model_spec} />
                  </Suspense>
                </div>
              ) : (
                <div className="flex h-[540px] min-h-[420px] items-center justify-center border border-dashed border-[#69736a]/40 bg-[#e4dfd3] px-8 text-center">
                  <div className="max-w-sm">
                    <Box className="mx-auto h-8 w-8 text-[#69736a]" />
                    <p className="mt-4 text-sm font-medium text-[#303831]">尚无可验证的 3D 参数预览</p>
                    <p className="mt-2 text-xs leading-5 text-[#69736a]">提交右侧结构化参数后，仅在服务端返回确定性模型规则时显示本地草案。当前内容不代表施工图、已保存方案或已核价结果。</p>
                  </div>
                </div>
              )
            ) : (
              <RoomView3D
                key={sceneKey}
                plan={plan}
                roomType={roomType}
                roomModel={project.roomModel}
                onMovePersisted={reportMovePersisted}
                onGlbLoadFailed={reportGlbLoadFailure}
                onSceneReferenceChange={handleSceneReferenceChange}
              />
            )}
          </main>

          <div className={mobilePanel === "context" ? "block" : "hidden xl:block"}>
            {project.mode === "custom_furniture" ? (
              <CustomFurniturePanel
                taskId={project.id}
                stateVersion={project.stateVersion}
                initialSpec={project.customFurnitureSpec}
                preview={project.customFurnitureResult}
                approvalRequired={project.approvalRequired}
                pendingQuestions={project.pendingQuestions}
                onAgentResponse={applyWorkspaceAgentResponse}
                onConversationTurn={appendConversationTurn}
              />
            ) : (
              <DesignWorkspaceInspector
                project={project}
                catalog={catalog}
                catalogLoading={catalogLoading}
                budget={plan.budget}
                onPlanMutation={handlePlanMutation}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
