import { Store } from "lucide-react";
import type { DesignPlan } from "@/types/design";

const fmt = (n: number) => `¥${n.toLocaleString()}`;

/** 本店产品报价单：成品家具按件 + 定制项目按面积/延米实算（价格来自商品库） */
export default function ShopQuoteCard({ plan }: { plan: DesignPlan }) {
  const quote = plan.shopQuote;
  if (!quote) return null;

  const furniture = plan.furnitureSuggestions.filter(
    (f) => typeof f.subtotal === "number",
  );
  const customs = plan.customItems ?? [];

  return (
    <div className="rounded-3xl border border-cream-200 bg-white/80 p-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-terra-100 text-terra-600">
            <Store className="h-4 w-4" />
          </span>
          <h3 className="text-base font-semibold text-stone-800">本店产品报价单</h3>
        </div>
        <span className="font-display text-xl font-semibold text-terra-600">
          {fmt(quote.total)}
        </span>
      </div>

      <div className="thin-scrollbar mt-5 overflow-x-auto">
        <table className="w-full min-w-[520px] text-sm">
          <thead>
            <tr className="border-b border-cream-200 text-left text-xs text-stone-400">
              <th className="pb-2 font-medium">项目</th>
              <th className="pb-2 font-medium">规格</th>
              <th className="pb-2 text-right font-medium">单价</th>
              <th className="pb-2 text-right font-medium">数量</th>
              <th className="pb-2 text-right font-medium">小计</th>
            </tr>
          </thead>
          <tbody className="text-stone-600">
            {furniture.map((f) => (
              <tr key={f.sku ?? f.id} className="border-b border-cream-100">
                <td className="py-2.5 font-medium text-stone-700">{f.name}</td>
                <td className="py-2.5 text-xs text-stone-400">
                  {f.sku} · {f.material}
                </td>
                <td className="py-2.5 text-right">{fmt(f.unitPrice ?? 0)}</td>
                <td className="py-2.5 text-right">x{f.quantity ?? 1}</td>
                <td className="py-2.5 text-right font-medium">{fmt(f.subtotal ?? 0)}</td>
              </tr>
            ))}
            {customs.map((c, i) => (
              <tr key={`${c.project}-${i}`} className="border-b border-cream-100">
                <td className="py-2.5 font-medium text-stone-700">{c.project}</td>
                <td className="py-2.5 text-xs text-stone-400">
                  {c.grade ?? "标准"} · {c.note}
                </td>
                <td className="py-2.5 text-right">
                  {fmt(c.unitPrice)}/{c.unit}
                </td>
                <td className="py-2.5 text-right">
                  {c.quantity} {c.unit}
                </td>
                <td className="py-2.5 text-right font-medium">{fmt(c.subtotal)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-end gap-x-6 gap-y-1 text-sm">
        <span className="text-stone-500">
          成品家具 <span className="font-medium text-stone-700">{fmt(quote.furnitureTotal)}</span>
        </span>
        <span className="text-stone-500">
          定制项目 <span className="font-medium text-stone-700">{fmt(quote.customTotal)}</span>
        </span>
        <span className="text-stone-700">
          合计 <span className="font-display text-lg font-semibold text-terra-600">{fmt(quote.total)}</span>
        </span>
      </div>
      <p className="mt-3 text-xs leading-relaxed text-stone-400">
        以上为本店产品预估报价（价格来自商品库与定制价目表），定制项目工程量以现场测量为准。
      </p>
    </div>
  );
}
