import { useRef, useState } from "react";
import {
  ArrowLeftRight,
  Box,
  Check,
  CircleDollarSign,
  Loader2,
  Map,
  Plus,
  Search,
  Upload,
  X,
} from "lucide-react";
import { analyzeRoomImage } from "@/api/designApi";
import type { DesignProject } from "@/lib/designProject";
import { useDesignProjectStore } from "@/store/useDesignProjectStore";
import { useRoomModelStore } from "@/store/useRoomModelStore";
import type { FurnitureItem } from "@/types/furniture";
import { getFurnitureDataOriginLabel } from "@/lib/furnitureDataOrigin";
import {
  buildFurnitureFeedbackEvent,
  buildReplaceFeedbackEvent,
  createFeedbackClientEventId,
} from "@/lib/workspaceFeedback";
import type { DesignFeedbackEventRequest } from "@/types/feedback";

type InspectorTab = "room" | "catalog" | "budget";

export function commitFurnitureReplacement(input: {
  replaceSelection: () => boolean;
  clientEventId: string;
  planVersionId: number | null;
  sourceSku: string | undefined;
  targetSku: string | undefined;
  roomId: string | null;
}): { completed: boolean; event: DesignFeedbackEventRequest | null } {
  if (!input.replaceSelection()) return { completed: false, event: null };
  return { completed: true, event: buildReplaceFeedbackEvent(input) };
}

function amountFromPrice(text: string): number {
  const values = text.replace(/,/g, "").match(/\d+(?:\.\d+)?/g);
  return values?.length ? Number(values[0]) : 0;
}

