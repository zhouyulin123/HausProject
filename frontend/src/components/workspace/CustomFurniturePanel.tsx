import { useEffect, useRef, useState, type FormEvent, type RefObject } from "react";
import {
  BadgeDollarSign,
  CircleCheck,
  Cuboid,
  Loader2,
  PanelsTopLeft,
  Ruler,
  Send,
  ShieldAlert,
  Table2,
} from "lucide-react";
import {
  addCustomFurnitureDraftToScene,
  ApiError,
  fetchDesignScene,
  saveCustomFurnitureDraft,
  sendAgentTurn,
  type AgentTurnResponse,
} from "@/api/designApi";
import {
  CABINET_MATERIALS,
  CABINET_PURPOSES,
  TABLE_MATERIALS,
  TABLE_PURPOSES,
  createCustomFurnitureDraft,
  customFurnitureDraftFromSpec,
  customFurnitureFocusField,
  quotePreviewDisplay,
} from "@/lib/customFurnitureWorkspace";
import { createCustomFurnitureDraftSaveCoordinator } from "@/lib/customFurnitureDraftQueue";
import {
  createCustomFurniturePlacementCoordinator,
  placeCustomFurnitureWithConflictRecovery,
} from "@/lib/customFurniturePlacement";
import type { AgentPendingQuestion } from "@/types/agent";
import type { AgentSceneReference } from "@/types/agent";
import type { DesignScene } from "@/types/scene";
import type { CustomFurnitureDraftReference } from "@/lib/designProject";
import type {
  CabinetCustomFurnitureSpec,
  CustomFurnitureFamily,
  CustomFurniturePreviewResult,
  CustomFurnitureSpec,
  CustomFurnitureSpecPatch,
  TableCustomFurnitureSpec,
} from "@/types/customFurniture";

interface CustomFurniturePanelProps {
  taskId: number;
  stateVersion: number;
  initialSpec: CustomFurnitureSpecPatch | null;
  preview: CustomFurniturePreviewResult | null;
  approvalRequired: boolean;
  pendingQuestions: AgentPendingQuestion[];
  sceneReference: AgentSceneReference | null;
  savedDraftReference: CustomFurnitureDraftReference | null;
  onDraftSaved: (
    reference: CustomFurnitureDraftReference,
    stateVersion: number,
  ) => void;
  onSceneApplied: (scene: DesignScene) => void;
  onAgentResponse: (response: AgentTurnResponse) => void;
  onAgentStateConflict?: () => Promise<void>;
  onConversationTurn: (message: string, reply: string) => void;
}

export class StructuredFurnitureCheckpointRefreshError extends Error {
  constructor() {
    super("structured_furniture_checkpoint_refresh_failed");
    this.name = "StructuredFurnitureCheckpointRefreshError";
  }
}

function isAgentStateConflict(error: unknown): boolean {
  const detail = error instanceof ApiError
    && typeof error.detail === "object"
    && error.detail
    ? error.detail as { code?: string }
    : null;
  return error instanceof ApiError
    && error.status === 409
    && detail?.code === "agent_state_conflict";
}

export async function submitStructuredFurnitureTurnWithConflictRecovery<T>({
  submit,
  refresh,
}: {
  submit: () => Promise<T>;
  refresh: () => Promise<void>;
}): Promise<T> {
  try {
    return await submit();
  } catch (cause) {
    if (!isAgentStateConflict(cause)) throw cause;
    try {
      await refresh();
    } catch {
      throw new StructuredFurnitureCheckpointRefreshError();
    }
    throw cause;
  }
}

function structuredFurnitureSubmitErrorMessage(error: unknown): string {
  if (error instanceof StructuredFurnitureCheckpointRefreshError) {
    return "设计状态已变化且最新状态读取失败。请刷新页面后再继续提交。";
  }
  if (isAgentStateConflict(error)) {
    return "设计状态已更新，已恢复最新参数。请确认后重新提交。";
  }
  return "参数提交失败，本次没有生成或更新预览。可直接重试。";
}

const inputClass =
  "min-h-10 w-full border border-white/15 bg-[#111713] px-3 text-xs text-[#e2e7df] outline-none transition focus:border-[#d5ff67] focus:ring-1 focus:ring-[#d5ff67]/30";

function nextTurnId(taskId: number) {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `custom-${taskId}-${Date.now()}`;
}

