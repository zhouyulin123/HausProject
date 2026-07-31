import { lazy, Suspense, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { motion } from "framer-motion";
import {
  ArrowLeft,
  BookmarkCheck,
  BookmarkPlus,
  Check,
  Download,
  Lightbulb,
  MessageCircleMore,
  Sparkles,
} from "lucide-react";
import { mockDesigns } from "@/data/mockDesigns";
import { exportProposalPdf } from "@/api/designApi";
import { useDesignStore } from "@/store/useDesignStore";
import { useRequirementStore } from "@/store/useRequirementStore";
import BudgetBreakdown from "@/components/design/BudgetBreakdown";
import ColorPalette from "@/components/design/ColorPalette";
import MaterialBoard from "@/components/design/MaterialBoard";
import EffectImage from "@/components/design/EffectImage";
import ShopQuoteCard from "@/components/design/ShopQuoteCard";
import EmptyState from "@/components/common/EmptyState";
import Button from "@/components/common/Button";
import Tag from "@/components/common/Tag";

const tabs = ["总览", "3D 布局", "布局", "家具", "色彩材质", "预算", "AI 建议"] as const;
type Tab = (typeof tabs)[number];

const RoomView3D = lazy(
  () => import("@/components/design/RoomView3D"),
);

function SceneEditorFallback() {
  return (
    <div className="flex min-h-[620px] items-center justify-center overflow-hidden rounded-[28px] border border-cream-200 bg-gradient-to-br from-[#e9e1d3] via-[#dcd3c3] to-[#c9bca8]">
      <div className="text-center">
        <div className="mx-auto h-10 w-10 animate-spin rounded-full border-2 border-white/60 border-t-sage-700" />
        <p className="mt-4 text-sm font-medium text-stone-600">
          正在加载 3D 空间编辑器
        </p>
        <p className="mt-1 text-xs text-stone-500">
          只在需要时载入三维引擎
        </p>
      </div>
    </div>
  );
}

export default function DesignDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { generatedPlans, savedDesigns, saveDesign, updateDesignStatus } =
    useDesignStore();
  const rooms = useRequirementStore((s) => s.requirement.rooms);
  const [tab, setTab] = useState<Tab>("总览");
  const [exportState, setExportState] = useState<"idle" | "doing" | "done" | "fail">(
    "idle",
  );

  const plan = useMemo(
    () =>
      generatedPlans.find((p) => p.id === id) ??
      mockDesigns.find((p) => p.id === id),
    [generatedPlans, id],
  );

  // 3D 视图聚焦的主空间：优先用户所选（跳过"全屋"），否则看方案家具都属于哪个空间
  const primaryRoom = useMemo(() => {
    const chosen = rooms.find((r) => r !== "全屋");
    if (chosen) return chosen;
    return (plan?.furnitureSuggestions ?? []).find((f) => f.room)?.room ?? "客厅";
  }, [rooms, plan]);

  if (!plan) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-16">
        <EmptyState
          title="没有找到这套方案"
          description="它可能已被删除，或者链接有误。"
          action={
            <Link to="/results">
              <Button>返回方案列表</Button>
            </Link>
          }
        />
      </div>
    );
  }

  const saved = savedDesigns.find((d) => d.planId === plan.id);

  const handleExport = async () => {
    if (exportState === "doing") return;
    setExportState("doing");
    try {
      const pdfUrl = await exportProposalPdf(plan);
      if (!saved) saveDesign(plan, rooms);
      const target = useDesignStore
        .getState()
        .savedDesigns.find((d) => d.planId === plan.id);
      if (target) updateDesignStatus(target.id, "已导出");
      setExportState("done");
      window.open(pdfUrl, "_blank");
      setTimeout(() => setExportState("idle"), 3000);
    } catch (error) {
      console.warn("[DesignDetail] 提案导出失败", error);
      setExportState("fail");
      setTimeout(() => setExportState("idle"), 3000);
    }
  };

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
      <button
        type="button"
        onClick={() => navigate(-1)}
        className="inline-flex items-center gap-1.5 text-sm text-stone-500 transition-colors hover:text-sage-700"
      >
        <ArrowLeft className="h-4 w-4" />
        返回
      </button>

      {/* 顶部信息区 */}
      <div className="mt-4 flex flex-col gap-5 rounded-3xl border border-cream-200 bg-white/80 p-6 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold sm:text-3xl">{plan.name}</h1>
            <Tag tone="sage">
              <Sparkles className="h-3 w-3" />
              AI 推荐指数 {plan.score}%
            </Tag>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="font-display text-xl font-semibold text-terra-600">
              预算约 ¥{plan.budget.toLocaleString()}
            </span>
            <span className="text-stone-300">|</span>
            {plan.tags.map((t) => (
              <Tag key={t} tone="wood">
                {t}
              </Tag>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant={saved ? "secondary" : "outline"}
            onClick={() => saveDesign(plan, rooms)}
          >
            {saved ? (
              <BookmarkCheck className="h-4 w-4 text-sage-600" />
            ) : (
              <BookmarkPlus className="h-4 w-4" />
            )}
            {saved ? "已保存" : "保存方案"}
          </Button>
          <Button
            variant="outline"
            onClick={() => void handleExport()}
            disabled={exportState === "doing"}
          >
            {exportState === "done" ? (
              <Check className="h-4 w-4 text-sage-600" />
            ) : (
              <Download className="h-4 w-4" />
            )}
            {exportState === "doing"
              ? "正在生成提案..."
              : exportState === "done"
                ? "已导出，正在打开"
                : exportState === "fail"
                  ? "导出失败，点击重试"
                  : "导出提案 PDF"}
          </Button>
          <Button onClick={() => navigate("/chat")}>
            <MessageCircleMore className="h-4 w-4" />
            继续和 AI 优化
          </Button>
        </div>
      </div>

      {/* Tab 导航 */}
      <div className="thin-scrollbar mt-6 flex gap-2 overflow-x-auto pb-1">
        {tabs.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`shrink-0 rounded-full px-4 py-2 text-sm font-medium transition-all ${
              tab === t
                ? "bg-sage-600 text-white shadow-card"
                : "border border-cream-300 bg-white/70 text-stone-600 hover:border-sage-400"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {/* 不用 AnimatePresence：StrictMode 下 mode="wait" 的 exit 回调会失灵导致内容卡死；
          key 重挂载 + 进入动画已足够 */}
      <motion.div
          key={tab}
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25 }}
          className="mt-6 space-y-6"
        >
          {tab === "总览" && (
            <>
              {/* 视觉预览区 */}
              <div className="grid gap-4 sm:grid-cols-2">
                <EffectImage plan={plan} />
                <div className="grid grid-rows-2 gap-4">
                  <div className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-cream-100 to-cream-300">
                    <div className="absolute inset-6 rounded-xl border-2 border-dashed border-wood-400/50" />
                    <div className="absolute top-10 left-10 h-10 w-14 rounded-md border-2 border-wood-400/50" />
                    <div className="absolute right-10 bottom-8 h-8 w-16 rounded-md border-2 border-wood-400/50" />
                    <span className="absolute bottom-3 left-5 rounded-full bg-white/85 px-3 py-1 text-xs font-medium text-stone-600">
                      平面布局图占位
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="relative overflow-hidden rounded-3xl">
                      <div className="grid h-full grid-cols-2">
                        {plan.materials.slice(0, 4).map((m) => (
                          <div key={m.name} className={m.gradient} />
                        ))}
                      </div>
                      <span className="absolute bottom-2.5 left-3.5 rounded-full bg-white/85 px-2.5 py-0.5 text-[11px] font-medium text-stone-600">
                        材质搭配板
                      </span>
                    </div>
                    <div className="relative overflow-hidden rounded-3xl">
                      <div className="flex h-full">
                        {plan.colorPalette.map((c) => (
                          <div
                            key={c.name}
                            className="flex-1"
                            style={{ backgroundColor: c.hex }}
                          />
                        ))}
                      </div>
                      <span className="absolute bottom-2.5 left-3.5 rounded-full bg-white/85 px-2.5 py-0.5 text-[11px] font-medium text-stone-600">
                        色彩搭配板
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              <div className="rounded-3xl border border-cream-200 bg-white/80 p-6">
                <h3 className="text-base font-semibold text-stone-800">风格定位</h3>
                <p className="mt-3 leading-relaxed text-stone-600">{plan.description}</p>
                <p className="mt-3 text-sm text-stone-400">
                  适合：{plan.suitableFor.join(" / ")}
                </p>
              </div>
            </>
          )}

          {tab === "3D 布局" && (
            <div>
              <Suspense fallback={<SceneEditorFallback />}>
                <RoomView3D plan={plan} roomType={primaryRoom} />
              </Suspense>
              <p className="mt-3 px-1 text-xs leading-relaxed text-stone-400">
                点击家具后可拖动、旋转或使用方向按钮微调；正式方案会自动保存场景版本。
                当前家具仍以准确尺寸体块表示，后续将逐步替换为商品 GLB 模型。
              </p>
            </div>
          )}

          {tab === "布局" && (
            <div className="rounded-3xl border border-cream-200 bg-white/80 p-6">
              <h3 className="text-base font-semibold text-stone-800">空间布局建议</h3>
              <ul className="mt-4 space-y-3.5">
                {plan.layoutSuggestions.map((item, i) => (
                  <li key={item} className="flex items-start gap-3">
                    <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-sage-100 text-xs font-bold text-sage-700">
                      {i + 1}
                    </span>
                    <span className="text-sm leading-relaxed text-stone-600">{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {tab === "家具" && (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {plan.furnitureSuggestions.map((item) => (
                <div
                  key={item.id}
                  className="overflow-hidden rounded-3xl border border-cream-200 bg-white/80 transition-all hover:-translate-y-1 hover:shadow-soft"
                >
                  <div className={`relative h-28 overflow-hidden ${item.gradient}`}>
                    {item.imageUrl && (
                      <img
                        src={item.imageUrl}
                        alt={item.name}
                        className="absolute inset-0 h-full w-full object-cover"
                      />
                    )}
                    {item.sku && (
                      <span className="absolute top-2.5 left-3 rounded-full bg-white/85 px-2 py-0.5 text-[10px] font-semibold text-stone-500">
                        {item.sku}
                      </span>
                    )}
                  </div>
                  <div className="p-4">
                    <div className="flex items-center justify-between gap-2">
                      <h4 className="text-sm font-semibold text-stone-800">{item.name}</h4>
                      <Tag tone="sage">{item.matchScore}%</Tag>
                    </div>
                    <p className="mt-2 text-xs leading-relaxed text-stone-500">
                      {item.reason}
                    </p>
                    <div className="mt-3 space-y-1 text-xs text-stone-400">
                      <p>价格区间：<span className="font-medium text-terra-600">{item.priceRange}</span></p>
                      <p>材质：{item.material}</p>
                      <p>尺寸建议：{item.sizeSuggestion}</p>
                      <p>替代选择：{item.alternative}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {tab === "色彩材质" && (
            <>
              <ColorPalette colors={plan.colorPalette} />
              <MaterialBoard materials={plan.materials} />
              <div className="rounded-3xl border border-cream-200 bg-white/80 p-6">
                <h3 className="text-base font-semibold text-stone-800">灯光建议</h3>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  {plan.lightingSuggestions.map((light) => (
                    <div
                      key={light.name}
                      className="rounded-2xl bg-cream-100/70 px-4 py-3.5"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-semibold text-stone-700">
                          {light.name}
                        </span>
                        <Tag tone="terra">{light.purpose}</Tag>
                      </div>
                      <p className="mt-1.5 text-xs leading-relaxed text-stone-500">
                        {light.description}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}

          {tab === "预算" && (
            <>
              <ShopQuoteCard plan={plan} />
              <BudgetBreakdown items={plan.budgetBreakdown} total={plan.budget} />
            </>
          )}

          {tab === "AI 建议" && (
            <div className="space-y-4">
              {plan.aiTips.map((tip, i) => (
                <motion.div
                  key={tip}
                  initial={{ opacity: 0, x: -16 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.1 }}
                  className="flex items-start gap-3 rounded-3xl border border-cream-200 bg-white/80 p-5"
                >
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-terra-100 text-terra-600">
                    <Lightbulb className="h-4.5 w-4.5" />
                  </span>
                  <p className="text-sm leading-relaxed text-stone-600">{tip}</p>
                </motion.div>
              ))}
              <div className="pt-2 text-center">
                <Button size="lg" onClick={() => navigate("/chat")}>
                  <MessageCircleMore className="h-4 w-4" />
                  和 AI 聊聊这些建议
                </Button>
              </div>
            </div>
          )}
        </motion.div>
    </div>
  );
}
