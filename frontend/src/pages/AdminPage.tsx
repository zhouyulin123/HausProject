import { useEffect, useMemo, useState } from "react";
import { AnimatePresence } from "framer-motion";
import { Boxes, Pencil, Plus, Ruler, Search, Store, Trash2 } from "lucide-react";
import type { AdminProduct, QuoteRule } from "@/api/designApi";
import {
  deleteProduct,
  deleteQuoteRule,
  fetchAdminProducts,
  fetchQuoteRules,
  saveQuoteRule,
} from "@/api/designApi";
import ProductFormModal from "@/components/admin/ProductFormModal";
import ShopSettingsPanel from "@/components/admin/ShopSettingsPanel";
import PageTitle from "@/components/common/PageTitle";
import EmptyState from "@/components/common/EmptyState";
import Button from "@/components/common/Button";
import Tag from "@/components/common/Tag";

type AdminTab = "products" | "quotes" | "shop";

export default function AdminPage() {
  const [tab, setTab] = useState<AdminTab>("products");
  const [products, setProducts] = useState<AdminProduct[]>([]);
  const [rules, setRules] = useState<QuoteRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [editing, setEditing] = useState<AdminProduct | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<number | null>(null);

  const reload = async () => {
    const [p, r] = await Promise.all([fetchAdminProducts(), fetchQuoteRules()]);
    setProducts(p);
    setRules(r);
    setLoading(false);
  };

  useEffect(() => {
    void reload();
  }, []);

  const filteredProducts = useMemo(
    () =>
      products.filter(
        (p) =>
          p.name.includes(keyword) ||
          (p.sku ?? "").toLowerCase().includes(keyword.toLowerCase()),
      ),
    [products, keyword],
  );

  const openNew = () => {
    setEditing(null);
    setShowModal(true);
  };
  const openEdit = (p: AdminProduct) => {
    setEditing(p);
    setShowModal(true);
  };

  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
      <PageTitle
        title="商品库管理"
        description="维护自家成品家具与定制报价规则。这里录入的产品会直接进入 AI 方案与报价单。（内部使用）"
      />

      {/* Tab 切换 */}
      <div className="mt-6 flex gap-2">
        <button
          type="button"
          onClick={() => setTab("products")}
          className={`inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-sm font-medium transition-all ${
            tab === "products"
              ? "bg-sage-600 text-white shadow-card"
              : "border border-cream-300 bg-white/70 text-stone-600 hover:border-sage-400"
          }`}
        >
          <Boxes className="h-4 w-4" />
          成品家具 ({products.length})
        </button>
        <button
          type="button"
          onClick={() => setTab("quotes")}
          className={`inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-sm font-medium transition-all ${
            tab === "quotes"
              ? "bg-sage-600 text-white shadow-card"
              : "border border-cream-300 bg-white/70 text-stone-600 hover:border-sage-400"
          }`}
        >
          <Ruler className="h-4 w-4" />
          定制报价 ({rules.length})
        </button>
        <button
          type="button"
          onClick={() => setTab("shop")}
          className={`inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-sm font-medium transition-all ${
            tab === "shop"
              ? "bg-sage-600 text-white shadow-card"
              : "border border-cream-300 bg-white/70 text-stone-600 hover:border-sage-400"
          }`}
        >
          <Store className="h-4 w-4" />
          店铺设置
        </button>
      </div>

      {tab === "products" && (
        <div className="mt-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="relative sm:w-72">
              <Search className="absolute top-1/2 left-3.5 h-4 w-4 -translate-y-1/2 text-stone-300" />
              <input
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                placeholder="搜索产品名或 SKU"
                className="w-full rounded-xl border border-cream-300 bg-white/80 py-2.5 pr-4 pl-10 text-sm text-stone-700 outline-none placeholder:text-stone-300 focus:border-sage-500 focus:ring-2 focus:ring-sage-100"
              />
            </div>
            <Button onClick={openNew}>
              <Plus className="h-4 w-4" />
              新增产品
            </Button>
          </div>

          {loading ? (
            <div className="mt-5 space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="h-16 animate-pulse rounded-2xl bg-cream-100/70" />
              ))}
            </div>
          ) : filteredProducts.length === 0 ? (
            <div className="mt-6">
              <EmptyState
                icon={Boxes}
                title="没有产品"
                description="点击「新增产品」录入第一件，或用 Excel 批量导入。"
              />
            </div>
          ) : (
            <div className="mt-5 space-y-2">
              {filteredProducts.map((p) => (
                <div
                  key={p.id}
                  className="flex items-center gap-4 rounded-2xl border border-cream-200 bg-white/80 p-3 transition-all hover:shadow-card"
                >
                  <div className="h-14 w-16 shrink-0 overflow-hidden rounded-xl bg-cream-100">
                    {p.image_url ? (
                      <img src={p.image_url} alt={p.name} className="h-full w-full object-cover" />
                    ) : (
                      <div className="flex h-full items-center justify-center text-xs text-stone-300">
                        无图
                      </div>
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold text-stone-800">{p.name}</span>
                      {p.sku && <Tag tone="cream">{p.sku}</Tag>}
                    </div>
                    <p className="mt-0.5 truncate text-xs text-stone-400">
                      {p.category} · {p.room} · {p.style} · {p.material}
                    </p>
                  </div>
                  <span className="shrink-0 font-display text-sm font-semibold text-terra-600">
                    {p.price_text}
                  </span>
                  <div className="flex shrink-0 items-center gap-1">
                    <Button variant="ghost" size="sm" onClick={() => openEdit(p)}>
                      <Pencil className="h-4 w-4" />
                    </Button>
                    {pendingDelete === p.id ? (
                      <div className="flex items-center gap-1">
                        <Button
                          variant="terra"
                          size="sm"
                          onClick={async () => {
                            await deleteProduct(p.id);
                            setPendingDelete(null);
                            void reload();
                          }}
                        >
                          确认下架
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => setPendingDelete(null)}>
                          取消
                        </Button>
                      </div>
                    ) : (
                      <Button variant="ghost" size="sm" onClick={() => setPendingDelete(p.id)}>
                        <Trash2 className="h-4 w-4 text-stone-400" />
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === "quotes" && (
        <QuoteRulesPanel rules={rules} onChanged={reload} />
      )}

      {tab === "shop" && <ShopSettingsPanel />}

      <AnimatePresence>
        {showModal && (
          <ProductFormModal
            initial={editing}
            onClose={() => setShowModal(false)}
            onSaved={() => {
              setShowModal(false);
              void reload();
            }}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

// ---------------------------------------------------------------- 定制报价面板

const units = ["㎡", "延米", "米", "项"];

function QuoteRulesPanel({
  rules,
  onChanged,
}: {
  rules: QuoteRule[];
  onChanged: () => Promise<void>;
}) {
  const [draft, setDraft] = useState({
    project_name: "",
    category: "柜类定制",
    pricing_unit: "㎡",
    material_grade: "",
    unit_price: 0,
    description: "",
  });

  const add = async () => {
    if (!draft.project_name.trim() || !draft.unit_price) return;
    await saveQuoteRule(draft);
    setDraft({ ...draft, project_name: "", material_grade: "", unit_price: 0, description: "" });
    void onChanged();
  };

  const inputClass =
    "rounded-xl border border-cream-300 bg-white/80 px-3 py-2 text-sm text-stone-700 placeholder:text-stone-300 outline-none focus:border-sage-500 focus:ring-2 focus:ring-sage-100";

  return (
    <div className="mt-6">
      {/* 新增行 */}
      <div className="grid gap-2 rounded-2xl border border-cream-200 bg-white/80 p-4 sm:grid-cols-[1.4fr_1.2fr_0.8fr_0.9fr_auto]">
        <input
          className={inputClass}
          placeholder="项目名（定制衣柜）"
          value={draft.project_name}
          onChange={(e) => setDraft((d) => ({ ...d, project_name: e.target.value }))}
        />
        <input
          className={inputClass}
          placeholder="材料档位（多层实木）"
          value={draft.material_grade}
          onChange={(e) => setDraft((d) => ({ ...d, material_grade: e.target.value }))}
        />
        <input
          type="number"
          className={inputClass}
          placeholder="单价"
          value={draft.unit_price || ""}
          onChange={(e) => setDraft((d) => ({ ...d, unit_price: Number(e.target.value) }))}
        />
        <select
          className={inputClass}
          value={draft.pricing_unit}
          onChange={(e) => setDraft((d) => ({ ...d, pricing_unit: e.target.value }))}
        >
          {units.map((u) => (
            <option key={u}>{u}</option>
          ))}
        </select>
        <Button onClick={() => void add()} disabled={!draft.project_name.trim() || !draft.unit_price}>
          <Plus className="h-4 w-4" />
          添加
        </Button>
      </div>

      <div className="mt-4 overflow-hidden rounded-2xl border border-cream-200">
        <table className="w-full text-sm">
          <thead className="bg-cream-100 text-left text-xs text-stone-500">
            <tr>
              <th className="px-4 py-2.5 font-medium">项目</th>
              <th className="px-4 py-2.5 font-medium">材料档位</th>
              <th className="px-4 py-2.5 text-right font-medium">单价</th>
              <th className="px-4 py-2.5 font-medium">单位</th>
              <th className="px-4 py-2.5"></th>
            </tr>
          </thead>
          <tbody>
            {rules.map((r) => (
              <tr key={r.id} className="border-t border-cream-100">
                <td className="px-4 py-2.5 font-medium text-stone-700">{r.project_name}</td>
                <td className="px-4 py-2.5 text-stone-500">{r.material_grade ?? "-"}</td>
                <td className="px-4 py-2.5 text-right font-medium text-terra-600">
                  ¥{r.unit_price.toLocaleString()}
                </td>
                <td className="px-4 py-2.5 text-stone-500">/{r.pricing_unit}</td>
                <td className="px-4 py-2.5 text-right">
                  <button
                    type="button"
                    onClick={async () => {
                      await deleteQuoteRule(r.id);
                      void onChanged();
                    }}
                    className="text-stone-400 hover:text-terra-600"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
