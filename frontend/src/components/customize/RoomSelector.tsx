import {
  Home,
  Sofa,
  BedDouble,
  CookingPot,
  Utensils,
  Bath,
  Baby,
  BookOpen,
  Sun,
  Shirt,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Check } from "lucide-react";

interface RoomOption {
  name: string;
  icon: LucideIcon;
  description: string;
}

export const roomOptions: RoomOption[] = [
  { name: "全屋", icon: Home, description: "整体规划，风格统一" },
  { name: "客厅", icon: Sofa, description: "会客与家庭活动中心" },
  { name: "卧室", icon: BedDouble, description: "睡眠与放松的私享空间" },
  { name: "厨房", icon: CookingPot, description: "烹饪动线与收纳" },
  { name: "餐厅", icon: Utensils, description: "用餐氛围与餐边收纳" },
  { name: "卫生间", icon: Bath, description: "干湿分离与适老细节" },
  { name: "儿童房", icon: Baby, description: "安全环保与成长陪伴" },
  { name: "书房", icon: BookOpen, description: "办公学习的专注角落" },
  { name: "阳台", icon: Sun, description: "洗晒、绿植或休闲区" },
  { name: "衣帽间", icon: Shirt, description: "衣物收纳与展示" },
];

export default function RoomSelector({
  selected,
  onToggle,
}: {
  selected: string[];
  onToggle: (room: string) => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5 sm:gap-4">
      {roomOptions.map((room) => {
        const active = selected.includes(room.name);
        return (
          <button
            key={room.name}
            type="button"
            onClick={() => onToggle(room.name)}
            className={`group relative flex flex-col items-start gap-2 rounded-2xl border p-4 text-left transition-all duration-200 ${
              active
                ? "border-sage-500 bg-sage-50 shadow-card"
                : "border-cream-200 bg-white/70 hover:border-sage-300 hover:bg-white"
            }`}
          >
            {active && (
              <span className="absolute top-2.5 right-2.5 flex h-5 w-5 items-center justify-center rounded-full bg-sage-600 text-white">
                <Check className="h-3 w-3" strokeWidth={3} />
              </span>
            )}
            <room.icon
              className={`h-6 w-6 ${active ? "text-sage-600" : "text-stone-400 group-hover:text-sage-500"}`}
              strokeWidth={1.6}
            />
            <span className="text-sm font-semibold text-stone-700">{room.name}</span>
            <span className="text-xs leading-snug text-stone-400">
              {room.description}
            </span>
          </button>
        );
      })}
    </div>
  );
}
