import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft, ArrowRight, Check, Minus, Plus, Sparkles } from "lucide-react";
import { useRequirementStore } from "@/store/useRequirementStore";
import RoomSelector from "./RoomSelector";
import PreferenceTags from "./PreferenceTags";
import Button from "@/components/common/Button";

const steps = ["选择空间", "房屋信息", "生活方式", "风格偏好"];

const houseTypes = ["一居室", "两居室", "三居室", "四居室", "复式", "别墅"];
const renovationTypes = ["毛坯房", "精装改造", "旧房翻新", "局部改造"];
const budgetRanges = ["3 万以下", "3-8 万", "8-15 万", "15-30 万", "30 万以上"];

const styleOptions = [
  "现代简约",
  "奶油风",
  "原木风",
  "北欧风",
  "轻奢风",
  "中古风",
  "日式风",
  "法式风",
  "工业风",
  "混搭风",
];

const colorOptions: Record<string, string> = {
  奶油白: "#F5EFE3",
  浅木色: "#D2B48C",
  暖灰色: "#B8B0A4",
  鼠尾草绿: "#9CAF88",
  陶土橙: "#C87E5A",
  雾霾蓝: "#A6B8C3",
  藕粉色: "#DDB8AC",
  墨绿色: "#3F5548",
};

const materialOptions = ["原木", "皮革", "布艺", "大理石", "金属", "藤编", "微水泥"];

const lifestyleOptions: { key: LifestyleKey; label: string; hint: string }[] = [
  { key: "hasElderly", label: "有老人", hint: "适老化细节" },
  { key: "hasChildren", label: "有儿童", hint: "安全与环保" },
  { key: "hasPets", label: "有宠物", hint: "耐抓易清洁" },
  { key: "workFromHome", label: "经常在家办公", hint: "办公区规划" },
  { key: "cookingOften", label: "喜欢做饭", hint: "厨房动线优化" },
  { key: "needStorage", label: "需要大量收纳", hint: "收纳体系设计" },
  { key: "ecoFriendly", label: "重视环保材料", hint: "ENF 级板材" },
  { key: "smartHome", label: "需要智能家居", hint: "灯光窗帘联动" },
];

type LifestyleKey =
  | "hasElderly"
  | "hasChildren"
  | "hasPets"
  | "workFromHome"
  | "cookingOften"
  | "needStorage"
  | "ecoFriendly"
  | "smartHome";

function FieldLabel({ children }: { children: string }) {
  return <label className="mb-2.5 block text-sm font-semibold text-stone-700">{children}</label>;
}

