import { Sparkles } from "lucide-react";
import { useRequirementStore } from "@/store/useRequirementStore";
import Tag from "@/components/common/Tag";

/** 需求摘要卡片：展示「AI 已理解的重点」 */
export default function RequirementSummary({ compact = false }: { compact?: boolean }) {
  const requirement = useRequirementStore((s) => s.requirement);

  const lifestyle: string[] = [];
  if (requirement.hasElderly) lifestyle.push("有老人");
  if (requirement.hasChildren) lifestyle.push("有儿童");
  if (requirement.hasPets) lifestyle.push("有宠物");
  if (requirement.workFromHome) lifestyle.push("居家办公");
  if (requirement.cookingOften) lifestyle.push("经常做饭");
  if (requirement.needStorage) lifestyle.push("大量收纳");
  if (requirement.ecoFriendly) lifestyle.push("环保材料");
  if (requirement.smartHome) lifestyle.push("智能家居");

  const groups: { label: string; items: string[] }[] = [
    { label: "空间", items: requirement.rooms },
    {
      label: "基础信息",
      items: [
        requirement.area ? `${requirement.area}㎡` : "",
        requirement.houseType,
        requirement.city,
        requirement.renovationType,
        requirement.budgetRange ? `预算 ${requirement.budgetRange}` : "",
      ].filter(Boolean),
    },
    {
      label: "生活方式",
      items: [`常住 ${requirement.familySize} 人`, ...lifestyle],
    },
    { label: "喜欢的风格", items: requirement.styles },
    { label: "主色调", items: requirement.colors },
    { label: "偏好材质", items: requirement.materials },
  ].filter((g) => g.items.length > 0);

  const isEmpty = groups.every((g) => g.items.length === 0);

  return (
    <div
      className={`rounded-3xl border border-cream-200 bg-white/80 ${compact ? "p-4" : "p-5"}`}
    >
      <div className="flex items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-sage-600 text-white">
          <Sparkles className="h-4 w-4" />
        </span>
        <h3 className="text-sm font-semibold text-stone-700">AI 已理解的重点</h3>
      </div>
      {isEmpty ? (
        <p className="mt-4 text-sm leading-relaxed text-stone-400">
          随着你的填写，这里会实时整理出 AI 理解的需求要点。
        </p>
      ) : (
        <div className="mt-4 space-y-3.5">
          {groups.map((group) => (
            <div key={group.label}>
              <div className="text-xs text-stone-400">{group.label}</div>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {group.items.map((item) => (
                  <Tag key={item} tone="sage">
                    {item}
                  </Tag>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
      {requirement.extraNotes && (
        <p className="mt-4 rounded-xl bg-cream-100 px-3 py-2 text-xs leading-relaxed text-stone-500">
          “{requirement.extraNotes}”
        </p>
      )}
    </div>
  );
}
