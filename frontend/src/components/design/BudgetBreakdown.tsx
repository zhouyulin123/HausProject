import { motion } from "framer-motion";
import type { BudgetItem } from "@/types/design";

const barColors = ["bg-sage-500", "bg-wood-400", "bg-terra-400", "bg-sage-300", "bg-cream-300"];

export default function BudgetBreakdown({
  items,
  total,
}: {
  items: BudgetItem[];
  total: number;
}) {
  return (
    <div className="rounded-3xl border border-cream-200 bg-white/80 p-6">
      <div className="flex items-baseline justify-between">
        <h3 className="text-base font-semibold text-stone-800">预算拆分</h3>
        <span className="font-display text-xl font-semibold text-terra-600">
          ¥{total.toLocaleString()}
        </span>
      </div>
      <div className="mt-5 space-y-4">
        {items.map((item, i) => (
          <div key={item.name}>
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium text-stone-600">{item.name}</span>
              <span className="text-stone-400">
                {item.percent}% ·{" "}
                <span className="font-medium text-stone-600">
                  ¥{item.amount.toLocaleString()}
                </span>
              </span>
            </div>
            <div className="mt-1.5 h-2.5 overflow-hidden rounded-full bg-cream-100">
              <motion.div
                className={`h-full rounded-full ${barColors[i % barColors.length]}`}
                initial={{ width: 0 }}
                whileInView={{ width: `${item.percent}%` }}
                viewport={{ once: true }}
                transition={{ duration: 0.7, delay: i * 0.08, ease: "easeOut" }}
              />
            </div>
          </div>
        ))}
      </div>
      <p className="mt-5 text-xs leading-relaxed text-stone-400">
        以上为 AI 预估价格，实际价格需根据现场测量、材料品牌与五金配置确认。
      </p>
    </div>
  );
}
