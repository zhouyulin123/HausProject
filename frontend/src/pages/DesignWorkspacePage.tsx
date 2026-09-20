import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeft,
  Box,
  CircleDot,
  MessageSquareText,
  Plus,
  X,
  Map,
  CircleDollarSign,
  Upload,
} from "lucide-react";
import ChatPanel from "@/components/chat/ChatPanel";
import RoomView3D from "@/components/design/RoomView3D";
import CustomFurniturePanel from "@/components/workspace/CustomFurniturePanel";
import OpenGeometryPanel from "@/components/workspace/OpenGeometryPanel";
import FurnitureDesignWorkspace from "@/components/workspace/FurnitureDesignWorkspace";
import DesignWorkspaceInspector from "@/components/workspace/DesignWorkspaceInspector";
import WorkspaceFeedbackControls from "@/components/workspace/WorkspaceFeedbackControls";
import AgentExecutionPanel from "@/components/workspace/AgentExecutionPanel";
import AgentApprovalPanel from "@/components/workspace/AgentApprovalPanel";
import {
  decideAgentApproval,
  fetchAgentApprovals,
  fetchDesignAgentState,
  fetchDesignAgentEvents,
  fetchDesignScene,
  fetchDesignTaskTimeline,
  fetchDesignTaskPlans,
  fetchFurnitureCatalog,
  mutateWorkspacePlan,
  resumeAgentGeneration,
  type DesignAgentStateResponse,
  type AgentTurnResponse,
  type AgentApproval,
  type TaskTimelineResponse,
} from "@/api/designApi";
import { parseCustomFurniturePreview } from "@/lib/customFurnitureWorkspace";
import { restoreCustomFurnitureDraftReference } from "@/lib/customFurniturePlacement";
import {
  agentExecutionFromCheckpoint,
  agentExecutionFromTurn,
  mergeAgentExecutionEvents,
} from "@/lib/agentExecution";
import { mergeTaskTimelinePages } from "@/lib/taskTimeline";
import { createTaskTimelinePollingLoop } from "@/lib/taskTimelinePolling";
import { useFeedbackDelivery } from "@/hooks/useFeedbackDelivery";
import {
  buildFinalSelectFeedbackEvent,
  buildGlbLoadFailureFeedbackEvent,
  createFeedbackClientEventId,
  createPlanMutationEventIdResolver,
} from "@/lib/workspaceFeedback";
import {
  buildWorkspacePlan,
  DESIGN_ENTRY_MODES,
  restoreDesignProjectSeed,
} from "@/lib/designProject";
import {
  parseDesignProjectId,
  WORKSPACE_CATALOG_OPTIONS,
} from "@/lib/designWorkspaceRouting";
import { useDesignProjectStore } from "@/store/useDesignProjectStore";
import { useDesignStore } from "@/store/useDesignStore";
import type { FurnitureItem } from "@/types/furniture";
import type { CustomFurniturePreviewResult } from "@/types/customFurniture";
import type { DesignScene } from "@/types/scene";
import {
  emptyOpenGeometryState,
  type OpenGeometryState,
} from "@/types/openGeometry";

type AgentConnection = "checking" | "connected" | "unavailable";
type ProjectRecovery = "checking" | "ready" | "missing";
type MobilePanel = "conversation" | "scene" | "context";

const FurnitureModelViewer = lazy(
  () => import("@/components/furniture/FurnitureModelViewer"),
);

export function applyAuthoritativeOpenGeometry(
  taskId: number,
  payload: { task_id: number; open_geometry: OpenGeometryState | null },
  setState: (state: OpenGeometryState) => void,
) {
  if (
    payload.task_id !== taskId
    || (payload.open_geometry !== null && payload.open_geometry.task_id !== taskId)
  ) return;
  setState(payload.open_geometry ?? emptyOpenGeometryState(taskId));
}

export async function refreshAuthoritativeSceneFromAgent(
  taskId: number,
  sceneReference: { scene_id: number; version: number } | null,
  getActiveTaskId: () => number | null | undefined,
  fetchScene: (sceneId: number) => Promise<DesignScene>,
  applyScene: (scene: DesignScene) => void,
): Promise<boolean> {
  if (!sceneReference) return false;
  const scene = await fetchScene(sceneReference.scene_id);
  if (
    getActiveTaskId() !== taskId
    || scene.id !== sceneReference.scene_id
    || scene.current_version !== sceneReference.version
  ) return false;
  applyScene(scene);
  return true;
}

export type CustomFurniturePreviewSource = "open_geometry" | "structured";

