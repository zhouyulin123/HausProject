import { Check } from "lucide-react";

/** 通用标签多选组件：风格 / 材质 / 颜色等 */
export default function PreferenceTags({
  options,
  selected,
  onToggle,
  colorMap,
}: {
  options: string[];
  selected: string[];
  onToggle: (value: string) => void;
  /** 传入色值时在标签前展示色块（用于主色调选择） */
  colorMap?: Record<string, string>;
}) {
  return (
    <div className="flex flex-wrap gap-2.5">
      {options.map((option) => {
        const active = selected.includes(option);
        return (
          <button
            key={option}
            type="button"
            onClick={() => onToggle(option)}
            className={`inline-flex items-center gap-1.5 rounded-full border px-4 py-2 text-sm font-medium transition-all duration-200 ${
              active
                ? "border-sage-500 bg-sage-600 text-white shadow-card"
                : "border-cream-300 bg-white/70 text-stone-600 hover:border-sage-400 hover:text-sage-700"
            }`}
          >
            {colorMap?.[option] && (
              <span
                className="h-3.5 w-3.5 rounded-full border border-white/60 shadow-sm"
                style={{ backgroundColor: colorMap[option] }}
              />
            )}
            {option}
            {active && <Check className="h-3.5 w-3.5" strokeWidth={3} />}
          </button>
        );
      })}
    </div>
  );
}
