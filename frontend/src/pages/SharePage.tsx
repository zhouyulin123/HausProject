import { useEffect, useState } from "react";
import { CalendarClock, CircleAlert, Lightbulb, PackageCheck } from "lucide-react";
import { useParams } from "react-router-dom";

import {
  fetchPublicPlanShare,
  PublicShareUnavailableError,
} from "@/api/shareApi";
import type { PublicPlanShare } from "@/api/shareApi";


function money(value: number | null | undefined): string {
  return value == null ? "待确认" : `¥${value.toLocaleString("zh-CN")}`;
}

export default function SharePage() {
  const { token = "" } = useParams();
  const [share, setShare] = useState<PublicPlanShare | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "unavailable" | "error">(
    "loading",
  );

  useEffect(() => {
    let active = true;
    setState("loading");
    fetchPublicPlanShare(token)
      .then((result) => {
        if (!active) return;
        setShare(result);
        setState("ready");
      })
      .catch((error) => {
        if (!active) return;
        setState(
          error instanceof PublicShareUnavailableError ? "unavailable" : "error",
        );
      });
    return () => {
      active = false;
    };
  }, [token]);

  if (state !== "ready" || !share) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#f1f0ea] px-6 text-center text-[#1c241e]">
        <div className="max-w-md">
          {state === "loading" ? (
            <div className="mx-auto h-8 w-8 animate-spin rounded-full border-2 border-[#abb1a8] border-t-[#243129]" />
          ) : (
            <CircleAlert className="mx-auto h-9 w-9 text-[#9b5843]" />
          )}
          <h1 className="mt-5 font-display text-2xl">
            {state === "loading"
              ? "正在读取方案"
              : state === "unavailable"
                ? "分享链接不可用"
                : "暂时无法读取方案"}
          </h1>
          {state !== "loading" && (
            <p className="mt-3 text-sm leading-6 text-[#687168]">
              {state === "unavailable"
                ? "链接可能已过期或由方案所有者撤销。"
                : "请稍后刷新页面。"}
            </p>
          )}
        </div>
      </main>
    );
  }

  const { plan } = share;
  return (
    <main className="min-h-screen bg-[#f1f0ea] text-[#1c241e]">
      <header className="border-b border-[#1c241e]/10 bg-[#162019] px-5 py-5 text-[#eff1e9] sm:px-8">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4">
          <p className="font-display text-lg">HAUS AI 家装方案</p>
          <p className="flex items-center gap-2 text-xs text-[#aeb8ae]">
            <CalendarClock className="h-4 w-4" />
            有效至 {new Date(share.expires_at).toLocaleDateString("zh-CN")}
          </p>
        </div>
      </header>

      <section className="border-b border-[#1c241e]/10 px-5 py-12 sm:px-8 sm:py-16">
        <div className="mx-auto max-w-6xl">
          <p className="text-xs font-medium text-[#758078]">{plan.style || "家装设计方案"}</p>
          <h1 className="mt-4 max-w-4xl font-display text-4xl leading-tight sm:text-6xl">
            {plan.name}
          </h1>
          {plan.delivery_mode === "development_preview" && (
            <p role="note" className="mt-5 rounded border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
              开发版预览：商品价格、库存和交期包含模拟数据，不作为商业报价或下单依据。
            </p>
          )}
          {plan.description && (
            <p className="mt-6 max-w-3xl text-base leading-8 text-[#626b63]">
              {plan.description}
            </p>
          )}
          <div className="mt-8 flex flex-wrap items-end gap-x-10 gap-y-4">
            <div>
              <p className="text-xs text-[#758078]">方案预算</p>
              <p className="mt-1 font-mono text-2xl">{money(plan.quote?.total ?? plan.budget)}</p>
            </div>
          </div>
          {plan.tags.length > 0 && (
            <div className="mt-7 flex flex-wrap gap-2">
              {plan.tags.map((tag) => (
                <span key={tag} className="border border-[#26352b]/20 px-3 py-1 text-xs">
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>
      </section>

      {plan.furniture.length > 0 && (
        <section className="border-b border-[#1c241e]/10 px-5 py-12 sm:px-8">
          <div className="mx-auto max-w-6xl">
            <div className="flex items-center gap-3">
              <PackageCheck className="h-5 w-5 text-[#647066]" />
              <h2 className="font-display text-2xl">家具清单</h2>
            </div>
            <div className="mt-7 grid gap-px bg-[#1c241e]/10 sm:grid-cols-2 lg:grid-cols-3">
              {plan.furniture.map((item, index) => (
                <article key={`${item.sku || item.name}-${index}`} className="bg-[#f1f0ea] p-5">
                  <div className="flex items-start justify-between gap-4">
                    <h3 className="font-medium">{item.name}</h3>
                    {item.sku && <span className="font-mono text-[10px] text-[#758078]">{item.sku}</span>}
                  </div>
                  <p className="mt-3 text-sm text-[#687168]">
                    {[item.room, item.material, item.size].filter(Boolean).join(" · ")}
                  </p>
                  {item.reason && <p className="mt-3 text-sm leading-6 text-[#4f5851]">{item.reason}</p>}
                  <p className="mt-4 font-mono text-sm">{money(item.subtotal ?? item.unit_price)}</p>
                </article>
              ))}
            </div>
          </div>
        </section>
      )}

      <section className="border-b border-[#1c241e]/10 px-5 py-12 sm:px-8">
        <div className="mx-auto grid max-w-6xl gap-10 lg:grid-cols-2">
          <div>
            <h2 className="font-display text-2xl">色彩与材质</h2>
            <div className="mt-6 flex min-h-24 overflow-hidden border border-[#1c241e]/10">
              {plan.colors.length > 0 ? plan.colors.map((color) => (
                <div key={`${color.name}-${color.hex}`} className="flex min-w-20 flex-1 items-end p-3" style={{ backgroundColor: color.hex }}>
                  <span className="bg-white/85 px-2 py-1 text-[10px] text-[#303832]">{color.name}</span>
                </div>
              )) : <p className="p-5 text-sm text-[#758078]">暂无色彩快照</p>}
            </div>
            <div className="mt-5 space-y-3">
              {plan.materials.map((material) => (
                <div key={material.name} className="border-t border-[#1c241e]/10 pt-3">
                  <p className="font-medium">{material.name}</p>
                  {material.description && <p className="mt-1 text-sm text-[#687168]">{material.description}</p>}
                </div>
              ))}
            </div>
          </div>
          <div>
            <h2 className="font-display text-2xl">布局建议</h2>
            <ol className="mt-6 space-y-4">
              {plan.layout_suggestions.map((suggestion, index) => (
                <li key={suggestion} className="flex gap-4 border-t border-[#1c241e]/10 pt-4 text-sm leading-6">
                  <span className="font-mono text-[#758078]">{String(index + 1).padStart(2, "0")}</span>
                  <span>{suggestion}</span>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </section>

      {plan.ai_tips.length > 0 && (
        <section className="px-5 py-12 sm:px-8">
          <div className="mx-auto max-w-6xl">
            <div className="flex items-center gap-3">
              <Lightbulb className="h-5 w-5 text-[#8d6846]" />
              <h2 className="font-display text-2xl">设计提示</h2>
            </div>
            <div className="mt-6 grid gap-4 sm:grid-cols-2">
              {plan.ai_tips.map((tip) => (
                <p key={tip} className="border-l-2 border-[#8d6846] pl-4 text-sm leading-7 text-[#586159]">
                  {tip}
                </p>
              ))}
            </div>
          </div>
        </section>
      )}
    </main>
  );
}