export function resolveCustomFurniturePreviewSource(
  payload: { intent: string; open_geometry: OpenGeometryState | null },
  structuredPreview: CustomFurniturePreviewResult | null,
): CustomFurniturePreviewSource | null {
  if (payload.intent === "custom_furniture" && structuredPreview) return "structured";
  if (payload.intent === "open_geometry" && payload.open_geometry?.current) {
    return "open_geometry";
  }
  if (structuredPreview) return "structured";
  return payload.open_geometry?.current ? "open_geometry" : null;
}

export default function DesignWorkspacePage() {
  const params = useParams();
  const projectId = parseDesignProjectId(params.projectId);
  const project = useDesignProjectStore((state) =>
    projectId ? state.projects[projectId] : undefined,
  );
  const selectProject = useDesignProjectStore((state) => state.selectProject);
  const registerProject = useDesignProjectStore((state) => state.registerProject);
  const setMessages = useDesignProjectStore((state) => state.setMessages);
  const applyAgentState = useDesignProjectStore((state) => state.applyAgentState);
  const attachPlan = useDesignProjectStore((state) => state.attachPlan);
  const setSceneReference = useDesignProjectStore((state) => state.setSceneReference);
  const setAuthoritativeScene = useDesignProjectStore((state) => state.setAuthoritativeScene);
  const setCustomFurnitureDraftReference = useDesignProjectStore(
    (state) => state.setCustomFurnitureDraftReference,
  );
  const setFurnitureSelection = useDesignProjectStore((state) => state.setFurnitureSelection);
  const generatedPlans = useDesignStore((state) => state.generatedPlans);
  const setGeneratedPlans = useDesignStore((state) => state.setGeneratedPlans);
  const [catalog, setCatalog] = useState<FurnitureItem[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState("");
  const [agentConnection, setAgentConnection] = useState<AgentConnection>("checking");
  const [projectRecovery, setProjectRecovery] = useState<ProjectRecovery>(
    project ? "ready" : projectId ? "checking" : "missing",
  );
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>("conversation");
  const [roomTool, setRoomTool] = useState<"room" | "catalog" | "budget" | null>(null);
  const [satisfaction, setSatisfaction] = useState<1 | 2 | 3 | 4 | 5 | null>(null);
  const [approvals, setApprovals] = useState<AgentApproval[]>([]);
  const [approvalsLoading, setApprovalsLoading] = useState(false);
  const [approvalsError, setApprovalsError] = useState("");
  const [decidingApprovalId, setDecidingApprovalId] = useState<number | null>(null);
  const [timeline, setTimeline] = useState<TaskTimelineResponse | null>(null);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [openGeometryState, setOpenGeometryState] = useState<OpenGeometryState | null>(null);
  const [customFurniturePreviewSource, setCustomFurniturePreviewSource] = useState<
    CustomFurniturePreviewSource | null
  >(null);
  const activeProjectIdRef = useRef(projectId);
  activeProjectIdRef.current = projectId;
  const timelineRef = useRef<TaskTimelineResponse | null>(null);
  const timelineEpochRef = useRef(0);
  const timelineInFlightRef = useRef<Promise<boolean> | null>(null);
  const finalSelectRef = useRef<{ signature: string; clientEventId: string } | null>(null);
  const feedback = useFeedbackDelivery(projectId ?? 0);

  const refreshApprovals = useCallback(async () => {
    if (!projectId) return;
    setApprovalsLoading(true);
    setApprovalsError("");
    try {
      setApprovals(await fetchAgentApprovals(projectId));
    } catch {
      setApprovalsError("审批记录读取失败，请稍后重试。");
    } finally {
      setApprovalsLoading(false);
    }
  }, [projectId]);

  const refreshTimeline = useCallback((
    direction: "initial" | "older" | "newer" = "newer",
  ): Promise<boolean> => {
    if (!projectId) return Promise.resolve(false);
    if (timelineInFlightRef.current) return timelineInFlightRef.current;
    const current = direction === "initial" ? null : timelineRef.current;
    if (direction === "older" && current?.next_before_id == null) {
      return Promise.resolve(true);
    }
    const epoch = timelineEpochRef.current;
    setTimelineLoading(true);
    const request = fetchDesignTaskTimeline(projectId, {
      limit: 25,
      beforeId: direction === "older" ? current?.next_before_id ?? undefined : undefined,
      afterId: direction === "newer" ? current?.events.at(-1)?.event_id : undefined,
    })
      .then((response) => {
        if (epoch !== timelineEpochRef.current) return false;
        const next = direction === "initial"
          ? response
          : mergeTaskTimelinePages(current, response, direction);
        timelineRef.current = next;
        setTimeline(next);
        return true;
      })
      .catch(() => false)
      .finally(() => {
        if (timelineInFlightRef.current === request) {
          timelineInFlightRef.current = null;
          if (epoch === timelineEpochRef.current) setTimelineLoading(false);
        }
      });
    timelineInFlightRef.current = request;
    return request;
  }, [projectId]);

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
    if (
      !projectId
      || activeProjectIdRef.current !== projectId
      || response.task_id !== projectId
    ) return;
    const currentProject = useDesignProjectStore.getState().projects[projectId];
    if (currentProject && response.state_version < currentProject.stateVersion) return;
    const customFurnitureResult = parseCustomFurniturePreview(response.result);
    applyAgentState(projectId, {
      stateVersion: response.state_version,
      status: response.status,
      activeMode: response.active_mode,
      pendingQuestions: response.pending_questions,
      facts: response.state.facts,
      factEvidence: response.state.fact_evidence,
      sceneRef: response.scene_ref,
      exitReason: response.exit_reason,
      activeRoomId: response.active_room_id,
      customFurnitureSpec: response.state.custom_furniture_spec,
      customFurnitureResult,
      approvalRequired: response.approval_required,
      generationRunId: response.run_id,
      execution: agentExecutionFromTurn(response),
    });
    applyAuthoritativeOpenGeometry(projectId, response, setOpenGeometryState);
    if (
      response.status === "completed"
      && response.scene_ref
      && ["action_plan", "scene_edit"].includes(response.intent)
    ) {
      void refreshAuthoritativeSceneFromAgent(
        projectId,
        response.scene_ref,
        () => activeProjectIdRef.current,
        fetchDesignScene,
        (scene) => setAuthoritativeScene(projectId, scene),
      ).catch(() => undefined);
    }
    setCustomFurniturePreviewSource(
      resolveCustomFurniturePreviewSource(response, customFurnitureResult),
    );
    if (response.status === "completed" && response.intent === "design") {
      void restoreServerPlans(projectId);
    }
    if (response.approval_required) void refreshApprovals();
    void refreshTimeline("newer");
  }, [
    applyAgentState,
    projectId,
    refreshApprovals,
    refreshTimeline,
    restoreServerPlans,
    setAuthoritativeScene,
  ]);

  const applyRefreshedAgentCheckpoint = useCallback((checkpoint: DesignAgentStateResponse) => {
    if (
      !projectId
      || activeProjectIdRef.current !== projectId
      || checkpoint.task_id !== projectId
    ) return;
    const currentProject = useDesignProjectStore.getState().projects[projectId];
    if (currentProject && checkpoint.state_version < currentProject.stateVersion) return;
    const customFurnitureResult = parseCustomFurniturePreview(checkpoint.result);
    applyAgentState(projectId, {
      stateVersion: checkpoint.state_version,
      status: checkpoint.status,
      activeMode: checkpoint.active_mode,
      pendingQuestions: checkpoint.pending_questions,
      facts: checkpoint.facts,
      factEvidence: checkpoint.fact_evidence,
      roomContext: checkpoint.room_source === undefined ? undefined : {
        roomModel: checkpoint.room_model,
        roomSource: checkpoint.room_source,
      },
      sceneRef: checkpoint.scene_ref,
      exitReason: checkpoint.exit_reason,
      activeRoomId: checkpoint.active_room_id,
      customFurnitureSpec:
        checkpoint.custom_furniture_draft ?? checkpoint.custom_furniture_spec,
      customFurnitureResult,
      approvalRequired: checkpoint.approval_required,
      generationRunId: checkpoint.run_id,
      execution: agentExecutionFromCheckpoint(
        checkpoint,
        useDesignProjectStore.getState().projects[projectId]?.execution.events ?? [],
      ),
    });
    applyAuthoritativeOpenGeometry(projectId, checkpoint, setOpenGeometryState);
    setCustomFurniturePreviewSource(
      resolveCustomFurniturePreviewSource(checkpoint, customFurnitureResult),
    );
  }, [applyAgentState, projectId]);

  const refreshAgentCheckpointAfterConflict = useCallback(async () => {
    if (!projectId) return;
    const checkpoint = await fetchDesignAgentState(projectId);
    applyRefreshedAgentCheckpoint(checkpoint);
  }, [applyRefreshedAgentCheckpoint, projectId]);

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
    if (project) {
      setProjectRecovery("ready");
      return;
    }
    if (!projectId) {
      setProjectRecovery("missing");
      return;
    }
    let cancelled = false;
    setProjectRecovery("checking");
    void fetchDesignAgentState(projectId)
      .then((checkpoint) => {
        if (cancelled) return;
        if (checkpoint.task_id !== projectId) throw new Error("agent_task_mismatch");
        registerProject(
          checkpoint.task_id,
          checkpoint.active_mode,
          restoreDesignProjectSeed({
            confirmedRequirement: checkpoint.confirmed_requirement,
            facts: checkpoint.facts,
            roomModel: checkpoint.room_model,
            roomSource: checkpoint.room_source ?? null,
          }),
        );
        setProjectRecovery("ready");
      })
      .catch(() => {
        if (!cancelled) setProjectRecovery("missing");
      });
    return () => {
      cancelled = true;
    };
  }, [project, projectId, registerProject]);

  useEffect(() => {
    if (project) void refreshApprovals();
  }, [project?.id, refreshApprovals]);

  useEffect(() => {
    timelineEpochRef.current += 1;
    timelineInFlightRef.current = null;
    timelineRef.current = null;
    setTimeline(null);
    if (!project) return;
    const polling = createTaskTimelinePollingLoop({
      poll: async () => {
        const succeeded = await refreshTimeline(
          timelineRef.current ? "newer" : "initial",
        );
        if (!succeeded) throw new Error("timeline_unavailable");
      },
      isHidden: () => document.hidden,
    });
    const handleVisibilityChange = () => polling.visibilityChanged();
    document.addEventListener("visibilitychange", handleVisibilityChange);
    polling.start();
    return () => {
      timelineEpochRef.current += 1;
      polling.stop();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [project?.id, refreshTimeline]);

  useEffect(() => {
    if (!project) return;
    let cancelled = false;
    void Promise.all([
      fetchDesignAgentState(project.id),
      fetchDesignAgentEvents(project.id, { limit: 50 })
        .catch(() => ({ events: [], has_more: false, next_before_id: null })),
    ])
      .then(([checkpoint, eventFeed]) => {
        if (cancelled || checkpoint.task_id !== project.id) return;
        const customFurnitureResult = parseCustomFurniturePreview(checkpoint.result);
        applyAgentState(project.id, {
          stateVersion: checkpoint.state_version,
          status: checkpoint.status,
          activeMode: checkpoint.active_mode,
          pendingQuestions: checkpoint.pending_questions,
          facts: checkpoint.facts,
          factEvidence: checkpoint.fact_evidence,
          roomContext: checkpoint.room_source === undefined ? undefined : {
            roomModel: checkpoint.room_model,
            roomSource: checkpoint.room_source,
          },
          sceneRef: checkpoint.scene_ref,
          exitReason: checkpoint.exit_reason,
          activeRoomId: checkpoint.active_room_id,
          customFurnitureSpec:
            checkpoint.custom_furniture_draft ?? checkpoint.custom_furniture_spec,
          customFurnitureResult,
          approvalRequired: checkpoint.approval_required,
          generationRunId: checkpoint.run_id,
          execution: agentExecutionFromCheckpoint(
            checkpoint,
            mergeAgentExecutionEvents(
              useDesignProjectStore.getState().projects[project.id]?.execution.events ?? [],
              eventFeed.events,
            ),
          ),
        });
        applyAuthoritativeOpenGeometry(project.id, checkpoint, setOpenGeometryState);
        setCustomFurniturePreviewSource(
          resolveCustomFurniturePreviewSource(checkpoint, customFurnitureResult),
        );
        setMessages(
          project.id,
          checkpoint.messages.map((message) => ({
            id: `server-${message.id}`,
            role: message.role,
            content: message.content,
          })),
        );
        setCustomFurnitureDraftReference(
          project.id,
          restoreCustomFurnitureDraftReference(
            checkpoint.custom_furniture_draft,
            checkpoint.custom_furniture_draft_ref,
          ),
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
  }, [
    applyAgentState,
    project?.id,
    restoreServerPlans,
    setCustomFurnitureDraftReference,
    setMessages,
  ]);

  useEffect(() => {
    if (
      !project
      || project.status !== "running"
      || project.exitReason !== "generation_queued"
      || !project.generationRunId
    ) return;
    let cancelled = false;
    void resumeAgentGeneration(project.id, project.generationRunId)
      .then(async ({ checkpoint, plans }) => {
        if (cancelled || checkpoint.task_id !== project.id) return;
        const eventFeed = await fetchDesignAgentEvents(project.id, { limit: 50 })
          .catch(() => ({ events: [], has_more: false, next_before_id: null }));
        if (cancelled) return;
        const customFurnitureResult = parseCustomFurniturePreview(checkpoint.result);
        applyAgentState(project.id, {
          stateVersion: checkpoint.state_version,
          status: checkpoint.status,
          activeMode: checkpoint.active_mode,
          pendingQuestions: checkpoint.pending_questions,
          facts: checkpoint.facts,
          factEvidence: checkpoint.fact_evidence,
          roomContext: checkpoint.room_source === undefined ? undefined : {
            roomModel: checkpoint.room_model,
            roomSource: checkpoint.room_source,
          },
          sceneRef: checkpoint.scene_ref,
          exitReason: checkpoint.exit_reason,
          activeRoomId: checkpoint.active_room_id,
          customFurnitureSpec:
            checkpoint.custom_furniture_draft ?? checkpoint.custom_furniture_spec,
          customFurnitureResult,
          approvalRequired: checkpoint.approval_required,
          generationRunId: checkpoint.run_id,
          execution: agentExecutionFromCheckpoint(
            checkpoint,
            mergeAgentExecutionEvents(
              useDesignProjectStore.getState().projects[project.id]?.execution.events ?? [],
              eventFeed.events,
            ),
          ),
        });
        applyAuthoritativeOpenGeometry(project.id, checkpoint, setOpenGeometryState);
        setCustomFurniturePreviewSource(
          resolveCustomFurniturePreviewSource(checkpoint, customFurnitureResult),
        );
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
        void refreshTimeline("newer");
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
    refreshTimeline,
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

  useEffect(() => {
    setOpenGeometryState(
      project?.mode === "custom_furniture"
        ? emptyOpenGeometryState(project.id)
        : null,
    );
    setCustomFurniturePreviewSource(null);
  }, [project?.id, project?.mode]);

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
  const activeOpenGeometryPreview = customFurniturePreviewSource === "structured"
    ? null
    : openGeometryState?.current ?? null;
  const activeStructuredFurniturePreview = customFurniturePreviewSource === "open_geometry"
    ? null
    : project?.customFurnitureResult ?? null;
  const activeCustomFurnitureName = activeOpenGeometryPreview?.design.name
    ?? activeStructuredFurniturePreview?.spec.name
    ?? "自定义家具参数草案";
  const activeCustomFurnitureModelSpec = activeOpenGeometryPreview?.model_spec
    ?? activeStructuredFurniturePreview?.model_spec
    ?? null;
  const planMutationEventIds = useMemo(
    () => createPlanMutationEventIdResolver(projectId ?? 0),
    [projectId],
  );

  const handleApprovalDecision = useCallback(async (
    approval: AgentApproval,
    decision: "approve" | "reject",
    conclusion: string,
  ) => {
    if (!projectId) return;
    setDecidingApprovalId(approval.id);
    setApprovalsError("");
    try {
      const decided = await decideAgentApproval(projectId, approval.id, {
        clientDecisionId: `approval-${projectId}-${approval.id}-${decision}`,
        decision,
        conclusion,
      });
      setApprovals((current) => current.map((item) => (
        item.id === decided.id ? decided : item
      )));
      const checkpoint = await fetchDesignAgentState(projectId);
      if (
        activeProjectIdRef.current !== projectId
        || checkpoint.task_id !== projectId
      ) return;
      const customFurnitureResult = parseCustomFurniturePreview(checkpoint.result);
      applyAgentState(projectId, {
        stateVersion: checkpoint.state_version,
        status: checkpoint.status,
        activeMode: checkpoint.active_mode,
        pendingQuestions: checkpoint.pending_questions,
        facts: checkpoint.facts,
        factEvidence: checkpoint.fact_evidence,
        roomContext: checkpoint.room_source === undefined ? undefined : {
          roomModel: checkpoint.room_model,
          roomSource: checkpoint.room_source,
        },
        sceneRef: checkpoint.scene_ref,
        exitReason: checkpoint.exit_reason,
        activeRoomId: checkpoint.active_room_id,
        customFurnitureSpec:
          checkpoint.custom_furniture_draft ?? checkpoint.custom_furniture_spec,
        customFurnitureResult,
        approvalRequired: checkpoint.approval_required,
        generationRunId: checkpoint.run_id,
        execution: agentExecutionFromCheckpoint(
          checkpoint,
          useDesignProjectStore.getState().projects[projectId]?.execution.events ?? [],
        ),
      });
      applyAuthoritativeOpenGeometry(projectId, checkpoint, setOpenGeometryState);
      setCustomFurniturePreviewSource(
        resolveCustomFurniturePreviewSource(checkpoint, customFurnitureResult),
      );
      await refreshApprovals();
      await refreshTimeline("newer");
    } catch {
      setApprovalsError("审批决定提交失败，请刷新记录后重试。");
      void refreshApprovals();
    } finally {
      setDecidingApprovalId(null);
    }
  }, [applyAgentState, projectId, refreshApprovals, refreshTimeline]);

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
    const mutationSignature = JSON.stringify([
      activePlan.revisionVersion,
      activePlan.planVersionId,
      mutation.action,
      sourceInstanceId ?? null,
      mutation.targetSku ?? null,
      project.activeRoomId ?? null,
    ]);
    const clientMutationId = planMutationEventIds.resolve(
      mutationSignature,
      mutation.action,
    );
    const response = await mutateWorkspacePlan(project.id, {
      clientMutationId,
      baseRevisionVersion: activePlan.revisionVersion,
      planVersionId: activePlan.planVersionId,
      action: mutation.action,
      sourceInstanceId,
      targetSku: mutation.targetSku,
      roomId: project.activeRoomId,
    });
    planMutationEventIds.acknowledge(mutationSignature);
    setSceneReference(project.id, {
      scene_id: response.scene.id,
      version: response.scene.current_version,
    });
    await restoreServerPlans(project.id);
  }, [activePlan, planMutationEventIds, project, restoreServerPlans, setSceneReference]);

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

  const handleAuthoritativeScene = useCallback((scene: Parameters<
    typeof setAuthoritativeScene
  >[1]) => {
    if (!projectId) return;
    setAuthoritativeScene(projectId, scene);
  }, [projectId, setAuthoritativeScene]);

  const handleCustomDraftSaved = useCallback((reference: Parameters<
    typeof setCustomFurnitureDraftReference
  >[1], stateVersion: number) => {
    if (!projectId || !reference) return;
    setCustomFurnitureDraftReference(projectId, reference, stateVersion);
  }, [projectId, setCustomFurnitureDraftReference]);

  if (!project && projectRecovery === "checking") {
    return (
      <div className="flex min-h-[70vh] items-center justify-center bg-[#111713] px-5 text-center text-[#e5e8e1]">
        <p className="text-sm text-[#9ca69d]">正在载入你的设计…</p>
      </div>
    );
  }

  if (!project || !plan || !entry) {
    return (
      <div className="flex min-h-[70vh] items-center justify-center bg-[#111713] px-5 text-center text-[#e5e8e1]">
        <div>
          <AlertTriangle className="mx-auto h-8 w-8 text-[#f1c08b]" />
          <h1 className="mt-5 text-2xl !text-white">暂时找不到这份设计</h1>
          <p className="mt-3 max-w-sm text-sm leading-6 text-[#8f9a90]">你可以返回设计首页，选择最近的设计继续。</p>
          <Link to="/design/new" className="mt-5 inline-flex items-center gap-2 text-sm text-[#d5ff67]">
            <ArrowLeft className="h-4 w-4" /> 返回设计首页
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

  if (project.mode === "custom_furniture") {
    return <FurnitureDesignWorkspace
      key={project.id}
      title={project.title}
      connection={connectionLabel}
      name={activeCustomFurnitureName}
      source={customFurniturePreviewSource ?? "open_geometry"}
      onSourceChange={setCustomFurniturePreviewSource}
      versionLabel={activeOpenGeometryPreview
        ? `V${activeOpenGeometryPreview.version} · 已保存至服务端`
        : activeStructuredFurniturePreview ? "参数预览 · 报价与草稿状态见模板参数" : "尚无作品"}
      chat={<ChatPanel key={project.id} workspace projectId={project.id} activeMode={project.mode}
        activeRoomId={activeRoomId} sceneId={project.sceneRef?.scene_id} baseSceneVersion={project.sceneRef?.version}
        baseStateVersion={project.stateVersion} initialMessages={project.messages} pendingQuestions={project.pendingQuestions}
        onMessagesChange={(messages) => setMessages(project.id, messages)} onAgentResponse={applyWorkspaceAgentResponse}
        onAgentStateConflict={refreshAgentCheckpointAfterConflict} />}
      preview={activeCustomFurnitureModelSpec
        ? <Suspense fallback={<p className="p-6 text-sm">正在加载模型…</p>}><FurnitureModelViewer spec={activeCustomFurnitureModelSpec} /></Suspense>
        : <div className="flex h-full min-h-[360px] items-center justify-center text-center"><div><Box className="mx-auto mb-3 h-8 w-8 text-[#68796e]" /><p className="text-sm">尚无家具作品</p></div></div>}
      geometryTools={openGeometryState
        ? <OpenGeometryPanel taskId={project.id} state={openGeometryState} sceneReference={project.sceneRef}
            authoritativeScene={project.authoritativeScene} onCheckpointRefresh={applyRefreshedAgentCheckpoint} onSceneApplied={handleAuthoritativeScene} />
        : <p className="p-4 text-xs">正在读取作品状态…</p>}
      templateTools={<CustomFurniturePanel taskId={project.id} stateVersion={project.stateVersion}
        initialSpec={project.customFurnitureSpec} preview={project.customFurnitureResult} approvalRequired={project.approvalRequired}
        pendingQuestions={project.pendingQuestions} sceneReference={project.sceneRef} savedDraftReference={project.customFurnitureDraftReference}
        onDraftSaved={handleCustomDraftSaved} onSceneApplied={handleAuthoritativeScene} onAgentResponse={applyWorkspaceAgentResponse}
        onAgentStateConflict={refreshAgentCheckpointAfterConflict} onConversationTurn={appendConversationTurn} />}
      activity={<AgentExecutionPanel status={project.status} exitReason={project.exitReason} execution={project.execution}
        timeline={timeline} timelineLoading={timelineLoading} onLoadMore={() => { void refreshTimeline("older"); }} />}
      approvals={<AgentApprovalPanel approvals={approvals} loading={approvalsLoading} error={approvalsError}
        decidingId={decidingApprovalId} onDecision={(approval, decision, conclusion) => { void handleApprovalDecision(approval, decision, conclusion); }} />}
    />;
  }

  return (
    <div className="min-h-[calc(100dvh-4rem)] bg-[#f4f6f5] text-[#26372e]">
      <div className="mx-auto w-full">
        <header className="flex min-h-16 flex-wrap items-center justify-between gap-3 border-b border-[#d5dbd7] bg-[#f4f6f5] px-4 py-3">
          <div className="flex min-w-0 items-center gap-3">
            <Link
              to="/design/new"
              title="返回设计首页"
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded border border-[#d5dbd7] text-[#53655a] hover:bg-[#e1eae4]"
            >
              <ArrowLeft className="h-4 w-4" />
            </Link>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <CircleDot className={`h-3.5 w-3.5 shrink-0 ${agentConnection === "connected" ? "text-[#d5ff67]" : "text-[#f1c08b]"}`} />
                <h1 className="truncate text-sm font-medium !text-[#26372e]">{project.title}</h1>
              </div>
              <p className="mt-1 truncate font-mono text-[9px] tracking-[0.12em] text-[#778278] uppercase">
                {entry.shortTitle} / TASK {project.id} / {connectionLabel}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Link to={`/design/${project.id}/space`} className="inline-flex min-h-9 items-center gap-1.5 rounded border border-[#304e40] bg-[#304e40] px-3 text-xs text-white">
              <Map className="h-3.5 w-3.5" /> 整屋户型
            </Link>
            <Link
              to="/design/new"
              className="inline-flex min-h-9 items-center gap-1.5 rounded border border-[#d5dbd7] px-3 text-xs text-[#53655a] hover:bg-[#e1eae4]"
            >
              <Plus className="h-3.5 w-3.5" /> 新建设计
            </Link>
          </div>
        </header>

        <details className="border-b border-[#d5dbd7] text-xs">
        <summary className="cursor-pointer px-4 py-2 text-[#53655a]">执行记录 · {connectionLabel}</summary>
        <AgentExecutionPanel
          status={project.status}
          exitReason={project.exitReason}
          execution={project.execution}
          timeline={timeline}
          timelineLoading={timelineLoading}
          onLoadMore={() => { void refreshTimeline("older"); }}
        />
        </details>

        <AgentApprovalPanel
          approvals={approvals}
          loading={approvalsLoading}
          error={approvalsError}
          decidingId={decidingApprovalId}
          onDecision={(approval, decision, conclusion) => {
            void handleApprovalDecision(approval, decision, conclusion);
          }}
        />

        {planVersionId && <WorkspaceFeedbackControls
          planVersionId={planVersionId}
          satisfaction={satisfaction}
          delivery={feedback.deliveries[0] ?? null}
          onSatisfactionChange={setSatisfaction}
          onConfirm={confirmCurrentPlan}
          onRetry={feedback.retry}
        />}

        {catalogError && (
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

        <nav aria-label="移动端工作台视图" className="grid grid-cols-2 border-b border-[#d5dbd7] bg-white lg:hidden">
          {[
            { id: "conversation" as const, label: "对话", icon: MessageSquareText },
            { id: "scene" as const, label: "当前方案", icon: Box },
          ].map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setMobilePanel(item.id)}
                aria-pressed={mobilePanel === item.id}
                className={`flex min-h-11 items-center justify-center gap-2 text-xs font-medium ${mobilePanel === item.id ? "bg-[#e1eae4] text-[#304e40]" : "text-[#68796e]"}`}
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </button>
            );
          })}
        </nav>

        <div className="grid min-w-0 lg:grid-cols-[clamp(420px,38%,600px)_minmax(0,1fr)]">
          <section aria-label="空间设计对话" className={`min-w-0 border-r border-[#d5dbd7] lg:sticky lg:top-16 lg:h-[calc(100dvh-11rem)] lg:min-h-[540px] ${mobilePanel === "conversation" ? "flex" : "hidden lg:flex"} flex-col`}>
            <ChatPanel
              key={project.id}
              workspace
              projectId={project.id}
              activeMode={project.mode}
              activeRoomId={activeRoomId}
              sceneId={project.sceneRef?.scene_id}
              baseSceneVersion={project.sceneRef?.version}
              baseStateVersion={project.stateVersion}
              initialMessages={project.messages}
              pendingQuestions={project.pendingQuestions}
              onMessagesChange={(messages) => setMessages(project.id, messages)}
              onAgentResponse={applyWorkspaceAgentResponse}
              onAgentStateConflict={refreshAgentCheckpointAfterConflict}
            />
          </section>

          <main aria-label="当前空间方案" className={`relative min-w-0 bg-[#eef1f0] ${mobilePanel === "scene" ? "block" : "hidden lg:block"}`}>
            <div className="flex min-h-16 flex-wrap items-center justify-between gap-3 border-b border-[#d5dbd7] bg-white px-4 py-3 text-[#303831]">
              <div>
                <p className="font-mono text-[9px] tracking-[0.14em] text-[#69736a] uppercase">
                  当前方案 · {project.mode === "room_reconstruction" ? "房间设计" : "家具搭配"}
                </p>
                <p className="mt-0.5 text-xs font-medium">
                  {`${roomType} · ${selectedFurniture.length} 件家具`}
                </p>
              </div>
              <span className="text-[10px] text-[#69736a]">
                {plan.planVersionId ? `方案版本 ${plan.planVersionId}` : project.roomModel ? "空间草案 · 尚未生成搭配方案" : "等待空间需求"}
              </span>
            </div>
            <div className="flex flex-wrap gap-2 border-b border-[#d5dbd7] bg-white px-4 py-2" aria-label="方案工具栏">
              {([{id: 'room', label: '房间资料', icon: Map}, {id: 'catalog', label: '家具清单', icon: Box}, {id: 'budget', label: '预算明细', icon: CircleDollarSign}] as const).map(({id, label, icon: Icon}) => (
                <button key={id} type="button" aria-expanded={roomTool === id} aria-controls="room-workspace-tools" onClick={() => setRoomTool(roomTool === id ? null : id)}
                  className={`inline-flex min-h-10 items-center gap-2 rounded border px-3 text-xs ${roomTool === id ? 'border-[#304e40] bg-[#304e40] text-white' : 'border-[#d5dbd7] text-[#53655a]'}`}><Icon size={16} />{label}</button>
              ))}
            </div>
            <div id="room-workspace-tools" hidden={!roomTool} className="border-b border-[#d5dbd7] bg-[#f4f6f5] p-3 lg:absolute lg:right-0 lg:top-32 lg:z-30 lg:w-[360px] lg:max-w-full lg:shadow-lg">
              <div className="mb-2 flex justify-end"><button type="button" title="收起工具" aria-label="收起工具" onClick={() => setRoomTool(null)} className="flex h-9 w-9 items-center justify-center rounded border border-[#d5dbd7]"><X size={16} /></button></div>
              <DesignWorkspaceInspector project={project} catalog={catalog} catalogLoading={catalogLoading} plan={plan}
                activeTab={roomTool ?? (project.mode === 'room_reconstruction' ? 'room' : 'catalog')}
                onTabChange={setRoomTool} onPlanMutation={handlePlanMutation} />
            </div>
            {!project.roomModel && !planVersionId ? (
              <div className="flex min-h-[440px] items-center justify-center px-6 text-center">
                <div className="max-w-sm">
                  <Map className="mx-auto mb-4 h-10 w-10 text-[#68796e]" />
                  <h2 className="text-xl !text-[#304e40]">{project.mode === 'room_reconstruction' ? '从你的房间开始' : '为你的空间搭配家具'}</h2>
                  <button type="button" onClick={() => setRoomTool('room')} className="mt-6 inline-flex min-h-11 items-center gap-2 rounded bg-[#304e40] px-4 text-sm text-white"><Upload size={17} />导入户型图或房间照片</button>
                </div>
              </div>
            ) : <div className="relative isolate z-0 p-3 sm:p-4">
              <RoomView3D
                workspace
                key={sceneKey}
                plan={plan}
                roomType={roomType}
                roomModel={project.roomModel}
                onGlbLoadFailed={reportGlbLoadFailure}
                onSceneReferenceChange={handleSceneReferenceChange}
                authoritativeScene={project.authoritativeScene}
              />
              </div>}
          </main>
        </div>
      </div>
    </div>
  );
}