function QuestionHint({ question }: { question?: AgentPendingQuestion }) {
  if (!question) return null;
  return (
    <div className="mt-3 border-l-2 border-[#d5ff67] pl-3" role="status">
      <p className="text-xs leading-5 text-[#e4e9df]">{question.prompt}</p>
      <p className="mt-1 text-[10px] leading-4 text-[#818c82]">{question.reason}</p>
    </div>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  step = 1,
  readOnly = false,
  inputRef,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  readOnly?: boolean;
  inputRef?: RefObject<HTMLInputElement>;
  onChange: (value: number) => void;
}) {
  return (
    <label className="min-w-0 text-[10px] text-[#89948b]">
      <span className="mb-1.5 block">{label}</span>
      <input
        ref={inputRef}
        type="number"
        required
        min={min}
        max={max}
        step={step}
        readOnly={readOnly}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className={`${inputClass} tabular-nums read-only:cursor-not-allowed read-only:bg-[#1c231d] read-only:text-[#778178]`}
      />
    </label>
  );
}

export default function CustomFurniturePanel({
  taskId,
  stateVersion,
  initialSpec,
  preview,
  approvalRequired,
  pendingQuestions,
  sceneReference,
  savedDraftReference,
  onDraftSaved,
  onSceneApplied,
  onAgentResponse,
  onAgentStateConflict,
  onConversationTurn,
}: CustomFurniturePanelProps) {
  const [draft, setDraft] = useState<CustomFurnitureSpec>(() =>
    customFurnitureDraftFromSpec(initialSpec),
  );
  const [submitting, setSubmitting] = useState(false);
  const [stateSyncBlocked, setStateSyncBlocked] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [draftSaveError, setDraftSaveError] = useState("");
  const [placing, setPlacing] = useState(false);
  const [placementError, setPlacementError] = useState("");
  const [placementPosition, setPlacementPosition] = useState({ x: 0, z: 0 });
  const lastSubmissionRef = useRef<{ signature: string; turnId: string } | null>(null);
  const initialDraftSignatureRef = useRef(JSON.stringify(draft));
  const draftCoordinatorRef = useRef<ReturnType<
    typeof createCustomFurnitureDraftSaveCoordinator
  > | null>(null);
  const placementCoordinatorRef = useRef<ReturnType<
    typeof createCustomFurniturePlacementCoordinator<DesignScene>
  > | null>(null);
  const familyRef = useRef<HTMLButtonElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const purposeRef = useRef<HTMLSelectElement>(null);
  const materialRef = useRef<HTMLSelectElement>(null);
  const dimensionsRef = useRef<HTMLInputElement>(null);
  const structureRef = useRef<HTMLSelectElement>(null);
  const focusField = customFurnitureFocusField(pendingQuestions);

  useEffect(() => {
    const coordinator = createCustomFurnitureDraftSaveCoordinator({
      initialStateVersion: stateVersion,
      createMutationId: () => nextTurnId(taskId),
      save: (payload) => saveCustomFurnitureDraft(taskId, payload),
      onSynced: ({ stateVersion: savedStateVersion, spec, clientMutationId }) => {
        initialDraftSignatureRef.current = JSON.stringify(spec);
        onDraftSaved({
          clientMutationId,
          specSignature: JSON.stringify(spec),
        }, savedStateVersion);
        setDraftSaveError("");
      },
      onError: () => {
        setDraftSaveError("服务端状态已变化或网络中断，草稿未覆盖远端版本。可重试同步。");
      },
    });
    draftCoordinatorRef.current = coordinator;
    return () => {
      coordinator.dispose();
      if (draftCoordinatorRef.current === coordinator) {
        draftCoordinatorRef.current = null;
      }
    };
  }, [onDraftSaved, taskId]);

  useEffect(() => {
    placementCoordinatorRef.current = createCustomFurniturePlacementCoordinator({
      createMutationId: () => nextTurnId(taskId),
      add: ({ sceneId, ...payload }) =>
        addCustomFurnitureDraftToScene(sceneId, payload),
    });
    return () => {
      placementCoordinatorRef.current = null;
    };
  }, [taskId]);

  useEffect(() => {
    if (initialSpec) {
      const restored = customFurnitureDraftFromSpec(initialSpec);
      initialDraftSignatureRef.current = JSON.stringify(restored);
      setDraft(restored);
    }
  }, [initialSpec]);

  useEffect(() => {
    draftCoordinatorRef.current?.updateStateVersion(stateVersion);
    setStateSyncBlocked(false);
  }, [stateVersion]);

  useEffect(() => {
    const signature = JSON.stringify(draft);
    if (signature === initialDraftSignatureRef.current) return;
    draftCoordinatorRef.current?.schedule(draft);
  }, [draft]);

  useEffect(() => {
    if (!focusField) return;
    const targets = {
      family: familyRef,
      name: nameRef,
      purpose: purposeRef,
      material: materialRef,
      dimensions: dimensionsRef,
      structure: structureRef,
    };
    targets[focusField].current?.focus({ preventScroll: true });
  }, [focusField]);

  const questionFor = (field: string) =>
    pendingQuestions.find(
      (question) => question.field === `custom_furniture_spec.${field}`,
    );
  const sectionClass = (...fields: string[]) =>
    `border-t pt-4 ${focusField && fields.includes(focusField) ? "border-[#d5ff67]" : "border-white/10"}`;

  const setFamily = (family: CustomFurnitureFamily) => {
    setDraft(createCustomFurnitureDraft(family));
    setSubmitError("");
  };
  const setDimensions = (next: Partial<CustomFurnitureSpec["dimensions"]>) =>
    setDraft((current) => ({
      ...current,
      dimensions: { ...current.dimensions, ...next },
    }) as CustomFurnitureSpec);
  const updateCabinetStructure = (
    next: Partial<CabinetCustomFurnitureSpec["structure"]>,
  ) => setDraft((current) => current.family === "cabinet"
    ? { ...current, structure: { ...current.structure, ...next } }
    : current);
  const updateTableStructure = (
    next: Partial<TableCustomFurnitureSpec["structure"]>,
  ) => setDraft((current) => current.family === "table"
    ? { ...current, structure: { ...current.structure, ...next } }
    : current);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (submitting || stateSyncBlocked) return;
    const signature = JSON.stringify(draft);
    const turnId =
      lastSubmissionRef.current?.signature === signature
        ? lastSubmissionRef.current.turnId
        : nextTurnId(taskId);
    lastSubmissionRef.current = { signature, turnId };
    const message = `提交${draft.name}的结构化参数，生成参数预览与确定性报价。`;
    setSubmitting(true);
    setSubmitError("");
    try {
      const response = await submitStructuredFurnitureTurnWithConflictRecovery({
        submit: () => sendAgentTurn(taskId, {
          client_turn_id: turnId,
          message,
          active_mode: "custom_furniture",
          base_state_version: stateVersion,
          custom_furniture_spec: draft,
        }),
        refresh: async () => {
          if (!onAgentStateConflict) {
            throw new StructuredFurnitureCheckpointRefreshError();
          }
          await onAgentStateConflict();
        },
      });
      onAgentResponse(response);
      onConversationTurn(message, response.reply);
    } catch (cause) {
      if (cause instanceof StructuredFurnitureCheckpointRefreshError) {
        setStateSyncBlocked(true);
      }
      setSubmitError(structuredFurnitureSubmitErrorMessage(cause));
    } finally {
      setSubmitting(false);
    }
  };

  const quote = preview ? quotePreviewDisplay(preview.quote_preview) : null;
  const draftSignature = JSON.stringify(draft);
  const placementReady = Boolean(
    sceneReference
    && savedDraftReference
    && savedDraftReference.specSignature === draftSignature,
  );
  const purposes = draft.family === "cabinet" ? CABINET_PURPOSES : TABLE_PURPOSES;
  const materials = draft.family === "cabinet" ? CABINET_MATERIALS : TABLE_MATERIALS;

  const placeInRoom = async () => {
    if (!sceneReference || !savedDraftReference || !placementReady || placing) return;
    setPlacing(true);
    setPlacementError("");
    try {
      const outcome = await placeCustomFurnitureWithConflictRecovery({
        place: () => placementCoordinatorRef.current!.place({
          sceneId: sceneReference.scene_id,
          baseVersion: sceneReference.version,
          draftClientMutationId: savedDraftReference.clientMutationId,
          position: placementPosition,
          rotationY: 0,
        }),
        reload: () => fetchDesignScene(sceneReference.scene_id),
        apply: onSceneApplied,
      });
      if (outcome === "conflict_recovered") {
        setPlacementError("房间已在其他页面更新，已恢复最新版本，请再次加入。");
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setPlacementError("房间版本冲突且恢复失败，请检查网络后重试。");
      } else if (error instanceof ApiError && error.status === 422) {
        setPlacementError("当前草稿无法加入房间，请先重新保存草稿或调整摆放位置。");
      } else {
        setPlacementError("加入结果未知，可直接重试；系统会复用同一幂等请求。");
      }
    } finally {
      setPlacing(false);
    }
  };

  return (
    <aside className="overflow-hidden rounded-lg border border-[#293229] bg-[#171e18] text-[#e3e7df] xl:h-[calc(100vh-8.5rem)] xl:min-h-[620px]">
      <form onSubmit={(event) => void submit(event)} className="thin-scrollbar h-[680px] overflow-y-auto p-4 xl:h-full">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="font-mono text-[9px] tracking-[0.16em] text-[#7f8b81] uppercase">Custom furniture</p>
            <h2 className="mt-1 text-sm font-medium !text-[#eef1ea]">结构化参数</h2>
          </div>
          <span className="border border-[#d5ff67]/30 px-2 py-1 font-mono text-[9px] text-[#d5ff67]">SERVER DRAFT</span>
        </div>

        <section className="mt-5">
          <p className="mb-2 text-[10px] text-[#89948b]">01 / 家具族</p>
          <div className="grid grid-cols-2 border border-white/12 p-1">
            {([
              ["cabinet", "柜体", PanelsTopLeft],
              ["table", "桌类", Table2],
            ] as const).map(([family, label, Icon], index) => (
              <button
                key={family}
                ref={index === 0 ? familyRef : undefined}
                type="button"
                aria-pressed={draft.family === family}
                onClick={() => setFamily(family)}
                className={`flex min-h-10 items-center justify-center gap-2 text-xs ${draft.family === family ? "bg-[#d5ff67] text-[#111713]" : "text-[#9da79e]"}`}
              >
                <Icon className="h-4 w-4" /> {label}
              </button>
            ))}
          </div>
          <QuestionHint question={questionFor("family")} />
        </section>

        <section className={`mt-5 ${sectionClass("name", "purpose", "material")}`}>
          <p className="mb-3 text-[10px] text-[#89948b]">02 / 用途与材料</p>
          <div className="space-y-3">
            <label className="block text-[10px] text-[#89948b]">
              <span className="mb-1.5 block">草案名称</span>
              <input
                ref={nameRef}
                required
                maxLength={100}
                value={draft.name}
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                className={inputClass}
              />
            </label>
            <label className="block text-[10px] text-[#89948b]">
              <span className="mb-1.5 block">用途</span>
              <select
                ref={purposeRef}
                value={draft.purpose}
                onChange={(event) => setDraft({ ...draft, purpose: event.target.value } as CustomFurnitureSpec)}
                className={inputClass}
              >
                {purposes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            <label className="block text-[10px] text-[#89948b]">
              <span className="mb-1.5 block">材料档位</span>
              <select
                ref={materialRef}
                value={draft.material}
                onChange={(event) => setDraft({ ...draft, material: event.target.value } as CustomFurnitureSpec)}
                className={inputClass}
              >
                {materials.map((value) => <option key={value}>{value}</option>)}
              </select>
            </label>
          </div>
          <QuestionHint question={questionFor("name") ?? questionFor("purpose") ?? questionFor("material")} />
        </section>

        <section className={`mt-5 ${sectionClass("dimensions")}`}>
          <div className="mb-3 flex items-center gap-2 text-[10px] text-[#89948b]"><Ruler className="h-3.5 w-3.5" />03 / 毫米尺寸</div>
          <div className="grid grid-cols-2 gap-2">
            <NumberField
              label="宽度（mm）"
              inputRef={dimensionsRef}
              value={draft.dimensions.width_mm}
              min={draft.family === "cabinet" ? 400 : 600}
              max={draft.family === "cabinet" ? 5000 : 3000}
              step={10}
              onChange={(value) => setDimensions({
                width_mm: value,
                ...(draft.family === "table" && draft.structure.top_shape === "round" ? { depth_mm: value } : {}),
              })}
            />
            <NumberField label="高度（mm）" value={draft.dimensions.height_mm} min={draft.family === "cabinet" ? 600 : 650} max={draft.family === "cabinet" ? 3000 : 1100} step={10} onChange={(value) => setDimensions({ height_mm: value })} />
            <NumberField label="深度（mm）" value={draft.dimensions.depth_mm} min={draft.family === "cabinet" ? 250 : 450} max={draft.family === "cabinet" ? 1000 : 1600} step={10} readOnly={draft.family === "table" && draft.structure.top_shape === "round"} onChange={(value) => setDimensions({ depth_mm: value })} />
          </div>
          <QuestionHint question={questionFor("dimensions")} />
        </section>

        <section className={`mt-5 ${sectionClass("structure")}`}>
          <p className="mb-3 text-[10px] text-[#89948b]">04 / 结构参数</p>
          {draft.family === "cabinet" ? (
            <div className="grid grid-cols-2 gap-2">
              <label className="col-span-2 text-[10px] text-[#89948b]">
                <span className="mb-1.5 block">门型</span>
                <select
                  ref={structureRef}
                  value={draft.structure.door_style}
                  onChange={(event) => {
                    const doorStyle = event.target.value as CabinetCustomFurnitureSpec["structure"]["door_style"];
                    updateCabinetStructure({ door_style: doorStyle, door_count: doorStyle === "open" ? 0 : Math.max(doorStyle === "sliding" ? 2 : 1, draft.structure.door_count) });
                  }}
                  className={inputClass}
                >
                  <option value="hinged">平开门</option><option value="sliding">移门</option><option value="open">开放式</option>
                </select>
              </label>
              <NumberField label="门扇" value={draft.structure.door_count} min={draft.structure.door_style === "open" ? 0 : 1} max={10} readOnly={draft.structure.door_style === "open"} onChange={(value) => updateCabinetStructure({ door_count: value })} />
              <NumberField label="分区" value={draft.structure.compartment_count} min={1} max={12} onChange={(value) => updateCabinetStructure({ compartment_count: value })} />
              <NumberField label="层板" value={draft.structure.shelf_count} min={0} max={24} onChange={(value) => updateCabinetStructure({ shelf_count: value })} />
              <NumberField label="抽屉" value={draft.structure.drawer_count} min={0} max={12} onChange={(value) => updateCabinetStructure({ drawer_count: value })} />
              <NumberField label="板厚（mm）" value={draft.structure.panel_thickness_mm} min={16} max={25} onChange={(value) => updateCabinetStructure({ panel_thickness_mm: value })} />
              <NumberField label="柜脚（mm）" value={draft.structure.leg_height_mm} min={0} max={250} step={5} onChange={(value) => updateCabinetStructure({ leg_height_mm: value })} />
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-2">
              <label className="text-[10px] text-[#89948b]">
                <span className="mb-1.5 block">台面形状</span>
                <select
                  ref={structureRef}
                  value={draft.structure.top_shape}
                  onChange={(event) => {
                    const topShape = event.target.value as TableCustomFurnitureSpec["structure"]["top_shape"];
                    updateTableStructure({ top_shape: topShape });
                    if (topShape === "round") setDimensions({ depth_mm: draft.dimensions.width_mm });
                  }}
                  className={inputClass}
                ><option value="rectangle">矩形</option><option value="round">圆形</option></select>
              </label>
              <label className="text-[10px] text-[#89948b]">
                <span className="mb-1.5 block">支撑结构</span>
                <select
                  value={draft.structure.base_style}
                  onChange={(event) => {
                    const baseStyle = event.target.value as TableCustomFurnitureSpec["structure"]["base_style"];
                    updateTableStructure({ base_style: baseStyle, support_count: { four_leg: 4, pedestal: 1, trestle: 2 }[baseStyle] });
                  }}
                  className={inputClass}
                ><option value="four_leg">四腿</option><option value="pedestal">中央柱</option><option value="trestle">栈桥式</option></select>
              </label>
              <NumberField label="支撑数" value={draft.structure.support_count} min={1} max={4} readOnly onChange={() => undefined} />
              <NumberField label="座位数" value={draft.structure.seat_count} min={1} max={12} onChange={(value) => updateTableStructure({ seat_count: value })} />
              <NumberField label="台面厚（mm）" value={draft.structure.top_thickness_mm} min={18} max={80} onChange={(value) => updateTableStructure({ top_thickness_mm: value })} />
              <NumberField label="边缘圆角（mm）" value={draft.structure.edge_radius_mm} min={0} max={80} onChange={(value) => updateTableStructure({ edge_radius_mm: value })} />
            </div>
          )}
          <QuestionHint question={questionFor("structure")} />
        </section>

        {preview && quote && (
          <section className="mt-5 border-t border-white/10 pt-4">
            <div className="flex items-center gap-2">
              {preview.status === "preview_ready" ? <CircleCheck className="h-4 w-4 text-[#d5ff67]" /> : <ShieldAlert className="h-4 w-4 text-[#f1c08b]" />}
              <p className="text-xs font-medium">{preview.status === "preview_ready" ? "参数预览已就绪" : "参数预览需人工确认"}</p>
            </div>
            <div className="mt-3 border-y border-white/10 py-3">
              <div className="flex items-center justify-between gap-3 text-xs">
                <span className="flex items-center gap-1.5 text-[#89948b]"><BadgeDollarSign className="h-3.5 w-3.5" />{quote.state}</span>
                {quote.amount && <strong className="font-mono text-[#d5ff67]">{quote.amount}</strong>}
              </div>
              <p className="mt-2 text-[10px] leading-4 text-[#7f8b81]">{quote.reason}</p>
            </div>
            <p className="mt-3 text-[10px] text-[#f1c08b]">工程状态：待工程复核</p>
            {approvalRequired && <p className="mt-2 text-[10px] text-[#f1c08b]">审批状态：需要人工确认报价</p>}
            {preview.warnings.map((warning) => <p key={warning} className="mt-2 text-[10px] leading-4 text-[#89948b]">{warning}</p>)}
          </section>
        )}

        <section className="mt-5 border-t border-white/10 pt-4">
          <div className="flex items-center gap-2">
            <Cuboid className="h-4 w-4 text-[#d5ff67]" />
            <p className="text-xs font-medium">加入当前房间</p>
          </div>
          <p className="mt-2 text-[10px] leading-4 text-[#89948b]">
            作为参数化草稿体块加入版本化 3D 房间，可继续移动或删除；不代表制造级资产或正式商品。
          </p>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <NumberField label="房间 X（m）" value={placementPosition.x} min={-20} max={20} step={0.1} onChange={(x) => setPlacementPosition((current) => ({ ...current, x }))} />
            <NumberField label="房间 Z（m）" value={placementPosition.z} min={-20} max={20} step={0.1} onChange={(z) => setPlacementPosition((current) => ({ ...current, z }))} />
          </div>
          <button
            type="button"
            data-placement-ready={placementReady ? "true" : "false"}
            disabled={!placementReady || placing}
            onClick={() => void placeInRoom()}
            className="mt-3 flex min-h-10 w-full items-center justify-center gap-2 border border-[#d5ff67]/45 px-3 text-xs font-medium text-[#d5ff67] transition-colors hover:bg-[#d5ff67]/10 disabled:cursor-not-allowed disabled:border-white/10 disabled:text-[#667068]"
          >
            {placing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Cuboid className="h-4 w-4" />}
            {placing ? "正在加入房间" : "加入当前房间"}
          </button>
          {!sceneReference && <p className="mt-2 text-[10px] text-[#f1c08b]">当前没有已恢复的服务端房间场景。</p>}
          {sceneReference && !placementReady && <p className="mt-2 text-[10px] text-[#f1c08b]">请等待当前草稿成功保存后再加入。</p>}
          {placementError && <p role="alert" className="mt-2 text-[10px] leading-4 text-[#f1b59e]">{placementError}</p>}
        </section>

        {submitError && <p role="alert" className="mt-4 border border-[#8f4938] bg-[#2b1c18] px-3 py-2 text-xs text-[#f1b59e]">{submitError}</p>}
        {draftSaveError && (
          <div role="alert" className="mt-4 border border-[#8f7040] bg-[#2b2718] px-3 py-2 text-xs text-[#f0d39e]">
            <p>{draftSaveError}</p>
            <button
              type="button"
              onClick={() => draftCoordinatorRef.current?.retryLatest()}
              className="mt-2 min-h-9 border border-[#f0d39e]/40 px-3 text-[11px] text-[#f0d39e]"
            >
              重试同步
            </button>
          </div>
        )}
        <button
          type="submit"
          disabled={submitting || stateSyncBlocked || !draft.name.trim()}
          className="mt-5 flex min-h-11 w-full items-center justify-center gap-2 bg-[#d5ff67] px-3 text-xs font-semibold text-[#111713] transition-colors hover:bg-[#e0ff91] disabled:cursor-wait disabled:opacity-55"
        >
          {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          {submitting ? "正在校验与生成" : "生成参数预览"}
        </button>
      </form>
    </aside>
  );
}
