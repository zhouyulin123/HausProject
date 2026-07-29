export interface FurnitureFilters {
  room: string;
  category: string;
  style: string;
  price: string;
  material: string;
}

export const defaultFilters: FurnitureFilters = {
  room: "全部",
  category: "全部",
  style: "全部",
  price: "全部",
  material: "全部",
};

function FilterRow({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: string[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
      <span className="w-14 shrink-0 pt-1.5 text-xs font-semibold text-stone-400">
        {label}
      </span>
      <div className="flex flex-wrap gap-1.5">
        {options.map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => onChange(option)}
            className={`rounded-full px-3 py-1.5 text-xs font-medium transition-all ${
              value === option
                ? "bg-sage-600 text-white"
                : "bg-cream-100 text-stone-500 hover:bg-cream-200 hover:text-stone-700"
            }`}
          >
            {option}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function FurnitureFilter({
  filters,
  onChange,
  optionGroups,
}: {
  filters: FurnitureFilters;
  onChange: (patch: Partial<FurnitureFilters>) => void;
  optionGroups: {
    rooms: string[];
    categories: string[];
    styles: string[];
    prices: string[];
    materials: string[];
  };
}) {
  return (
    <div className="space-y-3.5 rounded-3xl border border-cream-200 bg-white/80 p-5">
      <FilterRow
        label="空间"
        options={optionGroups.rooms}
        value={filters.room}
        onChange={(v) => onChange({ room: v })}
      />
      <FilterRow
        label="类型"
        options={optionGroups.categories}
        value={filters.category}
        onChange={(v) => onChange({ category: v })}
      />
      <FilterRow
        label="风格"
        options={optionGroups.styles}
        value={filters.style}
        onChange={(v) => onChange({ style: v })}
      />
      <FilterRow
        label="价格"
        options={optionGroups.prices}
        value={filters.price}
        onChange={(v) => onChange({ price: v })}
      />
      <FilterRow
        label="材质"
        options={optionGroups.materials}
        value={filters.material}
        onChange={(v) => onChange({ material: v })}
      />
    </div>
  );
}
