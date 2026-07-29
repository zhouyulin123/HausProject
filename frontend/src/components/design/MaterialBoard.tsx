import type { MaterialItem } from "@/types/design";

export default function MaterialBoard({ materials }: { materials: MaterialItem[] }) {
  return (
    <div className="rounded-3xl border border-cream-200 bg-white/80 p-6">
      <h3 className="text-base font-semibold text-stone-800">材质建议</h3>
      <div className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {materials.map((material) => (
          <div key={material.name}>
            <div className={`h-20 rounded-2xl ${material.gradient} shadow-sm`} />
            <p className="mt-2 text-sm font-semibold text-stone-700">{material.name}</p>
            <p className="mt-0.5 text-xs leading-relaxed text-stone-400">
              {material.description}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