export default function DesignWorkspaceInspector({
  project,
  catalog,
  catalogLoading,
  budget,
  planVersionId,
  onFeedbackEvent,
}: {
  project: DesignProject;
  catalog: FurnitureItem[];
  catalogLoading: boolean;
  budget: number;
  planVersionId: number | null;
  onFeedbackEvent: (event: DesignFeedbackEventRequest, label: string) => void;
}) {
  const [tab, setTab] = useState<InspectorTab>(
    project.mode === "room_reconstruction" ? "room" : "catalog",
  );
  const [query, setQuery] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [replacementSourceId, setReplacementSourceId] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const toggleFurniture = useDesignProjectStore((state) => state.toggleFurniture);
  const replaceFurniture = useDesignProjectStore((state) => state.replaceFurniture);
  const setProjectRoomModel = useDesignProjectStore((state) => state.setRoomModel);

  const selectedItems = catalog.filter((item) =>
    project.selectedFurnitureIds.includes(item.id),
  );
  const furnitureSubtotal = selectedItems.reduce(
    (sum, item) => sum + amountFromPrice(item.priceRange),
    0,
  );
  const filteredCatalog = catalog
    .filter((item) =>
      `${item.name}${item.category}${item.room}${item.material}`
        .toLowerCase()
        .includes(query.trim().toLowerCase()),
    )
    .slice(0, 12);
  const replacementSource = replacementSourceId
    ? selectedItems.find((item) => item.id === replacementSourceId) ?? null
    : null;

  const toggleCatalogItem = (item: FurnitureItem) => {
    const currentProject = useDesignProjectStore.getState().projects[project.id];
    const selectedBeforeToggle = currentProject?.selectedFurnitureIds.includes(item.id) ?? false;
    toggleFurniture(project.id, item.id);
    const action = selectedBeforeToggle ? "remove" : "adopt";
    const request = buildFurnitureFeedbackEvent({
      clientEventId: createFeedbackClientEventId(project.id, action),
      selectedBeforeToggle,
      planVersionId,
      sku: item.sku,
      roomId: project.activeRoomId,
    });
    if (request) {
      onFeedbackEvent(
        request,
        selectedBeforeToggle ? `移除“${item.name}”` : `采用“${item.name}”`,
      );
    }
  };

  const replaceWithCatalogItem = (target: FurnitureItem) => {
    if (!replacementSource) return;
    const replacement = commitFurnitureReplacement({
      replaceSelection: () => replaceFurniture(
        project.id,
        replacementSource.id,
        target.id,
      ),
      clientEventId: createFeedbackClientEventId(project.id, "replace"),
      planVersionId,
      sourceSku: replacementSource.sku,
      targetSku: target.sku,
      roomId: project.activeRoomId,
    });
    if (!replacement.completed) return;
    setReplacementSourceId(null);
    if (replacement.event) {
      onFeedbackEvent(
        replacement.event,
        `用“${target.name}”替换“${replacementSource.name}”`,
      );
    }
  };

  const uploadRoom = async (file: File) => {
    setUploading(true);
    setUploadError("");
    try {
      const analysis = await analyzeRoomImage(file, project.id);
      setProjectRoomModel(project.id, analysis.roomModel ?? null);
      useRoomModelStore.getState().setRoomModel(analysis.roomModel ?? null);
      if (!analysis.roomModel) {
        setUploadError("识别结果缺少可用空间模型，请更换清晰图片。");
      }
    } catch {
      setUploadError("房间识别失败，请检查服务后重试。");
    } finally {
      setUploading(false);
    }
  };

  const tabs = [
    { id: "room" as const, label: "房间", icon: Map },
    { id: "catalog" as const, label: "家具", icon: Box },
    { id: "budget" as const, label: "预算", icon: CircleDollarSign },
  ];

  return (
    <aside className="overflow-hidden rounded-lg border border-[#293229] bg-[#171e18] text-[#e3e7df] xl:h-[calc(100vh-8.5rem)] xl:min-h-[620px]">
      <div className="grid grid-cols-3 border-b border-white/10">
        {tabs.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => setTab(item.id)}
              className={`flex min-h-12 items-center justify-center gap-1.5 text-xs transition-colors ${
                tab === item.id
                  ? "bg-[#d5ff67] text-[#111713]"
                  : "text-[#909b91] hover:bg-white/5 hover:text-white"
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              {item.label}
            </button>
          );
        })}
      </div>

      <div className="thin-scrollbar h-[620px] overflow-y-auto p-4 xl:h-[calc(100%-3rem)]">
        {tab === "room" && (
          <div>
            <div className="flex items-center justify-between">
              <p className="font-mono text-[10px] tracking-[0.16em] text-[#7f8b81] uppercase">Room facts</p>
              <span className={`h-2 w-2 rounded-full ${project.roomModel ? "bg-[#d5ff67]" : "bg-[#667168]"}`} />
            </div>
            {project.roomModel ? (
              <dl className="mt-5 divide-y divide-white/10 border-y border-white/10 text-xs">
                <div className="flex justify-between gap-4 py-3"><dt className="text-[#7f8b81]">空间</dt><dd>{project.roomModel.spaceType ?? "待确认"}</dd></div>
                <div className="flex justify-between gap-4 py-3"><dt className="text-[#7f8b81]">房间</dt><dd>{project.roomModel.rooms.length} 个</dd></div>
                <div className="flex justify-between gap-4 py-3"><dt className="text-[#7f8b81]">门 / 窗</dt><dd>{project.roomModel.doors.length} / {project.roomModel.windows.length}</dd></div>
                <div className="flex justify-between gap-4 py-3"><dt className="text-[#7f8b81]">置信度</dt><dd>{Math.round(project.roomModel.confidence * 100)}%</dd></div>
                <div className="flex justify-between gap-4 py-3"><dt className="text-[#7f8b81]">尺度</dt><dd>{project.roomModel.scale.source === "user" ? "已校准" : "估算 / 待校准"}</dd></div>
              </dl>
            ) : (
              <div className="mt-5 border border-dashed border-white/15 p-4 text-xs leading-6 text-[#8d978e]">当前项目还没有房间模型。</div>
            )}
            <input
              ref={fileRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void uploadRoom(file);
                event.target.value = "";
              }}
            />
            <button
              type="button"
              disabled={uploading}
              onClick={() => fileRef.current?.click()}
              className="mt-4 flex min-h-11 w-full items-center justify-center gap-2 bg-[#d5ff67] px-3 text-xs font-semibold text-[#111713] transition-colors hover:bg-[#e0ff91] disabled:opacity-50"
            >
              {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
              {uploading ? "正在识别" : project.roomModel ? "重新导入房间" : "导入户型图或照片"}
            </button>
            {uploadError && <p role="alert" className="mt-3 text-xs leading-5 text-[#f1b59e]">{uploadError}</p>}
            {project.roomModel?.requiresConfirmation.map((item) => (
              <p key={item} className="mt-3 border-l-2 border-[#f1c08b] pl-3 text-xs leading-5 text-[#b8c0b9]">{item}</p>
            ))}
            {project.pendingQuestions.map((question) => (
              <div key={`${question.field}-${question.prompt}`} className="mt-3 border-l-2 border-[#d5ff67] pl-3">
                <p className="text-xs leading-5 text-[#dce2da]">{question.prompt}</p>
                <p className="mt-1 text-[10px] leading-4 text-[#7f8b81]">{question.reason}</p>
              </div>
            ))}
          </div>
        )}

        {tab === "catalog" && (
          <div>
            {selectedItems.length > 0 && (
              <section className="mb-4 border-b border-white/10 pb-4" aria-label="已选家具替换">
                <div className="flex items-center justify-between gap-3">
                  <p className="font-mono text-[10px] tracking-[0.14em] text-[#7f8b81] uppercase">
                    已选家具
                  </p>
                  <span className="text-[10px] text-[#657067]">{selectedItems.length} 件</span>
                </div>
                <div className="mt-2 space-y-1.5">
                  {selectedItems.map((item) => (
                    <div
                      key={item.id}
                      className="grid min-h-9 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 border border-white/10 px-2"
                    >
                      <span className="truncate text-[11px] text-[#c5ccc5]">{item.name}</span>
                      <button
                        type="button"
                        aria-label={`替换${item.name}`}
                        aria-pressed={replacementSourceId === item.id}
                        onClick={() => setReplacementSourceId(item.id)}
                        className="inline-flex min-h-7 shrink-0 items-center gap-1 px-1.5 text-[10px] text-[#d5ff67] hover:bg-white/5"
                      >
                        <ArrowLeftRight className="h-3 w-3" />
                        替换
                      </button>
                    </div>
                  ))}
                </div>
              </section>
            )}
            {replacementSource && (
              <div className="mb-3 flex min-w-0 items-center justify-between gap-2 border border-[#d5ff67]/35 bg-[#20291f] px-3 py-2 text-[11px]">
                <p className="min-w-0 truncate text-[#cbd3cb]">
                  选择目录商品替换“{replacementSource.name}”
                </p>
                <button
                  type="button"
                  title="取消替换"
                  aria-label="取消替换"
                  onClick={() => setReplacementSourceId(null)}
                  className="flex h-7 w-7 shrink-0 items-center justify-center text-[#8f9a90] hover:text-white"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            )}
            <label className="flex items-center gap-2 border-b border-white/15 pb-2 text-[#89948a]">
              <Search className="h-4 w-4" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索名称、类型或材料"
                className="min-w-0 flex-1 bg-transparent py-1 text-xs text-white outline-none placeholder:text-[#657067]"
              />
            </label>
            <div className="mt-3 divide-y divide-white/10">
              {catalogLoading && <p className="py-5 text-xs text-[#7f8b81]">正在同步商品库…</p>}
              {!catalogLoading && filteredCatalog.length === 0 && <p className="py-5 text-xs text-[#7f8b81]">没有匹配商品</p>}
              {filteredCatalog.map((item) => {
                const selected = project.selectedFurnitureIds.includes(item.id);
                const choosingReplacement = replacementSource !== null;
                const replacementDisabled = choosingReplacement && selected;
                return (
                  <div key={item.id} className="grid grid-cols-[44px_1fr_32px] items-center gap-3 py-3">
                    <div className={`h-11 overflow-hidden ${item.gradient}`}>
                      {item.imageUrl && <img src={item.imageUrl} alt="" className="h-full w-full object-cover" />}
                    </div>
                    <div className="min-w-0">
                      <p className="truncate text-xs font-medium">{item.name}</p>
                      <div className="mt-1 flex min-w-0 items-center gap-1.5">
                        <span className="truncate font-mono text-[9px] text-[#7f8b81]">{item.priceRange}</span>
                        <span className="shrink-0 border border-white/10 px-1 py-0.5 text-[8px] text-[#9ca69d]">{getFurnitureDataOriginLabel(item.dataOrigin)}</span>
                      </div>
                    </div>
                    <button
                      type="button"
                      disabled={replacementDisabled}
                      title={choosingReplacement
                        ? selected ? "已在当前方案中" : `替换为${item.name}`
                        : selected ? "从项目移除" : "加入当前项目"}
                      aria-label={choosingReplacement
                        ? selected ? `${item.name}已在当前方案中` : `用${item.name}替换${replacementSource.name}`
                        : selected ? `移除${item.name}` : `加入${item.name}`}
                      onClick={() => choosingReplacement
                        ? replaceWithCatalogItem(item)
                        : toggleCatalogItem(item)}
                      className={`flex h-8 w-8 items-center justify-center rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-35 ${selected ? "bg-[#d5ff67] text-[#111713]" : "border border-white/15 text-[#9ca69d] hover:border-[#d5ff67] hover:text-[#d5ff67]"}`}
                    >
                      {choosingReplacement && !selected
                        ? <ArrowLeftRight className="h-4 w-4" />
                        : selected ? <Check className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {tab === "budget" && (
          <div>
            <p className="font-mono text-[10px] tracking-[0.16em] text-[#7f8b81] uppercase">Live estimate</p>
            <div className="mt-5 border-y border-white/10 py-5">
              <p className="text-xs text-[#7f8b81]">当前家具小计</p>
              <p className="mt-2 font-mono text-3xl">¥{furnitureSubtotal.toLocaleString("zh-CN")}</p>
              <p className="mt-1 text-[10px] text-[#6f7a71]">按商品区间最低价暂估</p>
            </div>
            <dl className="mt-4 divide-y divide-white/10 text-xs">
              <div className="flex justify-between gap-4 py-3"><dt className="text-[#7f8b81]">需求预算</dt><dd>{project.requirement.budgetRange || "待确认"}</dd></div>
              <div className="flex justify-between gap-4 py-3"><dt className="text-[#7f8b81]">方案估算</dt><dd>{budget > 0 ? `¥${budget.toLocaleString("zh-CN")}` : "待生成"}</dd></div>
              <div className="flex justify-between gap-4 py-3"><dt className="text-[#7f8b81]">已选家具</dt><dd>{selectedItems.length} 件</dd></div>
            </dl>
          </div>
        )}
      </div>
    </aside>
  );
}
