import type { ColorItem } from "@/types/design";

export default function ColorPalette({ colors }: { colors: ColorItem[] }) {
  return (
    <div className="rounded-3xl border border-cream-200 bg-white/80 p-6">
      <h3 className="text-base font-semibold text-stone-800">色彩搭配</h3>
      <div className="mt-5 grid grid-cols-5 gap-3">
        {colors.map((color) => (
          <div key={color.name} className="text-center">
            <div
              className="mx-auto h-14 w-full rounded-2xl border border-stone-200/60 shadow-sm sm:h-16"
              style={{ backgroundColor: color.hex }}
            />
            <p className="mt-2 text-xs font-semibold text-stone-700">{color.name}</p>
            <p className="mt-0.5 text-[11px] text-stone-400">{color.usage}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
