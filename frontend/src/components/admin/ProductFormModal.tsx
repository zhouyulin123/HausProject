import { useState } from "react";
import { motion } from "framer-motion";
import { ImagePlus, Loader2, X } from "lucide-react";
import type { AdminProduct } from "@/api/designApi";
import { saveProduct, uploadProductImage } from "@/api/designApi";
import Button from "@/components/common/Button";

const inputClass =
  "w-full rounded-xl border border-cream-300 bg-white/80 px-3.5 py-2 text-sm text-stone-700 placeholder:text-stone-300 outline-none transition-colors focus:border-sage-500 focus:ring-2 focus:ring-sage-100";

const categories = ["沙发", "茶几", "床", "餐桌", "餐椅", "书桌", "书椅", "柜子", "灯具", "窗帘", "地毯"];
const rooms = ["客厅", "卧室", "餐厅", "书房", "厨房", "阳台"];
const styles = ["奶油风", "原木风", "现代简约", "北欧风", "轻奢风", "中古风", "日式风"];

type Draft = Partial<AdminProduct> & { name: string; price: number };

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-xs font-semibold text-stone-500">{label}</label>
      {children}
    </div>
  );
}

export default function ProductFormModal({
  initial,
  onClose,
  onSaved,
}: {
  initial: AdminProduct | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [draft, setDraft] = useState<Draft>(
    initial ?? { name: "", price: 0, category: "沙发", room: "客厅", style: "奶油风" },
  );
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);

  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));

  const handleImage = async (file: File) => {
    setUploading(true);
    try {
      const url = await uploadProductImage(file);
      set({ image_url: url });
    } finally {
      setUploading(false);
    }
  };

  const submit = async () => {
    if (!draft.name.trim() || !draft.price) return;
    setSaving(true);
    try {
      await saveProduct(draft);
      onSaved();
    } finally {
      setSaving(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/40 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 16 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        className="thin-scrollbar max-h-[88vh] w-full max-w-2xl overflow-y-auto rounded-3xl bg-cream-50 p-6 shadow-lift"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-stone-800">
            {initial ? "编辑产品" : "新增产品"}
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-full text-stone-400 hover:bg-cream-200 hover:text-stone-700"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <Field label="产品名称 *">
              <input
                className={inputClass}
                value={draft.name}
                onChange={(e) => set({ name: e.target.value })}
                placeholder="例如 云朵感三人位布艺沙发"
              />
            </Field>
          </div>
          <Field label="SKU 编号">
            <input
              className={inputClass}
              value={draft.sku ?? ""}
              onChange={(e) => set({ sku: e.target.value })}
              placeholder="SF-001"
            />
          </Field>
          <Field label="材质">
            <input
              className={inputClass}
              value={draft.material ?? ""}
              onChange={(e) => set({ material: e.target.value })}
              placeholder="科技布 + 白蜡木脚"
            />
          </Field>
          <Field label="类别">
            <select
              className={inputClass}
              value={draft.category ?? ""}
              onChange={(e) => set({ category: e.target.value })}
            >
              {categories.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </Field>
          <Field label="适用空间">
            <select
              className={inputClass}
              value={draft.room ?? ""}
              onChange={(e) => set({ room: e.target.value })}
            >
              {rooms.map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
          </Field>
          <Field label="风格">
            <select
              className={inputClass}
              value={draft.style ?? ""}
              onChange={(e) => set({ style: e.target.value })}
            >
              {styles.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </Field>
          <Field label="尺寸">
            <input
              className={inputClass}
              value={draft.size ?? ""}
              onChange={(e) => set({ size: e.target.value })}
              placeholder="宽 2.4m x 深 1.05m"
            />
          </Field>
          <Field label="价格（元）*">
            <input
              type="number"
              className={inputClass}
              value={draft.price || ""}
              onChange={(e) => set({ price: Number(e.target.value) })}
              placeholder="4999"
            />
          </Field>
          <Field label="价格上限（元，选填）">
            <input
              type="number"
              className={inputClass}
              value={draft.price_max ?? ""}
              onChange={(e) =>
                set({ price_max: e.target.value ? Number(e.target.value) : null })
              }
              placeholder="7299（带选配时）"
            />
          </Field>
          <div className="sm:col-span-2">
            <Field label="卖点 / 推荐语">
              <input
                className={inputClass}
                value={draft.selling_point ?? ""}
                onChange={(e) => set({ selling_point: e.target.value })}
                placeholder="科技布耐抓易清洁，坐感松弛，宠物家庭首选"
              />
            </Field>
          </div>
          <div className="sm:col-span-2">
            <Field label="替代选择">
              <input
                className={inputClass}
                value={draft.alternative ?? ""}
                onChange={(e) => set({ alternative: e.target.value })}
                placeholder="棉麻布艺款（更透气，价格低 500）"
              />
            </Field>
          </div>
          <div className="sm:col-span-2">
            <Field label="产品图">
              <div className="flex items-center gap-4">
                <div className="relative h-24 w-32 shrink-0 overflow-hidden rounded-xl border border-cream-300 bg-cream-100">
                  {draft.image_url ? (
                    <img
                      src={draft.image_url}
                      alt="产品"
                      className="h-full w-full object-cover"
                    />
                  ) : (
                    <div className="flex h-full items-center justify-center text-stone-300">
                      <ImagePlus className="h-6 w-6" />
                    </div>
                  )}
                  {uploading && (
                    <div className="absolute inset-0 flex items-center justify-center bg-white/70">
                      <Loader2 className="h-5 w-5 animate-spin text-sage-600" />
                    </div>
                  )}
                </div>
                <label className="cursor-pointer rounded-xl border border-cream-300 bg-white/70 px-4 py-2 text-sm text-stone-600 hover:border-sage-400 hover:text-sage-700">
                  选择图片
                  <input
                    type="file"
                    accept="image/*"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) void handleImage(f);
                    }}
                  />
                </label>
              </div>
            </Field>
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button onClick={() => void submit()} disabled={saving || !draft.name.trim() || !draft.price}>
            {saving ? "保存中..." : "保存"}
          </Button>
        </div>
      </motion.div>
    </motion.div>
  );
}