/** 单选 pill 组 */
function PillGroup({
  options,
  value,
  onChange,
}: {
  options: string[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2.5">
      {options.map((option) => (
        <button
          key={option}
          type="button"
          onClick={() => onChange(value === option ? "" : option)}
          className={`rounded-full border px-4 py-2 text-sm font-medium transition-all ${
            value === option
              ? "border-sage-500 bg-sage-600 text-white shadow-card"
              : "border-cream-300 bg-white/70 text-stone-600 hover:border-sage-400 hover:text-sage-700"
          }`}
        >
          {option}
        </button>
      ))}
    </div>
  );
}

const inputClass =
  "w-full rounded-xl border border-cream-300 bg-white/80 px-4 py-2.5 text-sm text-stone-700 placeholder:text-stone-300 outline-none transition-colors focus:border-sage-500 focus:ring-2 focus:ring-sage-100";

export default function StepForm() {
  const [step, setStep] = useState(0);
  const [direction, setDirection] = useState(1);
  const navigate = useNavigate();
  const { requirement, update, toggleArrayItem } = useRequirementStore();

  const goto = (next: number) => {
    setDirection(next > step ? 1 : -1);
    setStep(next);
  };

  // 「全屋」与具体空间互斥
  const handleRoomToggle = (room: string) => {
    if (room === "全屋") {
      update({ rooms: requirement.rooms.includes("全屋") ? [] : ["全屋"] });
    } else {
      const withoutWhole = requirement.rooms.filter((r) => r !== "全屋");
      update({
        rooms: withoutWhole.includes(room)
          ? withoutWhole.filter((r) => r !== room)
          : [...withoutWhole, room],
      });
    }
  };

  const canNext = step !== 0 || requirement.rooms.length > 0;

  return (
    <div className="rounded-3xl border border-cream-200 bg-white/70 p-5 sm:p-8">
      {/* Stepper */}
      <div className="flex items-center gap-2 sm:gap-3">
        {steps.map((label, i) => (
          <div key={label} className="flex flex-1 items-center gap-2 sm:gap-3 last:flex-none">
            <button
              type="button"
              onClick={() => i < step && goto(i)}
              className={`flex items-center gap-2 ${i < step ? "cursor-pointer" : "cursor-default"}`}
            >
              <span
                className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold transition-colors ${
                  i < step
                    ? "bg-sage-600 text-white"
                    : i === step
                      ? "bg-terra-500 text-white shadow-card"
                      : "bg-cream-200 text-stone-400"
                }`}
              >
                {i < step ? <Check className="h-4 w-4" strokeWidth={3} /> : i + 1}
              </span>
              <span
                className={`hidden text-sm font-medium sm:block ${
                  i === step ? "text-stone-800" : "text-stone-400"
                }`}
              >
                {label}
              </span>
            </button>
            {i < steps.length - 1 && (
              <div
                className={`h-px flex-1 ${i < step ? "bg-sage-400" : "bg-cream-200"}`}
              />
            )}
          </div>
        ))}
      </div>
      <p className="mt-3 text-center text-sm font-medium text-stone-500 sm:hidden">
        第 {step + 1} 步 · {steps[step]}
      </p>

      {/* 步骤内容 */}
      <div className="relative mt-8 overflow-hidden">
        <AnimatePresence mode="wait" custom={direction}>
          <motion.div
            key={step}
            custom={direction}
            initial={{ opacity: 0, x: direction * 48 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: direction * -48 }}
            transition={{ duration: 0.3, ease: "easeOut" }}
          >
            {step === 0 && (
              <div>
                <h2 className="text-lg font-semibold">想改造哪些空间？</h2>
                <p className="mt-1 mb-6 text-sm text-stone-400">
                  可以多选，也可以直接选择「全屋」整体规划。
                </p>
                <RoomSelector selected={requirement.rooms} onToggle={handleRoomToggle} />
              </div>
            )}

            {step === 1 && (
              <div className="space-y-6">
                <div>
                  <h2 className="text-lg font-semibold">房屋基础信息</h2>
                  <p className="mt-1 text-sm text-stone-400">
                    这些信息决定了方案的布局和预算分配。
                  </p>
                </div>
                <div className="grid gap-5 sm:grid-cols-2">
                  <div>
                    <FieldLabel>房屋面积（㎡）</FieldLabel>
                    <input
                      type="number"
                      min={10}
                      placeholder="例如 98"
                      className={inputClass}
                      value={requirement.area ?? ""}
                      onChange={(e) =>
                        update({ area: e.target.value ? Number(e.target.value) : null })
                      }
                    />
                  </div>
                  <div>
                    <FieldLabel>所在城市</FieldLabel>
                    <input
                      type="text"
                      placeholder="例如 杭州"
                      className={inputClass}
                      value={requirement.city}
                      onChange={(e) => update({ city: e.target.value })}
                    />
                  </div>
                </div>
                <div>
                  <FieldLabel>户型</FieldLabel>
                  <PillGroup
                    options={houseTypes}
                    value={requirement.houseType}
                    onChange={(v) => update({ houseType: v })}
                  />
                </div>
                <div>
                  <FieldLabel>装修类型</FieldLabel>
                  <PillGroup
                    options={renovationTypes}
                    value={requirement.renovationType}
                    onChange={(v) => update({ renovationType: v })}
                  />
                </div>
                <div>
                  <FieldLabel>预算范围</FieldLabel>
                  <PillGroup
                    options={budgetRanges}
                    value={requirement.budgetRange}
                    onChange={(v) => update({ budgetRange: v })}
                  />
                </div>
              </div>
            )}

            {step === 2 && (
              <div className="space-y-6">
                <div>
                  <h2 className="text-lg font-semibold">生活方式与家庭成员</h2>
                  <p className="mt-1 text-sm text-stone-400">
                    AI 会根据生活习惯调整布局、材质与收纳设计。
                  </p>
                </div>
                <div>
                  <FieldLabel>常住人数</FieldLabel>
                  <div className="flex items-center gap-4">
                    <button
                      type="button"
                      onClick={() =>
                        update({ familySize: Math.max(1, requirement.familySize - 1) })
                      }
                      className="flex h-9 w-9 items-center justify-center rounded-xl border border-cream-300 text-stone-500 hover:border-sage-400 hover:text-sage-600"
                    >
                      <Minus className="h-4 w-4" />
                    </button>
                    <span className="w-12 text-center font-display text-xl font-semibold text-stone-800">
                      {requirement.familySize} 人
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        update({ familySize: Math.min(10, requirement.familySize + 1) })
                      }
                      className="flex h-9 w-9 items-center justify-center rounded-xl border border-cream-300 text-stone-500 hover:border-sage-400 hover:text-sage-600"
                    >
                      <Plus className="h-4 w-4" />
                    </button>
                  </div>
                </div>
                <div>
                  <FieldLabel>家庭情况与生活习惯</FieldLabel>
                  <div className="grid gap-3 sm:grid-cols-2">
                    {lifestyleOptions.map((option) => {
                      const active = requirement[option.key];
                      return (
                        <button
                          key={option.key}
                          type="button"
                          onClick={() => update({ [option.key]: !active })}
                          className={`flex items-center justify-between rounded-2xl border px-4 py-3 text-left transition-all ${
                            active
                              ? "border-sage-500 bg-sage-50"
                              : "border-cream-200 bg-white/70 hover:border-sage-300"
                          }`}
                        >
                          <span>
                            <span className="block text-sm font-medium text-stone-700">
                              {option.label}
                            </span>
                            <span className="mt-0.5 block text-xs text-stone-400">
                              {option.hint}
                            </span>
                          </span>
                          <span
                            className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
                              active ? "bg-sage-600" : "bg-cream-300"
                            }`}
                          >
                            <span
                              className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${
                                active ? "left-[22px]" : "left-0.5"
                              }`}
                            />
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}

            {step === 3 && (
              <div className="space-y-6">
                <div>
                  <h2 className="text-lg font-semibold">风格与材质偏好</h2>
                  <p className="mt-1 text-sm text-stone-400">
                    选择你喜欢的风格，我们会帮你匹配色彩、家具和材质。
                  </p>
                </div>
                <div>
                  <FieldLabel>喜欢的装修风格（可多选）</FieldLabel>
                  <PreferenceTags
                    options={styleOptions}
                    selected={requirement.styles}
                    onToggle={(v) => toggleArrayItem("styles", v)}
                  />
                </div>
                <div>
                  <FieldLabel>喜欢的主色调</FieldLabel>
                  <PreferenceTags
                    options={Object.keys(colorOptions)}
                    selected={requirement.colors}
                    onToggle={(v) => toggleArrayItem("colors", v)}
                    colorMap={colorOptions}
                  />
                </div>
                <div>
                  <FieldLabel>不喜欢的颜色</FieldLabel>
                  <PreferenceTags
                    options={Object.keys(colorOptions)}
                    selected={requirement.dislikedColors}
                    onToggle={(v) => toggleArrayItem("dislikedColors", v)}
                    colorMap={colorOptions}
                  />
                </div>
                <div>
                  <FieldLabel>喜欢的材质</FieldLabel>
                  <PreferenceTags
                    options={materialOptions}
                    selected={requirement.materials}
                    onToggle={(v) => toggleArrayItem("materials", v)}
                  />
                </div>
                <div>
                  <FieldLabel>其他想法（选填）</FieldLabel>
                  <textarea
                    rows={3}
                    placeholder="例如：希望客厅有一面书墙，喜欢暖暖的灯光…"
                    className={`${inputClass} resize-none`}
                    value={requirement.extraNotes}
                    onChange={(e) => update({ extraNotes: e.target.value })}
                  />
                </div>
              </div>
            )}
          </motion.div>
        </AnimatePresence>
      </div>

      {/* 底部按钮 */}
      <div className="mt-8 flex items-center justify-between border-t border-cream-200 pt-6">
        <Button variant="ghost" onClick={() => goto(step - 1)} disabled={step === 0}>
          <ArrowLeft className="h-4 w-4" />
          上一步
        </Button>
        {step < steps.length - 1 ? (
          <Button onClick={() => goto(step + 1)} disabled={!canNext}>
            下一步
            <ArrowRight className="h-4 w-4" />
          </Button>
        ) : (
          <Button variant="terra" onClick={() => navigate("/upload")}>
            <Sparkles className="h-4 w-4" />
            生成 AI 方案
          </Button>
        )}
      </div>
      {!canNext && (
        <p className="mt-3 text-right text-xs text-terra-600">
          请至少选择一个想改造的空间
        </p>
      )}
    </div>
  );
}
